"""运行日志 — Agent 每次调用落库（可观测性 + golden 飞轮数据源）

设计约束：日志失败绝不能影响主流程（编辑器不能挂），所有异常吞掉只留 warning。
status 判定优先级：显式 error > result.error / "AI 处理失败" 回复 > fallback trace >
interrupt 挂起 > success。
"""

import logging
from typing import Any, Dict

from app.database import SessionLocal
from app.models.agent_run import AgentRun

logger = logging.getLogger(__name__)

PROMPT_STORE_LIMIT = 500
REPLY_STORE_LIMIT = 500
ERROR_STORE_LIMIT = 500


def _truncate(value, limit: int) -> str:
    return str(value)[:limit] if value else ""


def _extract_corrections(result: Dict[str, Any]) -> list[dict]:
    """从 trace 中提取自省修正轮次摘要（eval golden 候选的核心信号）"""
    trace = result.get("trace") or []
    return [
        {
            "type": entry.get("error"),
            "step": entry.get("step"),
            "detail": {
                key: entry[key]
                for key in ("rejectedTools", "unresolvedRefs", "execution")
                if key in entry
            },
        }
        for entry in trace
        if isinstance(entry, dict) and entry.get("type") == "correction"
    ]


def _resolve_status(result: Dict[str, Any], error: str | None) -> str:
    if error:
        return "error"
    if result.get("__interrupt__") or result.get("waitingForInput"):
        return "waiting"
    reply = str(result.get("reply") or "")
    if reply.startswith("AI 处理失败") or result.get("error"):
        return "error"
    trace = result.get("trace") or []
    if any(isinstance(entry, dict) and entry.get("tool") == "local_fallback" for entry in trace):
        return "degraded"
    return "success"


def log_agent_run(
    source: str,
    thread_id: str | None,
    stage: str | None,
    result: Dict[str, Any],
    duration_ms: int,
    error: str | None = None,
    prompt: str = "",
) -> None:
    """记录一次 Agent 运行。任何异常都吞掉（日志是旁路，不是主链路）。"""
    try:
        if result.get("__interrupt__"):
            first = result["__interrupt__"][0]
            # LangGraph Interrupt 对象带 .value 属性；测试/普通 dict 用 ["value"]
            value = getattr(first, "value", None)
            if value is None and isinstance(first, dict):
                value = first.get("value")
            inner = (value or {}).get("payload") or {}
            reply = inner.get("reply", "")
        else:
            reply = result.get("reply", "")

        run = AgentRun(
            thread_id=_truncate(thread_id, 100),
            stage=_truncate(stage, 20),
            status=_resolve_status(result, error),
            source=source,
            prompt=_truncate(prompt, PROMPT_STORE_LIMIT),
            reply=_truncate(reply, REPLY_STORE_LIMIT),
            error=_truncate(error or result.get("error") or "", ERROR_STORE_LIMIT),
            actions_count=len(result.get("actions") or []),
            corrections=_extract_corrections(result),
            validation=_compact_validation(result.get("validation")),
            duration_ms=int(duration_ms),
        )
        with SessionLocal() as db:
            db.add(run)
            db.commit()
    except Exception as exc:  # noqa: BLE001 — 旁路日志绝不抛出
        logger.warning("[AI] failed to log agent run: %s", exc)


def _compact_validation(validation: Dict[str, Any] | None) -> dict | None:
    if not isinstance(validation, dict):
        return None
    return {
        "valid": validation.get("valid"),
        "errorCount": validation.get("errorCount"),
        "warningCount": validation.get("warningCount"),
    }

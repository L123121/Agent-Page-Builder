"""SSE 流式执行 — Agent 每步工具调用都产出进度事件。

与 run_agent（一次性返回）共享同一张图（graph.agent_graph）、阶段路由、
请求预处理（run_context）与结果提取（graph.extract_graph_result）。

流式采用双通道（stream_mode=["custom", "updates"]）：
- custom：节点内经 _stream_emit 实时推送 tool_call / tool_result /
  self_correction——executor 闭环可能跑数分钟，旧实现等整个节点结束才从
  trace 回放事件，用户全程只看到 agent_start；现在每步完成即刻可见；
- updates：节点返回值与 __interrupt__ 块，用于 agent_done（含挂起协议）。

custom 与 trace 回放通过 (step, type) 去重：正常路径事件实时推送、
不再回放；节点异常降级（如 local_fallback）等未实时推送的 trace 条目
仍按旧协议补发，保证事件协议向后兼容。

关键协议点：planner 等待用户输入时由 await_user 节点 interrupt 挂起，
在 updates 流中以 __interrupt__ 块出现——这里把挂起载荷合成为带
waitingForInput=true 的 agent_done 事件，前端由此渲染卡片并保存 threadId。
事件协议见 routers/ai.py 的 /chat/stream 文档。
"""

import logging
import time
from typing import Any, Dict, List

from langgraph.types import Command

from app.config import settings

from .graph import agent_graph, ensure_checkpointer_ready, extract_graph_result, has_pending_interrupt
from .run_context import build_graph_config, build_initial_state
from .run_logger import log_agent_run

logger = logging.getLogger(__name__)


async def run_agent_streaming(
    prompt: str,
    image: str | None = None,
    history: List[Dict[str, str]] | None = None,
    components: List[Dict[str, Any]] | None = None,
    canvas_style: Dict[str, Any] | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
    selected_component_ids: List[str] | None = None,
    viewport: Dict[str, Any] | None = None,
    project_knowledge: str = "",
    conversation_stage: str | None = None,
    thread_id: str | None = None,
    resume: Any | None = None,
):
    """流式版 Agent：async generator，每步工具调用都 yield 进度事件。

    事件类型：
      {"type": "agent_start", "stage": "discover"}
      {"type": "tool_call", "step": 1, "tool": "generate_page"}
      {"type": "tool_result", "step": 1, "tool": "generate_page", "status": "done",
       "validation": {...}, "autoFixes": [...]}
      {"type": "self_correction", "step": 2, "error": "unresolved_component_ref", ...}
      {"type": "agent_done", "result": {...}}
        - 正常完成：reply/actions/nextStage/validation/trace/threadId
        - planner 挂起：reply/options/question/plan/nextStage/threadId/waitingForInput=true
      {"type": "agent_error", "error": "..."}
    """
    initial_state, stage = build_initial_state(
        prompt=prompt,
        image=image,
        history=history,
        components=components,
        canvas_style=canvas_style,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        selected_component_ids=selected_component_ids,
        viewport=viewport,
        project_knowledge=project_knowledge,
        conversation_stage=conversation_stage,
    )

    yield {"type": "agent_start", "stage": stage}

    if not settings.AI_API_KEY:
        yield {"type": "agent_error", "error": "AI_API_KEY is not configured"}
        return

    config = build_graph_config(thread_id)
    started = time.monotonic()

    def _log_run(result_payload: dict, error: str | None = None) -> None:
        log_agent_run(
            "chat_stream",
            config["configurable"]["thread_id"],
            stage,
            result_payload,
            int((time.monotonic() - started) * 1000),
            error=error,
            prompt=prompt,
        )

    # 已实时推送的事件键，防止节点结束后 trace 回放造成前端重复步骤卡片
    emitted: set[tuple] = set()

    try:
        # redis 后端首次使用前建索引（memory 后端 no-op）；失败走 agent_error 路径
        await ensure_checkpointer_ready()
        # resume 前置检查：线程确实挂起才走恢复；checkpoint 丢失（重启/TTL 淘汰）
        # 或已无挂起点时降级为新请求执行，前端无需感知差异
        resume_command = None
        if resume is not None and await has_pending_interrupt(agent_graph, config):
            resume_command = Command(resume=resume)
        stream_input = resume_command if resume_command is not None else initial_state
        # 双通道：custom 实时进度 + updates 节点结果（挂起时为 __interrupt__）
        async for mode, chunk in agent_graph.astream(
            stream_input, config=config, stream_mode=["custom", "updates"]
        ):
            if mode == "custom":
                # 节点内实时推送的 tool_call / tool_result / self_correction
                emitted.add((chunk.get("step"), chunk.get("type")))
                yield chunk
                continue

            for node_name, node_output in chunk.items():
                if node_name == "__interrupt__":
                    # planner 挂起等待用户输入：与 run_agent 非流式协议保持一致
                    waiting_result = extract_graph_result(
                        {"__interrupt__": node_output}, stage, config["configurable"]["thread_id"]
                    )
                    _log_run(waiting_result)
                    yield {"type": "agent_done", "result": waiting_result}
                    continue
                if node_name == "executor":
                    # executor 返回 {"result": {reply/actions/nextStage/validation/trace}}
                    result = (node_output or {}).get("result", {})
                    if not isinstance(result, dict):
                        continue
                    trace = result.get("trace", [])
                    # 补发未实时推送的 trace 条目（节点异常降级等边缘路径）
                    for entry in _unemitted_trace_entries(trace, emitted):
                        yield entry
                    _log_run(result)
                    yield {
                        "type": "agent_done",
                        "result": {
                            "reply": result.get("reply", ""),
                            "actions": result.get("actions", []),
                            "nextStage": result.get("nextStage", "edit"),
                            "validation": result.get("validation"),
                            "trace": trace,
                            "threadId": config["configurable"]["thread_id"],
                            "waitingForInput": False,
                        },
                    }
                elif node_name == "planner":
                    # planner 产出挂起载荷时 __interrupt__ 块随后到达，这里不发 done
                    if (node_output or {}).get("pending_input"):
                        continue
                    # planner 正常完成（产出动作或降级回复）
                    result = (node_output or {}).get("result", {})
                    if not isinstance(result, dict):
                        continue
                    _log_run(result)
                    yield {
                        "type": "agent_done",
                        "result": {
                            "reply": result.get("reply", ""),
                            "actions": result.get("actions", []),
                            "nextStage": result.get("nextStage", "edit"),
                            "threadId": config["configurable"]["thread_id"],
                            "waitingForInput": False,
                        },
                    }
    except Exception as e:
        logger.error(f"[AI] Agent streaming failed: {e}", exc_info=True)
        _log_run({"reply": f"AI 处理失败: {e}"}, error=str(e))
        yield {"type": "agent_error", "error": str(e)}


def _unemitted_trace_entries(trace: list, emitted: set[tuple]) -> list[dict]:
    """把 trace 中未实时推送的条目转成协议事件（顺序：tool_call → tool_result）。

    correction 类型（自省修正轮次）映射为 self_correction 事件。
    """
    events: list[dict] = []
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "correction":
            if (entry.get("step"), "self_correction") in emitted:
                continue
            events.append({
                "type": "self_correction",
                "step": entry.get("step"),
                "error": entry.get("error"),
                "detail": {
                    key: value for key, value in entry.items()
                    if key not in ("type", "step", "error", "execution", "autoFixes")
                },
            })
            continue
        if (entry.get("step"), "tool_call") in emitted:
            continue
        events.append({
            "type": "tool_call",
            "step": entry.get("step"),
            "tool": entry.get("tool"),
        })
        events.append({
            "type": "tool_result",
            "step": entry.get("step"),
            "tool": entry.get("tool"),
            "status": "done",
            "validation": entry.get("validation"),
            "autoFixes": entry.get("autoFixes", []),
        })
    return events

"""SSE 流式执行 — Agent 每步工具调用都产出进度事件。

与 run_agent（一次性返回）共享同一张图（graph.agent_graph）、阶段路由与
结果提取（graph.extract_graph_result），区别在于用 astream(stream_mode="updates")
逐节点产出，前端可实时展示「正在调用什么工具、验证结果如何」。

关键协议点：planner 等待用户输入（选项/提问/方案确认）通过 interrupt 挂起，
在 updates 流中以 __interrupt__ 块出现而非节点返回值——这里把挂起载荷合成为
带 waitingForInput=true 的 agent_done 事件，前端由此渲染卡片并保存 threadId。
事件协议见 routers/ai.py 的 /chat/stream 文档。
"""

import logging
import time
from typing import Any, Dict, List

from langgraph.types import Command

from app.config import settings
from app.utils.id_generator import generate_id

from .graph import agent_graph, extract_graph_result, has_pending_interrupt
from .run_logger import log_agent_run
from .schemas import AgentState
from .stage_routing import resolve_stage
from .tools import TOOLS_BY_STAGE

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
        - 正常完成：reply/actions/nextStage/validation/trace
        - planner 挂起：reply/options/question/plan/nextStage/threadId/waitingForInput=true
      {"type": "agent_error", "error": "..."}
    """
    history = history or []
    components = components or []
    selected_component_ids = selected_component_ids or []
    cw = canvas_width or (canvas_style.get("width") if canvas_style else None) or 375
    ch = canvas_height or (canvas_style.get("height") if canvas_style else None) or 667
    stage = resolve_stage(prompt, components, conversation_stage)

    messages = list(history)
    # 全模态消息：图片作为 image_url 块 + 文字一起发给模型
    if image:
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image}},
                {"type": "text", "text": prompt},
            ],
        })
    else:
        messages.append({"role": "user", "content": prompt})

    yield {"type": "agent_start", "stage": stage}

    if not settings.AI_API_KEY:
        yield {"type": "agent_error", "error": "AI_API_KEY is not configured"}
        return

    initial_state: AgentState = {
        "messages": messages,
        "prompt": prompt,
        "components": components,
        "canvas_style": canvas_style or {},
        "canvas_width": cw,
        "canvas_height": ch,
        "selected_component_ids": selected_component_ids,
        "viewport": viewport or {"width": cw, "height": ch, "scale": (canvas_style or {}).get("scale", 100)},
        "project_knowledge": project_knowledge,
        "requested_stage": conversation_stage,
        "stage": stage,
        "allowed_tools": TOOLS_BY_STAGE[stage],
        "result": {"reply": "", "actions": []},
        "plan": None,
    }

    config = {
        "configurable": {
            "thread_id": thread_id or f"anon-{generate_id(8)}",
        }
    }
    # resume 前置检查：线程确实挂起才走恢复；checkpoint 丢失（重启/TTL 淘汰）
    # 或已无挂起点时降级为新请求执行，前端无需感知差异
    resume_command = None
    if resume is not None and await has_pending_interrupt(agent_graph, config):
        resume_command = Command(resume=resume)

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

    try:
        stream_input = resume_command if resume_command is not None else initial_state
        # stream_mode="updates"：每步产出 {node_name: node_output}（挂起时为 __interrupt__）
        async for chunk in agent_graph.astream(stream_input, config=config, stream_mode="updates"):
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
                    for entry in trace:
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("type") == "correction":
                            yield {
                                "type": "self_correction",
                                "step": entry.get("step"),
                                "error": entry.get("error"),
                                "detail": {
                                    key: value for key, value in entry.items()
                                    if key not in ("type", "step", "error", "execution", "autoFixes")
                                },
                            }
                            continue
                        yield {
                            "type": "tool_call",
                            "step": entry.get("step"),
                            "tool": entry.get("tool"),
                        }
                        yield {
                            "type": "tool_result",
                            "step": entry.get("step"),
                            "tool": entry.get("tool"),
                            "status": "done",
                            "validation": entry.get("validation"),
                            "autoFixes": entry.get("autoFixes", []),
                        }
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
                    # planner 正常完成（产出动作或降级回复）；挂起走 __interrupt__ 分支
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

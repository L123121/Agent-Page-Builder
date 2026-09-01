"""SSE 流式执行 — Agent 每步工具调用都产出进度事件。

与 run_agent（一次性返回）共享同一张图（graph.agent_graph）与阶段路由，
区别在于用 astream 逐节点产出，前端可实时展示「正在调用什么工具、
验证结果如何」。事件协议见 routers/ai.py 的 /chat/stream 文档。
"""

import logging
from typing import Any, Dict, List

from app.config import settings

from .graph import agent_graph
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
):
    """流式版 Agent：async generator，每步工具调用都 yield 进度事件。

    事件类型：
      {"type": "agent_start", "stage": "discover"}
      {"type": "tool_call", "step": 1, "tool": "propose_options", "args": {...}}
      {"type": "tool_result", "step": 1, "tool": "propose_options", "status": "done", "validation": {...}}
      {"type": "agent_done", "result": {...}}
      {"type": "agent_error", "error": "..."}
    """
    from app.utils.id_generator import generate_id

    history = history or []
    components = components or []
    selected_component_ids = selected_component_ids or []
    cw = canvas_width or (canvas_style.get("width") if canvas_style else None) or 375
    ch = canvas_height or (canvas_style.get("height") if canvas_style else None) or 667
    stage = resolve_stage(prompt, components, conversation_stage)

    messages = list(history)
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

    yield {"type": "agent_start", "stage": "edit" if stage == "edit" else "execute"}

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

    try:
        # 流式执行 LangGraph：astream 逐节点产出结果
        async for node_name, node_output in agent_graph.astream(initial_state, config=config):
            if node_name == "executor":
                # executor 节点产出 trace 数组，逐条 yield
                trace = node_output.get("trace", [])
                for entry in trace:
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
                # executor 完成后的最终结果
                result = node_output.get("result", {})
                if isinstance(result, dict):
                    yield {
                        "type": "agent_done",
                        "result": {
                            "reply": result.get("reply", ""),
                            "actions": result.get("actions", []),
                            "nextStage": result.get("nextStage", "edit"),
                            "validation": result.get("validation"),
                            "trace": trace,
                            "threadId": config["configurable"]["thread_id"],
                        },
                    }
            elif node_name == "planner":
                # planner 产出：选项/问题/方案
                result = node_output.get("result", {})
                if isinstance(result, dict):
                    if result.get("options"):
                        yield {"type": "tool_call", "tool": "propose_options"}
                        yield {
                            "type": "tool_result",
                            "tool": "propose_options",
                            "status": "waiting_for_user",
                            "options": result.get("options"),
                            "threadId": config["configurable"]["thread_id"],
                        }
                    elif result.get("question"):
                        yield {"type": "tool_call", "tool": "ask_question"}
                        yield {
                            "type": "tool_result",
                            "tool": "ask_question",
                            "status": "waiting_for_user",
                            "question": result.get("question"),
                            "suggestions": result.get("suggestions"),
                            "threadId": config["configurable"]["thread_id"],
                        }
                    elif result.get("plan"):
                        yield {"type": "tool_call", "tool": "confirm_plan"}
                        yield {
                            "type": "tool_result",
                            "tool": "confirm_plan",
                            "status": "waiting_for_user",
                            "plan": result.get("plan"),
                            "threadId": config["configurable"]["thread_id"],
                        }
                    else:
                        yield {
                            "type": "agent_done",
                            "result": {
                                "reply": result.get("reply", ""),
                                "actions": result.get("actions", []),
                                "nextStage": result.get("nextStage", "edit"),
                                "threadId": config["configurable"]["thread_id"],
                            },
                        }
    except Exception as e:
        logger.error(f"[AI] Agent streaming failed: {e}", exc_info=True)
        yield {"type": "agent_error", "error": str(e)}

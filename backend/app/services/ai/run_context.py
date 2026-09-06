"""请求预处理 — run_agent（非流式）与 run_agent_streaming（SSE）共用的输入规范化。

两条链路的请求参数完全一致，此前各自维护一份 ~40 行的初始状态构建逻辑，
容易漂移；这里统一收敛：输入默认值、画布尺寸兜底、阶段路由、消息构建
（含多模态图片块）、初始图状态与执行配置。
"""

from typing import Any, Dict, List

from app.config import settings
from app.utils.id_generator import generate_id

from .schemas import AgentState
from .stage_routing import resolve_stage
from .tools import TOOLS_BY_STAGE


def build_initial_state(
    prompt: str,
    image: str | None,
    history: List[Dict[str, str]] | None,
    components: List[Dict[str, Any]] | None,
    canvas_style: Dict[str, Any] | None,
    canvas_width: int | None,
    canvas_height: int | None,
    selected_component_ids: List[str] | None,
    viewport: Dict[str, Any] | None,
    project_knowledge: str,
    conversation_stage: str | None,
) -> tuple[AgentState, str]:
    """构建图的初始状态；返回 (initial_state, 解析后的阶段)。"""
    history = history or []
    components = components or []
    selected_component_ids = selected_component_ids or []
    cw = canvas_width or (canvas_style.get("width") if canvas_style else None) or 375
    ch = canvas_height or (canvas_style.get("height") if canvas_style else None) or 667
    stage = resolve_stage(prompt, components, conversation_stage)

    messages = list(history)
    # 全模态消息：图片作为 image_url 块 + 文字一起发给模型（仅首轮携带）
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
        "pending_input": None,
        "interrupt_rounds": 0,
    }
    return initial_state, stage


def build_graph_config(thread_id: str | None) -> dict:
    """图执行配置：会话线程 + 交互轮数对应的递归上限。

    递归步数 = route(1) + 每轮用户交互 planner/await_user 各 1 步，
    上限按最大交互轮数换算并留余量。
    """
    max_interrupt_rounds = getattr(settings, "AI_MAX_INTERRUPT_ROUNDS", 10)
    return {
        "configurable": {
            "thread_id": thread_id or f"anon-{generate_id(8)}",
        },
        "recursion_limit": 2 * max_interrupt_rounds + 6,
    }

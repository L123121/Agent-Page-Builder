"""AI Agent 公开接口与模块门面。

内部按职责拆分：
- stage_routing    确定性阶段路由（短语表 + 状态机）
- tool_handlers    工具响应解析、组件引用解析、动作转换
- agent_nodes      planner / executor 节点（LLM 决策与闭环执行）
- graph            LangGraph 组装与 checkpointer
- agent_streaming  SSE 流式执行
- validator        确定性画布验证与自动修复

本模块只保留 run_agent 入口与向后兼容的再导出
（tests / eval / router 历史上从 app.services.ai.agent 导入）。
"""

import logging
from typing import Any, Dict, List

from langgraph.types import Command

from app.config import settings

from .agent_nodes import executor_node, planner_node  # noqa: F401 (再导出)
from .agent_streaming import run_agent_streaming  # noqa: F401 (再导出)
from .fallback import run_fallback_agent
from .graph import agent_graph
from .stage_routing import next_stage_for_tool, resolve_stage  # noqa: F401 (再导出)
from .tool_handlers import _gen_id, process_tool_response  # noqa: F401 (再导出)
from .tools import TOOLS_BY_STAGE, tools_for_stage  # noqa: F401 (再导出)

logger = logging.getLogger(__name__)


# ==================== 公开接口 ====================

async def run_agent(
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
) -> Dict[str, Any]:
    """运行 AI Agent：先路由阶段，再在阶段内执行一个工具。

    image:     参考图 data URL (image/...)，全模态模型直接"看到"图片 + 文字，
               无需前置解析。仅首轮携带，后续多轮对话不带。
    thread_id: 会话标识。同一 thread_id 下的执行状态由 checkpointer 持久化，
               支持 interrupt 挂起后用 `resume` 恢复，失败后可从最近 checkpoint 继续。
    resume:    中断恢复数据。传值时 LangGraph 从上次 interrupt 处继续执行，
                不会重复执行已完成的节点。
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

    initial_state: Dict[str, Any] = {
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

    if not settings.AI_API_KEY:
        return run_fallback_agent(initial_state, "AI_API_KEY is not configured")

    config = {
        "configurable": {
            "thread_id": thread_id or f"anon-{_gen_id(8)}",
        }
    }
    try:
        if resume is not None:
            # 从上次 interrupt 挂起点继续执行（不重复已完成的节点）
            result = await agent_graph.ainvoke(Command(resume=resume), config=config)
        else:
            result = await agent_graph.ainvoke(initial_state, config=config)
        return _extract_result(result, stage, config)
    except Exception as e:
        logger.error(f"[AI] Agent failed: {e}", exc_info=True)
        return {"reply": f"AI 处理失败: {str(e)}", "actions": [], "nextStage": stage}


def _extract_result(result: Dict[str, Any], stage: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """从 LangGraph 返回值中提取前端可用的结果。

    - 正常结束：返回节点写入的 result。
    - interrupt 挂起（等待用户输入）：把挂起载荷（选项/问题/方案）转成响应，
      并附带 thread_id，前端后续请求凭 thread_id + resume 恢复执行。
    """
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = dict(interrupts[0].value)
        inner = payload.get("payload") or {}
        return {
            "reply": inner.get("reply", ""),
            "actions": [],
            "options": inner.get("options"),
            "question": inner.get("question"),
            "suggestions": inner.get("suggestions"),
            "plan": inner.get("plan"),
            "nextStage": payload.get("nextStage") or inner.get("nextStage") or stage,
            "threadId": config["configurable"]["thread_id"],
            "waitingForInput": True,
        }
    # 正常结束：返回节点写入的 result，并透传 planner 确认的方案（供评测/前端使用）
    normal_result = result.get("result", {"reply": "", "actions": []})
    if isinstance(normal_result, dict) and result.get("plan") is not None:
        normal_result = {**normal_result, "plan": result["plan"]}
    return normal_result

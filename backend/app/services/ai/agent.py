"""AI Agent 公开接口与模块门面。

内部按职责拆分：
- stage_routing    确定性阶段路由（短语表 + 状态机）
- run_context      请求预处理（非流式/流式共用）
- tool_handlers    工具响应解析、参数校验、组件引用解析、动作转换
- agent_nodes      planner / await_user / executor 节点（LLM 决策与闭环执行）
- graph            LangGraph 组装与 checkpointer
- agent_streaming  SSE 流式执行
- validator        确定性画布验证与自动修复

本模块只保留 run_agent 入口与向后兼容的再导出
（tests / eval / router 历史上从 app.services.ai.agent 导入）。
"""

import logging
import time
from typing import Any, Dict, List

from langgraph.types import Command

from app.config import settings

from .agent_nodes import await_user_node, executor_node, planner_node  # noqa: F401 (再导出)
from .agent_streaming import run_agent_streaming  # noqa: F401 (再导出)
from .fallback import run_fallback_agent
from .graph import agent_graph, ensure_checkpointer_ready, extract_graph_result, has_pending_interrupt
from .run_context import build_graph_config, build_initial_state
from .run_logger import log_agent_run
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

    if not settings.AI_API_KEY:
        fallback_result = run_fallback_agent(initial_state, "AI_API_KEY is not configured")
        log_agent_run("chat", thread_id, stage, fallback_result, 0, prompt=prompt)
        return fallback_result

    config = build_graph_config(thread_id)
    started = time.monotonic()
    try:
        # redis 后端首次使用前建索引（memory 后端 no-op）；失败走统一错误路径
        await ensure_checkpointer_ready()
        if resume is not None and await has_pending_interrupt(agent_graph, config):
            # 从上次 interrupt 挂起点继续执行（不重复已完成的节点）；
            # checkpoint 丢失或无挂起点时降级为新请求执行
            result = await agent_graph.ainvoke(Command(resume=resume), config=config)
        else:
            result = await agent_graph.ainvoke(initial_state, config=config)
        extracted = extract_graph_result(result, stage, config["configurable"]["thread_id"])
        log_agent_run(
            "chat",
            config["configurable"]["thread_id"],
            stage,
            extracted,
            int((time.monotonic() - started) * 1000),
            prompt=prompt,
        )
        return extracted
    except Exception as e:
        logger.error(f"[AI] Agent failed: {e}", exc_info=True)
        failure = {"reply": f"AI 处理失败: {str(e)}", "actions": [], "nextStage": stage}
        log_agent_run(
            "chat",
            config["configurable"]["thread_id"],
            stage,
            failure,
            int((time.monotonic() - started) * 1000),
            error=str(e),
            prompt=prompt,
        )
        return failure

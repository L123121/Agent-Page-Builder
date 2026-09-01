"""LangGraph 组装 — route → planner / executor 条件边 + 状态检查点。

图结构：
  route（确定性路由，定阶段与白名单）
    ├─ planner（discover/design/plan/confirm：LLM 决策 + interrupt 人工介入）
    └─ executor（execute/edit：执行 → 验证 → 修复闭环）

checkpointer 用于同一 thread_id 下的状态持久化与 interrupt 恢复；
默认 MemorySaver（进程内），配置 AI_CHECKPOINT_BACKEND=redis 时用 RedisSaver
（跨进程持久化，初始化失败自动回退内存实现）。
"""

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.config import settings

from .agent_nodes import executor_node, planner_node
from .schemas import AgentState
from .stage_routing import resolve_stage
from .tools import TOOLS_BY_STAGE

logger = logging.getLogger(__name__)


def route_request(state: AgentState) -> dict:
    """LangGraph 路由节点：在模型调用前确定阶段和工具白名单。"""
    stage = resolve_stage(state["prompt"], state["components"], state.get("requested_stage"))
    return {"stage": stage, "allowed_tools": TOOLS_BY_STAGE[stage]}


def select_execution_node(state: AgentState) -> str:
    """条件边：需求分析阶段走 planner，执行/编辑阶段走 executor。"""
    return "executor" if state["stage"] in {"execute", "edit"} else "planner"


def _build_checkpointer():
    """按配置构建状态检查点：默认 MemorySaver，配置 redis 时尝试 RedisSaver。"""
    backend = getattr(settings, "AI_CHECKPOINT_BACKEND", "memory").lower()
    if backend == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver
            redis_url = getattr(settings, "AI_REDIS_URL", "") or "redis://localhost:6379"
            return RedisSaver.from_conn_string(redis_url)
        except Exception as error:
            logger.warning("[AI] RedisSaver 不可用（%s），回退 MemorySaver", error)
    return MemorySaver()


def _build_agent_graph():
    """构建并编译 LangGraph：route → planner（需求分析）/ executor（画布执行）。"""
    workflow = StateGraph(AgentState)
    workflow.add_node("route", route_request)
    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.set_entry_point("route")
    workflow.add_conditional_edges(
        "route",
        select_execution_node,
        {"planner": "planner", "executor": "executor"},
    )
    workflow.add_edge("planner", END)
    workflow.add_edge("executor", END)
    return workflow.compile(checkpointer=_build_checkpointer())


# 模块级单例图（启动时编译一次）
agent_graph = _build_agent_graph()

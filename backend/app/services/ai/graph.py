"""LangGraph 组装 — route → planner / executor 条件边 + 状态检查点。

图结构：
  route（确定性路由，定阶段与工具白名单）
    ├─ planner（discover/design/plan/confirm：LLM 决策 + interrupt 人工介入）
    └─ executor（execute/edit：执行 → 验证 → 修复闭环）

checkpointer 用于同一 thread_id 下的状态持久化与 interrupt 恢复；
默认 TTLMemorySaver（进程内 + 线程 TTL/容量淘汰），配置 AI_CHECKPOINT_BACKEND=redis
时用 RedisSaver（跨进程持久化，初始化失败自动回退内存实现）。
"""

import logging
import time
from datetime import datetime

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.config import settings

from .agent_nodes import executor_node, planner_node
from .schemas import AgentState
from .stage_routing import resolve_stage
from .tools import TOOLS_BY_STAGE

logger = logging.getLogger(__name__)

# 淘汰扫描最小间隔：checkpoint 写入频率高，没必要每次都全量扫
_SWEEP_MIN_INTERVAL_SECONDS = 60.0


class TTLMemorySaver(MemorySaver):
    """带线程 TTL 与容量上限的进程内 checkpointer。

    MemorySaver 按 thread 无限累积（完整对话 + 画布状态），长期运行会持续增长；
    这里在每次写入时做摊销扫描：
    - 超过 TTL 未活跃的线程整条淘汰（配合请求侧「resume 前检查挂起状态 +
      降级为新请求」，淘汰线程上的恢复请求也能正常工作）；
    - 线程数超过上限时按最近活跃时间 LRU 淘汰。
    """

    def __init__(self, ttl_seconds: int = 3600, max_threads: int = 500) -> None:
        super().__init__()
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.max_threads = max(1, int(max_threads))
        self._last_sweep = 0.0

    def put(self, config, checkpoint, metadata, new_versions):
        self._sweep(exclude_thread=config["configurable"]["thread_id"])
        return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        self._sweep(exclude_thread=config["configurable"]["thread_id"])
        return super().put_writes(config, writes, task_id, task_path)

    def _thread_last_active(self, thread_id: str) -> float:
        """线程最新 checkpoint 的时间戳（checkpoint['ts'] 为 ISO 字符串）。"""
        latest = 0.0
        for checkpoints in self.storage.get(thread_id, {}).values():
            for (checkpoint_blob, _metadata_blob, _parent_id) in checkpoints.values():
                try:
                    checkpoint = self.serde.loads_typed(checkpoint_blob)
                    latest = max(latest, datetime.fromisoformat(checkpoint["ts"]).timestamp())
                except Exception:
                    continue
        return latest

    def _sweep(self, exclude_thread: str | None = None, force: bool = False) -> None:
        now = time.time()
        within_interval = now - self._last_sweep < _SWEEP_MIN_INTERVAL_SECONDS
        if (not force and within_interval) or not self.storage:
            return
        self._last_sweep = now

        if self.ttl_seconds > 0:
            expired = [
                thread_id
                for thread_id in list(self.storage)
                if thread_id != exclude_thread
                and now - self._thread_last_active(thread_id) > self.ttl_seconds
            ]
            for thread_id in expired:
                self._drop_thread(thread_id)
            if expired:
                logger.info("[AI] checkpointer evicted %d expired threads", len(expired))

        while len(self.storage) > self.max_threads:
            oldest = min(
                (thread_id for thread_id in self.storage if thread_id != exclude_thread),
                key=self._thread_last_active,
                default=None,
            )
            if oldest is None:
                break
            self._drop_thread(oldest)

    def _drop_thread(self, thread_id: str) -> None:
        self.storage.pop(thread_id, None)
        for key in [key for key in self.writes if key[0] == thread_id]:
            del self.writes[key]
        for key in [key for key in self.blobs if key[0] == thread_id]:
            del self.blobs[key]


def route_request(state: AgentState) -> dict:
    """LangGraph 路由节点：在模型调用前确定阶段和工具白名单。"""
    stage = resolve_stage(state["prompt"], state["components"], state.get("requested_stage"))
    return {"stage": stage, "allowed_tools": TOOLS_BY_STAGE[stage]}


def select_execution_node(state: AgentState) -> str:
    """条件边：需求分析阶段走 planner，执行/编辑阶段走 executor。"""
    return "executor" if state["stage"] in {"execute", "edit"} else "planner"


def _build_checkpointer():
    """按配置构建状态检查点：默认 TTLMemorySaver，配置 redis 时尝试 RedisSaver。"""
    backend = getattr(settings, "AI_CHECKPOINT_BACKEND", "memory").lower()
    if backend == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver
            redis_url = getattr(settings, "AI_REDIS_URL", "") or "redis://localhost:6379"
            return RedisSaver.from_conn_string(redis_url)
        except Exception as error:
            logger.warning("[AI] RedisSaver 不可用（%s），回退 TTLMemorySaver", error)
    return TTLMemorySaver(
        ttl_seconds=settings.AI_THREAD_TTL_SECONDS,
        max_threads=settings.AI_CHECKPOINT_MAX_THREADS,
    )


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


async def has_pending_interrupt(graph, config: dict) -> bool:
    """线程上是否存在待恢复的 interrupt（决定 resume 是否可行）。"""
    try:
        snapshot = await graph.aget_state(config)
        return bool(snapshot.interrupts)
    except Exception as error:
        logger.warning("[AI] failed to read checkpoint state: %s", error)
        return False


def extract_graph_result(
    result: dict,
    stage: str,
    thread_id: str | None,
) -> dict:
    """从 LangGraph 返回值中提取前端可用的结果。

    - interrupt 挂起（等待用户输入）：把挂起载荷（选项/问题/方案）转成响应，
      并附带 thread_id 与 waitingForInput，前端凭 thread_id + resume 恢复执行；
    - 正常结束：返回节点写入的 result，并透传 planner 确认的方案（供评测/前端使用）。

    非流式 run_agent 与流式 run_agent_streaming 共用，保证两条链路协议一致。
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
            "threadId": thread_id,
            "waitingForInput": True,
        }
    normal_result = result.get("result", {"reply": "", "actions": []})
    if isinstance(normal_result, dict) and result.get("plan") is not None:
        normal_result = {**normal_result, "plan": result["plan"]}
    return normal_result

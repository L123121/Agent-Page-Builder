"""LangGraph 组装 — route → planner ⇄ await_user / executor + 状态检查点。

图结构：
  route（确定性路由，定阶段与工具白名单）
    ├─ planner（discover/design/plan/confirm：LLM 决策；需要用户输入时写
    │   state["pending_input"] 并返回，条件边路由到 await_user）
    │     └─ await_user（唯一调用 interrupt 的节点，恢复后应用用户选择，
    │         回到 planner 继续下一轮决策）
    └─ executor（execute/edit：执行 → 验证 → 修复闭环）

把 interrupt 隔离在无副作用的 await_user 节点里，是 LangGraph human-in-the-loop
的推荐模式：节点恢复语义是「从头重执行被中断的节点」，若 interrupt 之前有
LLM 调用（旧实现），每次用户交互恢复都会多付一次重放的模型调用。

checkpointer 用于同一 thread_id 下的状态持久化与 interrupt 恢复；
默认 TTLMemorySaver（进程内 + 线程 TTL/容量淘汰），配置 AI_CHECKPOINT_BACKEND=redis
时用 AsyncRedisSaver（跨进程持久化，初始化失败自动回退内存实现）。
"""

import logging
import time
from datetime import datetime

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.config import settings

from .agent_nodes import await_user_node, executor_node, planner_node
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

    每个线程的最近活跃时间在写入时解析一次 checkpoint 时间戳并缓存进索引，
    扫描时直接查表——不再逐个反序列化全部 checkpoint blob（500 线程 × 多个
    checkpoint 的全量反序列化在每次扫描时是可感知的 CPU 开销）。
    """

    def __init__(self, ttl_seconds: int = 3600, max_threads: int = 500) -> None:
        super().__init__()
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.max_threads = max(1, int(max_threads))
        self._last_sweep = 0.0
        self._thread_active: dict[str, float] = {}

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = config["configurable"]["thread_id"]
        self._sweep(exclude_thread=thread_id)
        result = super().put(config, checkpoint, metadata, new_versions)
        self._thread_active[thread_id] = self._checkpoint_ts(checkpoint)
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        thread_id = config["configurable"]["thread_id"]
        self._sweep(exclude_thread=thread_id)
        result = super().put_writes(config, writes, task_id, task_path)
        self._thread_active.setdefault(thread_id, time.time())
        return result

    @staticmethod
    def _checkpoint_ts(checkpoint) -> float:
        """checkpoint['ts'] 为 ISO 字符串；解析失败时按当前时间兜底。"""
        try:
            return datetime.fromisoformat(checkpoint["ts"]).timestamp()
        except Exception:
            return time.time()

    def _thread_last_active(self, thread_id: str) -> float:
        return self._thread_active.get(thread_id, 0.0)

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
        self._thread_active.pop(thread_id, None)
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


def route_after_planner(state: AgentState) -> str:
    """条件边：planner 需要用户输入时挂起交给 await_user，否则结束本轮执行。"""
    return "await_user" if state.get("pending_input") else END


def _build_checkpointer():
    """按配置构建状态检查点：默认 TTLMemorySaver，配置 redis 时用 AsyncRedisSaver。

    三个实测踩坑点（langgraph-checkpoint-redis 0.5.x + langgraph 1.x，缺一即崩）：
    - from_conn_string 是 @contextmanager，直接返回拿到的是上下文管理器对象
      而非 saver 实例，必须直接实例化 AsyncRedisSaver(...)；
    - 本图经 ainvoke/astream 执行，langgraph 异步路径只调 aput/aget_tuple 等
      异步方法且无同步回退（BaseCheckpointSaver.aput 默认 NotImplementedError），
      sync RedisSaver 未实现这些方法，必须用 AsyncRedisSaver；
    - asetup() 建 RediSearch 索引需要运行中的事件循环，无法在模块导入时执行，
      由 ensure_checkpointer_ready 在每次请求入口补齐（幂等）。
    """
    backend = getattr(settings, "AI_CHECKPOINT_BACKEND", "memory").lower()
    if backend == "redis":
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver

            redis_url = getattr(settings, "AI_REDIS_URL", "") or "redis://localhost:6379"
            # 线程 TTL 透传给 redis（default_ttl 单位为分钟），跨进程重启也能自动过期；
            # 淘汰后的 resume 请求与内存后端同样安全降级为新请求
            ttl_minutes = (
                max(1, settings.AI_THREAD_TTL_SECONDS // 60)
                if settings.AI_THREAD_TTL_SECONDS > 0
                else None
            )
            return AsyncRedisSaver(
                redis_url=redis_url,
                ttl={"default_ttl": ttl_minutes} if ttl_minutes else None,
            )
        except Exception as error:
            logger.warning("[AI] AsyncRedisSaver 不可用（%s），回退 TTLMemorySaver", error)
    return TTLMemorySaver(
        ttl_seconds=settings.AI_THREAD_TTL_SECONDS,
        max_threads=settings.AI_CHECKPOINT_MAX_THREADS,
    )


def _build_agent_graph():
    """构建并编译 LangGraph：route → planner ⇄ await_user / executor。"""
    workflow = StateGraph(AgentState)
    workflow.add_node("route", route_request)
    workflow.add_node("planner", planner_node)
    workflow.add_node("await_user", await_user_node)
    workflow.add_node("executor", executor_node)
    workflow.set_entry_point("route")
    workflow.add_conditional_edges(
        "route",
        select_execution_node,
        {"planner": "planner", "executor": "executor"},
    )
    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {"await_user": "await_user", END: END},
    )
    workflow.add_edge("await_user", "planner")
    workflow.add_edge("executor", END)
    return workflow.compile(checkpointer=_build_checkpointer())


# 模块级单例图（启动时编译一次）
agent_graph = _build_agent_graph()


# 已完成初始化的 checkpointer id（asetup 幂等且只需成功一次；失败不标记，下次请求重试）
_checkpointer_setup_done: set[int] = set()


async def ensure_checkpointer_ready() -> None:
    """redis checkpointer 首次使用前完成初始化（asetup 需要事件循环，导入期无法执行）。

    memory 后端没有 asetup 方法，直接跳过；初始化失败时异常向上抛给调用方走
    统一错误路径，且不标记完成——下次请求自动重试，瞬时断连可自愈。
    """
    checkpointer = agent_graph.checkpointer
    asetup = getattr(checkpointer, "asetup", None)
    if asetup is None or id(checkpointer) in _checkpointer_setup_done:
        return
    await asetup()
    # __aenter__ 的另一半：上报客户端信息（redisvl 索引元数据），老版本没有该方法
    set_client_info = getattr(checkpointer, "aset_client_info", None)
    if set_client_info is not None:
        await set_client_info()
    _checkpointer_setup_done.add(id(checkpointer))


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
    - 正常结束：返回节点写入的 result，统一附带 threadId / waitingForInput=false
      （非流式 /chat 响应此前缺 threadId，前端无法保存会话标识），并透传
      planner 确认的方案（供评测/前端使用）。

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
    if isinstance(normal_result, dict):
        normal_result = {
            **normal_result,
            "threadId": thread_id,
            "waitingForInput": False,
        }
        if result.get("plan") is not None:
            normal_result = {**normal_result, "plan": result["plan"]}
    return normal_result

"""AI 对话路由 — 调用 LangGraph Agent（planner/executor 双 Agent）

两个端点都要求 JWT 鉴权（LLM 调用有真实成本，不能匿名打）。
"""

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.ai import AIChatRequest, AIChatResponse
from app.services.ai import run_agent, run_agent_streaming

router = APIRouter()

# SSE 空闲心跳间隔（秒）：LLM 长调用最坏可静默数分钟（超时重试 + 退避等待），
# nginx 等代理默认 proxy_read_timeout 60s 会掐断无字节的连接
SSE_KEEPALIVE_INTERVAL = getattr(settings, "AI_SSE_KEEPALIVE_INTERVAL", 15.0)


def _sse_data(event: Any) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


_SSE_KEEPALIVE = object()  # 队列内的心跳标记（区别于事件 dict 与结束哨兵）


async def with_sse_keepalive(events: AsyncIterator[Any], interval: float = SSE_KEEPALIVE_INTERVAL) -> AsyncIterator[str]:
    """把事件流转成 SSE data 行，周期插入注释行心跳。

    心跳用 SSE 注释行 ": keepalive"：规范要求客户端忽略注释，前端按块解析
    只认 "data: " 前缀，天然兼容（见 frontend/src/api/ai.ts）。

    实现是「生产者 + 周期心跳任务 → 队列 → 无超时消费」：不对 __anext__ 做
    asyncio.wait_for——等待超时会取消 __anext__，把 CancelledError 注入上游
    图执行、中断整次运行。也不用 wait_for 包 queue.get（Windows 时钟粒度
    15.6ms 下短 deadline 会提前触发，白白发心跳）：心跳由独立任务按固定周期
    写入队列，消费端阻塞式 get 即可。异常经队列透传给消费侧，由调用方转成
    agent_error；客户端断开时两个后台任务随生成器关闭一起取消。
    """
    queue: asyncio.Queue = asyncio.Queue()
    closed = object()

    async def _produce() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except BaseException as error:  # noqa: BLE001 — 经队列透传（含 CancelledError）
            await queue.put(error)
        finally:
            await queue.put(closed)

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(interval)
            await queue.put(_SSE_KEEPALIVE)

    producer = asyncio.create_task(_produce())
    heartbeat = asyncio.create_task(_heartbeat())
    try:
        while True:
            item = await queue.get()
            if item is closed:
                break
            if item is _SSE_KEEPALIVE:
                yield ": keepalive\n\n"
            elif isinstance(item, BaseException):
                raise item
            else:
                yield _sse_data(item)
    finally:
        heartbeat.cancel()
        producer.cancel()
        for task in (heartbeat, producer):
            try:
                await task
            except BaseException:  # noqa: BLE001 — 收尾等待，吞掉取消/异常
                pass


@router.post("/chat", response_model=AIChatResponse)
async def chat(data: AIChatRequest, user: User = Depends(get_current_user)):
    """AI 对话 — LLM 自主决策使用哪个工具

    支持 checkpoint 状态持久化与中断恢复：
    - 首次请求无需 threadId，后端生成并随响应返回；
    - 收到 waitingForInput=true 后，前端凭 threadId + resume 继续上次中断的图执行。
    """
    try:
        result = await run_agent(
            prompt=data.prompt,
            image=data.image,
            history=[m.model_dump() for m in data.history],
            components=data.components,
            canvas_style=data.canvasStyle,
            canvas_width=data.canvasWidth,
            canvas_height=data.canvasHeight,
            selected_component_ids=data.selectedComponentIds,
            viewport=data.viewport,
            project_knowledge=data.projectKnowledge,
            conversation_stage=data.conversationStage,
            thread_id=data.threadId,
            resume=data.resume,
        )
        return AIChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 生成失败: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(data: AIChatRequest, user: User = Depends(get_current_user)):
    """流式 AI 对话 — SSE 推送 Agent 执行进度

    事件类型：
      agent_start    → { stage }
      tool_call      → { step: 1, tool: "generate_page" }
      tool_result    → { step: 1, tool: "generate_page", status: "done", validation: {...} }
      self_correction→ { step: 2, error: "unresolved_component_ref", detail: {...} }
      agent_done     → { result }
        - 正常完成：result.reply / actions / nextStage / validation / trace
        - planner 挂起等待用户输入：result 带 reply/options/question/plan/threadId
          与 waitingForInput=true，前端凭 threadId + resume 恢复图执行
      agent_error    → { error }
    """

    async def event_generator():
        async def produce_events():
            async for event in run_agent_streaming(
                prompt=data.prompt,
                image=data.image,
                history=[m.model_dump() for m in data.history],
                components=data.components,
                canvas_style=data.canvasStyle,
                canvas_width=data.canvasWidth,
                canvas_height=data.canvasHeight,
                selected_component_ids=data.selectedComponentIds,
                viewport=data.viewport,
                project_knowledge=data.projectKnowledge,
                conversation_stage=data.conversationStage,
                thread_id=data.threadId,
                resume=data.resume,
            ):
                yield event

        try:
            async for chunk in with_sse_keepalive(produce_events()):
                yield chunk
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield _sse_data({"type": "agent_error", "error": str(e)})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

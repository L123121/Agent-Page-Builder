"""AI 对话路由 — 调用 LangGraph Agent（planner/executor 双 Agent）

两个端点都要求 JWT 鉴权（LLM 调用有真实成本，不能匿名打）。
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.ai import AIChatRequest, AIChatResponse
from app.services.ai import run_agent, run_agent_streaming

router = APIRouter()


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
      agent_start    → { stage: "discover" }
      tool_call      → { step: 1, tool: "propose_options", args: {...} }
      tool_result    → { step: 1, tool: "propose_options", status: "done", validation: {...} }
      agent_done     → { reply, actions, ... }
      agent_error    → { error: "..." }
    """

    async def event_generator():
        try:
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
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'agent_error', 'error': str(e)}, ensure_ascii=False)}\n\n"
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

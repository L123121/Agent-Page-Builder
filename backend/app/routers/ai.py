"""AI 对话路由 — 调用 LangGraph Agent（单节点 + 5 工具）"""

from fastapi import APIRouter, HTTPException

from app.schemas.ai import AIChatRequest, AIChatResponse
from app.services.ai import run_agent

router = APIRouter()


@router.post("/chat", response_model=AIChatResponse)
async def chat(data: AIChatRequest):
    """AI 对话 — LLM 自主决策使用哪个工具

    支持 checkpoint 状态持久化与中断恢复：
    - 首次请求无需 threadId，后端生成并随响应返回；
    - 收到 waitingForInput=true 后，前端凭 threadId + resume 继续上次中断的图执行。
    """
    try:
        result = await run_agent(
            prompt=data.prompt,
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

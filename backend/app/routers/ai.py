"""AI 对话路由 — 调用 LangGraph Agent（单节点 + 5 工具）"""

from fastapi import APIRouter, HTTPException

from app.schemas.ai import AIChatRequest, AIChatResponse
from app.services.ai_service import run_agent

router = APIRouter()


@router.post("/chat", response_model=AIChatResponse)
async def chat(data: AIChatRequest):
    """AI 对话 — LLM 自主决策使用哪个工具"""
    try:
        result = await run_agent(
            prompt=data.prompt,
            history=[m.model_dump() for m in data.history],
            components=data.components,
            canvas_style=data.canvasStyle,
            canvas_width=data.canvasWidth,
            canvas_height=data.canvasHeight,
        )
        return AIChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 生成失败: {str(e)}")
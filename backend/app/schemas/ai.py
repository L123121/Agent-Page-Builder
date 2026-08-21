"""AI 对话相关的 Pydantic schemas"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AIAction(BaseModel):
    type: str  # "generate" | "add" | "modify" | "delete" | "move"
    components: list | None = None
    canvasStyle: dict | None = None
    component: dict | None = None
    id: str | None = None
    style: dict | None = None
    propValue: Any = None
    top: int | None = None
    left: int | None = None


class AIOption(BaseModel):
    id: str
    title: str
    description: str
    tag: str | None = None


class AIPlan(BaseModel):
    summary: str
    details: list[str]


class AIChatRequest(BaseModel):
    prompt: str
    history: list[ChatMessage] = Field(default_factory=list)
    components: list = Field(default_factory=list)
    canvasStyle: dict | None = None
    canvasWidth: int | None = None
    canvasHeight: int | None = None
    selectedComponentIds: list[str] = Field(default_factory=list)
    viewport: dict | None = None
    projectKnowledge: str = ""
    conversationStage: Literal["discover", "design", "plan", "confirm", "execute", "edit"] | None = None
    # 会话标识与中断恢复：同一 threadId 下的执行状态由 checkpoint 持久化；
    # 前端收到 waitingForInput=true 后，凭 threadId + resume 继续上次中断的图执行
    threadId: str | None = None
    resume: Any | None = None
    # 参考图：data URL (image/...)，全模态模型直接"看到"图片 + 文字，无需前置解析
    image: str | None = None


class AIChatResponse(BaseModel):
    reply: str
    actions: list[AIAction] = Field(default_factory=list)
    options: list[AIOption] | None = None
    question: str | None = None
    suggestions: list[str] | None = None
    plan: AIPlan | None = None
    nextStage: Literal["discover", "design", "plan", "confirm", "execute", "edit"] | None = None
    validation: dict | None = None
    trace: list[dict] = Field(default_factory=list)
    # 中断恢复信息：waitingForInput=true 表示图已挂起等待用户输入
    threadId: str | None = None
    waitingForInput: bool = False

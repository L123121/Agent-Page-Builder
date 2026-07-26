"""AI 对话相关的 Pydantic schemas"""

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
    propValue: dict | None = None
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
    history: list[ChatMessage] = []
    components: list = []
    canvasStyle: dict | None = None
    canvasWidth: int | None = None
    canvasHeight: int | None = None


class AIChatResponse(BaseModel):
    reply: str
    actions: list[AIAction] = []
    options: list[AIOption] | None = None
    question: str | None = None
    suggestions: list[str] | None = None
    plan: AIPlan | None = None
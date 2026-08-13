"""AI Agent 类型定义 — Pydantic 模型替代 Dict[str, Any]"""

from typing import Any, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


# ==================== 组件相关 ====================

class ComponentStyle(BaseModel):
    """组件样式（LLM 返回的简化格式）"""
    width: int = 200
    height: int = 28
    top: int = 0
    left: int = 0
    rotate: int = 0
    opacity: float = 1
    fontSize: int = 14
    fontWeight: int = 400
    lineHeight: str = ""
    letterSpacing: int = 0
    textAlign: str = "center"
    color: str = "#333"
    backgroundColor: str = ""
    borderColor: str = ""
    borderWidth: int = 0
    borderStyle: str = "solid"
    borderRadius: str = ""
    padding: int = 4


class ComponentData(BaseModel):
    """规范化后的组件数据"""
    id: str
    component: str
    label: str = "组件"
    icon: str = ""
    propValue: Any = ""
    style: ComponentStyle
    parentId: Optional[str] = None
    slot: str = "default"
    zIndex: int = 1
    animations: list = []
    events: dict = {}
    groupStyle: dict = {}
    isLock: bool = False
    collapseName: str = "style"
    linkage: dict = {}


# ==================== 工具参数 ====================

class AskQuestionArgs(BaseModel):
    question: str
    suggestions: List[str] = Field(..., min_length=1, max_length=3)


class ProposeOption(BaseModel):
    id: str
    title: str
    description: str
    tag: str = ""


class ProposeOptionsArgs(BaseModel):
    reply: str
    options: List[ProposeOption] = Field(..., min_length=2, max_length=3)


class ConfirmPlanArgs(BaseModel):
    summary: str
    details: List[str] = Field(..., min_length=3, max_length=5)


class GeneratePageArgs(BaseModel):
    reply: str
    canvasStyle: dict
    components: list


class EditOperation(BaseModel):
    type: Literal["add", "modify", "delete", "move"]
    id: str = ""
    component: dict = {}
    style: dict = {}
    propValue: Any = None
    top: int = 0
    left: int = 0


class EditPageArgs(BaseModel):
    reply: str
    operations: List[EditOperation]


class FinishArgs(BaseModel):
    reply: str
    summary: str


AgentStage = Literal["discover", "design", "plan", "confirm", "execute", "edit"]


# ==================== Agent 状态 ====================

class AgentState(TypedDict):
    messages: List[dict]
    prompt: str
    components: List[dict]
    canvas_style: dict
    canvas_width: int
    canvas_height: int
    selected_component_ids: List[str]
    viewport: dict
    project_knowledge: str
    requested_stage: Optional[str]
    stage: AgentStage
    allowed_tools: List[str]
    result: dict
    # 需求分析 Agent（planner）确认后的设计方案，供执行 Agent（executor）注入上下文
    plan: Optional[dict]


# ==================== 动作输出 ====================

class AIAction(BaseModel):
    type: str  # "generate" | "add" | "modify" | "delete" | "move"
    components: Optional[List[ComponentData]] = None
    canvasStyle: Optional[dict] = None
    component: Optional[ComponentData] = None
    id: Optional[str] = None
    style: Optional[dict] = None
    propValue: Any = None
    top: Optional[int] = None
    left: Optional[int] = None

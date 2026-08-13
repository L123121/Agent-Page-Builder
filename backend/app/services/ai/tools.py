"""6 个工具定义 — 基于 @tool + Pydantic 自动生成 OpenAI function schema

相比手写 JSON Schema，参数结构、必填项、描述全部由 Pydantic 模型维护，
新增工具只需加一个函数 + 一个参数模型，不再需要维护两处定义。
"""

from typing import List

from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from .schemas import (
    AskQuestionArgs,
    ConfirmPlanArgs,
    EditPageArgs,
    FinishArgs,
    GeneratePageArgs,
    ProposeOptionsArgs,
)


@tool(args_schema=AskQuestionArgs)
def ask_question(question: str, suggestions: List[str]) -> dict:
    """向用户提出一个开放式问题（极少使用，优先用 propose_options）。附带 2~3 个快捷回复建议供用户点选。"""
    return {"question": question, "suggestions": suggestions}


@tool(args_schema=ProposeOptionsArgs)
def propose_options(reply: str, options: List[dict]) -> dict:
    """给出 2~3 种方案供用户点击选择（布局、风格等有明确选项的场景）"""
    return {"reply": reply, "options": options}


@tool(args_schema=ConfirmPlanArgs)
def confirm_plan(summary: str, details: List[str]) -> dict:
    """生成前展示设计方案摘要，让用户确认或提出修改"""
    return {"summary": summary, "details": details}


@tool(args_schema=GeneratePageArgs)
def generate_page(reply: str, canvasStyle: dict, components: list) -> dict:
    """生成全新页面（用户确认方案后执行）"""
    return {"reply": reply, "canvasStyle": canvasStyle, "components": components}


@tool(args_schema=EditPageArgs)
def edit_page(reply: str, operations: List[dict]) -> dict:
    """增量修改现有页面"""
    return {"reply": reply, "operations": operations}


@tool(args_schema=FinishArgs)
def finish(reply: str, summary: str) -> dict:
    """确认当前画布已经满足用户需求，无需继续修改时结束任务。仅在不需要任何动作或验证已经通过时使用。"""
    return {"reply": reply, "summary": summary}


_TOOL_OBJECTS = {
    "ask_question": ask_question,
    "propose_options": propose_options,
    "confirm_plan": confirm_plan,
    "generate_page": generate_page,
    "edit_page": edit_page,
    "finish": finish,
}

# OpenAI function-calling 格式（LLM 调用与 JSON 模式共用）
TOOL_DEFINITIONS = {
    name: convert_to_openai_tool(tool_obj)
    for name, tool_obj in _TOOL_OBJECTS.items()
}

ALL_TOOLS = list(TOOL_DEFINITIONS.values())

TOOLS_BY_STAGE = {
    "discover": ["propose_options"],
    "design": ["propose_options"],
    "plan": ["confirm_plan"],
    "confirm": ["confirm_plan", "generate_page", "edit_page"],
    "execute": ["generate_page"],
    "edit": ["edit_page", "finish"],
}


def tools_for_stage(stage: str) -> list[dict]:
    """只向模型暴露当前阶段允许的工具，避免跨阶段乱跳。"""
    names = TOOLS_BY_STAGE.get(stage, TOOLS_BY_STAGE["plan"])
    return [TOOL_DEFINITIONS[name] for name in names]

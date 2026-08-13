"""Agent 主逻辑 — 显式阶段路由 + 单节点工具执行。"""

import asyncio
import json
import logging
from copy import deepcopy
from typing import Any, Dict, List

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from app.config import settings

from .canvas_runtime import apply_actions_to_canvas, diff_canvas
from .component_utils import auto_layout_components, build_canvas_context, normalize_component
from .fallback import run_fallback_agent
from .llm import get_llm_client
from .prompts import build_system_prompt
from .schemas import AgentStage, AgentState
from .tools import TOOLS_BY_STAGE, tools_for_stage
from .validator import issue_key, repair_canvas, validate_canvas

logger = logging.getLogger(__name__)


# ==================== 配置（从 settings 读取，带默认值） ====================

MAX_RETRIES = getattr(settings, "AI_MAX_RETRIES", 3)
RETRY_BACKOFF_BASE = getattr(settings, "AI_RETRY_BACKOFF_BASE", 2)
MAX_AGENT_STEPS = getattr(settings, "AI_MAX_AGENT_STEPS", 6)
# 单次图执行允许的最大 interrupt 轮数：完整流程需要
# discover→design→plan→confirm 多次用户确认，3 次不够，取 10 预留余量
MAX_INTERRUPT_ROUNDS = 10
DEFAULT_CANVAS_WIDTH = getattr(settings, "AI_DEFAULT_CANVAS_WIDTH", 375)
DEFAULT_CANVAS_HEIGHT = getattr(settings, "AI_DEFAULT_CANVAS_HEIGHT", 667)

DIRECT_GENERATE_PHRASES = ("直接生成", "立即生成", "不用确认", "确认，请生成", "确认生成", "开始生成")
PLAN_REVISION_PHRASES = ("修改方案", "调整方案", "换一个方案", "我想修改", "方案改成")
NEW_PAGE_PHRASES = ("新页面", "新海报", "全新", "重新生成", "重做", "替换画布", "重新设计")
VAGUE_REQUESTS = {"做个页面", "做一个页面", "做个海报", "做一个海报", "帮我设计", "生成页面", "生成海报"}
EDIT_REQUEST_PHRASES = ("修改", "改成", "调整", "删除", "移动", "放大", "缩小", "加粗", "颜色", "换图", "替换文字")

LOOP_INSTRUCTION = """你正在执行闭环画布任务。每轮只调用一个工具。
工具结果会返回真实执行状态和确定性验证报告。如果存在 error，必须根据报告继续调用 edit_page 修复；不要重复已经成功的操作。
warning 可以按用户目标和设计意图决定是否修复。最多执行有限轮次，禁止重新询问已经明确的信息。"""


def resolve_stage(
    prompt: str,
    components: List[dict],
    requested_stage: str | None = None,
) -> AgentStage:
    """用确定性规则先决定阶段，避免把流程控制完全交给模型。"""
    text = "".join(prompt.strip().lower().split())

    if any(phrase in text for phrase in DIRECT_GENERATE_PHRASES):
        return "execute"

    if requested_stage == "confirm":
        if any(phrase in text for phrase in PLAN_REVISION_PHRASES):
            return "plan"
        return "confirm"

    if components:
        if any(phrase in text for phrase in NEW_PAGE_PHRASES):
            return "discover"
        if requested_stage == "discover" and not any(phrase in text for phrase in EDIT_REQUEST_PHRASES):
            return "discover"
        return "edit"

    if requested_stage in {"discover", "design", "plan", "execute"}:
        return requested_stage
    return "discover"


def next_stage_for_tool(tool_name: str, current_stage: AgentStage) -> AgentStage:
    if tool_name == "propose_options":
        return {"discover": "design", "design": "plan"}.get(current_stage, current_stage)
    if tool_name == "ask_question":
        return current_stage
    return {
        "confirm_plan": "confirm",
        "generate_page": "edit",
        "edit_page": "edit",
        "finish": "edit",
    }.get(tool_name, current_stage)


# ==================== LLM 调用 ====================

def _build_canvas_context_from_state(
    state: AgentState,
    components: list[dict] | None = None,
    canvas_style: dict | None = None,
) -> str:
    return build_canvas_context(
        components if components is not None else state["components"],
        state["canvas_width"],
        state["canvas_height"],
        canvas_style if canvas_style is not None else state["canvas_style"],
        state["selected_component_ids"],
        state["viewport"],
        state["project_knowledge"],
    )


async def _invoke_llm(messages: list, tools: list[dict]):
    llm = get_llm_client()
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return await llm.ainvoke(messages, tools=tools, tool_choice="required")
        except Exception as error:
            last_error = error
            logger.warning("[AI] LLM call failed (attempt %s/%s): %s", attempt + 1, MAX_RETRIES, error)
            if _is_non_retryable_llm_error(error):
                break
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_error}") from last_error


def _is_non_retryable_llm_error(error: Exception) -> bool:
    message = str(error).lower()
    return "401" in message or "invalid_api_key" in message or "incorrect api key" in message


async def planner_node(state: AgentState) -> Dict[str, Any]:
    """需求分析 Agent：负责 discover/design/plan/confirm 阶段的 LLM 决策与用户交互。

    当模型产出需要用户输入的决策（ask_question / propose_options / confirm_plan）时，
    通过 interrupt 挂起图执行；前端 resume 后把用户选择作为消息继续。
    确认后的设计方案写入 state["plan"]，供 executor 执行阶段注入上下文。
    """
    loop_state = dict(state)
    confirmed_plan = loop_state.get("plan")
    for _ in range(MAX_INTERRUPT_ROUNDS):
        canvas_ctx = _build_canvas_context_from_state(loop_state)
        system_content = build_system_prompt(loop_state["stage"], canvas_ctx)
        messages = [{"role": "system", "content": system_content}]
        messages.extend(loop_state["messages"])
        tools = tools_for_stage(loop_state["stage"])

        try:
            response = await _invoke_llm(messages, tools)
        except Exception as error:
            logger.warning("[AI] switching to local fallback: %s", error)
            return {"result": run_fallback_agent(loop_state, str(error)), "plan": confirmed_plan}

        result = process_tool_response(response, loop_state)

        # 记录确认后的设计方案（confirm_plan 产出）
        if result.get("plan"):
            confirmed_plan = result["plan"]

        # 自省修正：工具被拒或未调用工具（直接输出文本）→ 注入反馈让模型重新决策
        if (result.get("rejectedTools") or result.get("noToolCall")) and not (
            result.get("actions") or result.get("options")
            or result.get("question") or result.get("plan") or result.get("finished")
        ):
            allowed = ", ".join(loop_state["allowed_tools"])
            if result.get("noToolCall"):
                feedback = (
                    f"[系统反馈] 你没有调用工具而是直接输出文本。当前阶段"
                    f"（{loop_state['stage']}）必须通过工具决策。"
                    f"当前允许的工具：{allowed}。请重新决策并调用工具。"
                )
            else:
                rejected = result["rejectedTools"]
                feedback = (
                    f"[系统反馈] 你调用的工具 {rejected} 不在当前阶段"
                    f"（{loop_state['stage']}）允许的工具中。当前允许的工具：{allowed}。请重新决策。"
                )
            loop_state["messages"] = [
                *loop_state["messages"],
                {"role": "assistant", "content": result.get("reply") or ""},
                {"role": "user", "content": feedback},
            ]
            continue

        # 需要用户输入（选项 / 问题 / 方案确认）→ 挂起图，等待前端恢复
        if result.get("options") or result.get("question") or result.get("plan"):
            user_input = interrupt({
                "type": "user_input",
                "stage": loop_state["stage"],
                "nextStage": result.get("nextStage", loop_state["stage"]),
                "payload": result,
            })
            # 恢复后：把用户选择作为消息追加，继续下一轮 LLM 决策
            assistant_reply = result.get("reply") or ""
            loop_state["messages"] = [
                *loop_state["messages"],
                {"role": "assistant", "content": assistant_reply},
                {"role": "user", "content": str(user_input)},
            ]
            next_stage = result.get("nextStage") or loop_state["stage"]
            loop_state["stage"] = next_stage
            loop_state["allowed_tools"] = TOOLS_BY_STAGE[next_stage]
            continue

        # 产出可执行动作（generate / edit / finish）→ 交给前端执行
        return {"result": result, "plan": confirmed_plan}

    return {"result": {"reply": "交互轮次过多，请重新描述需求", "actions": []}, "plan": confirmed_plan}


# ==================== 工具响应处理 ====================

def process_tool_response(response, state: AgentState) -> dict:
    """只执行第一个合法工具调用，杜绝跨阶段动作被合并。

    返回结构含 rejectedTools：记录被阶段白名单拒绝的工具名，
    供上层把失败原因注入下一轮 prompt 自省修正。
    noToolCall：模型未调用任何工具（直接输出文本），同样需要自省修正。
    """
    result: dict = {"reply": "", "actions": [], "rejectedTools": []}

    if not getattr(response, "tool_calls", None):
        return {
            "reply": response.content or "抱歉，我没有理解你的需求",
            "actions": [],
            "rejectedTools": [],
            "noToolCall": True,
        }

    for tc in response.tool_calls:
        args = tc.get("args", {}) if isinstance(tc, dict) else tc.args
        name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
        if name not in state["allowed_tools"]:
            logger.warning("[AI] ignored tool outside stage: stage=%s tool=%s", state["stage"], name)
            result["rejectedTools"].append(name)
            continue
        handler = _TOOL_HANDLERS.get(name)
        if handler:
            handler(args, state, result, False)
            result["nextStage"] = next_stage_for_tool(name, state["stage"])
            return result

    return {
        "reply": "当前响应与执行阶段不匹配，请重新描述需求",
        "actions": [],
        "nextStage": state["stage"],
        "rejectedTools": result["rejectedTools"],
    }


def _first_allowed_tool_call(response, allowed_tools: list[str]):
    for tool_call in getattr(response, "tool_calls", []) or []:
        name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")
        if name in allowed_tools:
            return tool_call
    return None


def _tool_call_id(tool_call, step: int) -> str:
    if isinstance(tool_call, dict):
        return tool_call.get("id") or f"agent-step-{step}"
    return getattr(tool_call, "id", None) or f"agent-step-{step}"


def _tool_call_name(tool_call) -> str:
    if isinstance(tool_call, dict):
        return tool_call.get("name", "")
    return getattr(tool_call, "name", "")


def _validation_subset(report: dict, ignored_keys: set[tuple]) -> dict:
    issues = [issue for issue in report.get("issues", []) if issue_key(issue) not in ignored_keys]
    error_count = sum(issue.get("severity") == "error" for issue in issues)
    warning_count = sum(issue.get("severity") == "warning" for issue in issues)
    return {
        "valid": error_count == 0,
        "errorCount": error_count,
        "warningCount": warning_count,
        "issues": issues,
        "summary": f"{error_count} 个错误，{warning_count} 个警告",
    }


def _format_plan_context(plan: dict | None) -> str:
    """把 planner 确认的方案格式化为 executor 可注入的系统提示片段。"""
    if not plan:
        return ""
    summary = str(plan.get("summary") or "")
    details = plan.get("details") or []
    detail_lines = "\n".join(f"- {line}" for line in details[:5])
    return (
        "\n\n## 已确认的设计方案\n"
        f"方案概述：{summary}\n"
        f"{detail_lines}"
    )


async def executor_node(state: AgentState) -> Dict[str, Any]:
    """画布执行 Agent：执行工具 → 读取结果 → 验证 → 修复，直到完成或达到上限。

    从 planner 确认的方案（state["plan"]）注入执行上下文，保证生成结果
    与已确认的设计方向一致。
    """
    original_components = deepcopy(state["components"])
    original_canvas_style = deepcopy(state["canvas_style"])
    working_components = deepcopy(original_components)
    working_canvas_style = deepcopy(original_canvas_style)
    baseline_report = validate_canvas(
        original_components,
        state["canvas_width"],
        state["canvas_height"],
        original_canvas_style,
    )
    ignored_issue_keys = (
        {issue_key(issue) for issue in baseline_report["issues"]}
        if state["stage"] == "edit"
        else set()
    )
    loop_messages: list = []
    trace: list[dict] = []
    last_reply = ""
    final_validation = _validation_subset(baseline_report, ignored_issue_keys)
    plan_context = _format_plan_context(state.get("plan"))

    for step in range(1, MAX_AGENT_STEPS + 1):
        tool_stage: AgentStage = "execute" if state["stage"] == "execute" and step == 1 else "edit"
        allowed_tools = TOOLS_BY_STAGE[tool_stage]
        current_width = int(working_canvas_style.get("width") or state["canvas_width"])
        current_height = int(working_canvas_style.get("height") or state["canvas_height"])
        loop_state: AgentState = {
            **state,
            "components": working_components,
            "canvas_style": working_canvas_style,
            "canvas_width": current_width,
            "canvas_height": current_height,
            "stage": tool_stage,
            "allowed_tools": allowed_tools,
        }
        canvas_context = _build_canvas_context_from_state(loop_state, working_components, working_canvas_style)
        system_content = (
            f"{build_system_prompt(tool_stage, canvas_context)}"
            f"{plan_context}"
            f"\n\n## 闭环执行协议\n{LOOP_INSTRUCTION}"
        )
        messages = [{"role": "system", "content": system_content}, *state["messages"], *loop_messages]

        try:
            response = await _invoke_llm(messages, tools_for_stage(tool_stage))
        except Exception as error:
            logger.warning("[AI] tool loop switching to local fallback: %s", error)
            return {"result": run_fallback_agent(state, str(error))}

        tool_call = _first_allowed_tool_call(response, allowed_tools)
        step_result = process_tool_response(response, loop_state)
        last_reply = step_result.get("reply") or last_reply
        step_actions = step_result.get("actions", [])
        rejected_tools = step_result.get("rejectedTools") or []
        if not tool_call:
            # 自省修正：工具不在阶段白名单 → 把被拒工具与允许工具注入下一轮，让模型重新决策
            if rejected_tools:
                feedback = {
                    "error": "tool_not_allowed",
                    "rejectedTools": rejected_tools,
                    "allowedTools": allowed_tools,
                    "instruction": "你调用的工具不在当前阶段白名单中，请只调用 allowedTools 列出的工具重新决策。",
                }
                loop_messages.extend([
                    response,
                    ToolMessage(
                        content=json.dumps(feedback, ensure_ascii=False),
                        tool_call_id=_tool_call_id(None, step),
                    ),
                ])
                continue
            return {
                "result": {
                    "reply": step_result.get("reply") or "Agent 未生成可执行动作",
                    "actions": [],
                    "nextStage": state["stage"],
                    "validation": final_validation,
                    "trace": trace,
                }
            }

        tool_name = _tool_call_name(tool_call)
        if step_result.get("finished"):
            trace.append({
                "step": step,
                "tool": tool_name,
                "execution": [],
                "autoFixes": [],
                "validation": final_validation,
            })
            if final_validation["valid"]:
                return {
                    "result": {
                        "reply": last_reply or "当前画布已满足需求",
                        "actions": diff_canvas(
                            original_components,
                            working_components,
                            original_canvas_style,
                            working_canvas_style,
                            replace_all=state["stage"] == "execute",
                        ),
                        "nextStage": "edit",
                        "validation": final_validation,
                        "trace": trace,
                    }
                }
            loop_messages.extend([
                response,
                ToolMessage(
                    content=json.dumps({
                        "validation": final_validation,
                        "instruction": "仍有 error，不能结束；请调用 edit_page 修复。",
                    }, ensure_ascii=False),
                    tool_call_id=_tool_call_id(tool_call, step),
                ),
            ])
            continue

        if not step_actions:
            return {
                "result": {
                    "reply": step_result.get("reply") or "Agent 未生成可执行动作",
                    "actions": [],
                    "nextStage": state["stage"],
                    "validation": final_validation,
                    "trace": trace,
                }
            }

        working_components, working_canvas_style, execution_events = apply_actions_to_canvas(
            working_components,
            working_canvas_style,
            step_actions,
        )
        current_width = int(working_canvas_style.get("width") or state["canvas_width"])
        current_height = int(working_canvas_style.get("height") or state["canvas_height"])
        full_report = validate_canvas(
            working_components,
            current_width,
            current_height,
            working_canvas_style,
        )
        active_report = _validation_subset(full_report, ignored_issue_keys)
        working_components, auto_fixes = repair_canvas(
            working_components,
            current_width,
            current_height,
            working_canvas_style,
            active_report["issues"],
            allow_reflow=state["stage"] == "execute",
        )
        if auto_fixes:
            full_report = validate_canvas(
                working_components,
                current_width,
                current_height,
                working_canvas_style,
            )
            active_report = _validation_subset(full_report, ignored_issue_keys)
        final_validation = active_report
        trace.append({
            "step": step,
            "tool": _tool_call_name(tool_call),
            "execution": execution_events,
            "autoFixes": auto_fixes,
            "validation": active_report,
        })

        if active_report["valid"]:
            final_actions = diff_canvas(
                original_components,
                working_components,
                original_canvas_style,
                working_canvas_style,
                replace_all=state["stage"] == "execute",
            )
            if final_actions:
                return {
                    "result": {
                        "reply": last_reply or "已完成并通过画布验证",
                        "actions": final_actions,
                        "nextStage": "edit",
                        "validation": active_report,
                        "trace": trace,
                    }
                }

        tool_result = {
            "execution": execution_events,
            "autoFixes": auto_fixes,
            "validation": active_report,
            "instruction": (
                "动作没有产生有效画布差异，请检查组件 ID、锁定状态和操作参数。"
                if active_report["valid"]
                else "根据 error 修复画布；不要重复已成功的动作。"
            ),
        }
        loop_messages.extend([
            response,
            ToolMessage(
                content=json.dumps(tool_result, ensure_ascii=False),
                tool_call_id=_tool_call_id(tool_call, step),
            ),
        ])

    return {
        "result": {
            "reply": f"{last_reply or '页面处理未完成'}；达到最大修复轮次，未应用存在错误的结果",
            "actions": [],
            "nextStage": state["stage"],
            "validation": final_validation,
            "trace": trace,
        }
    }


def _handle_ask_question(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    result["question"] = args.get("question", "")
    if not seen_reply:
        result["reply"] = args.get("question", "")
    result["suggestions"] = args.get("suggestions", [])


def _handle_propose_options(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    if not seen_reply:
        result["reply"] = args.get("reply", "")
    result["options"] = [
        {"id": opt.get("id", _gen_id()), "title": opt.get("title", "方案"),
         "description": opt.get("description", ""), "tag": opt.get("tag", "")}
        for opt in args.get("options", [])
    ]


def _handle_confirm_plan(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    if not seen_reply:
        result["reply"] = args.get("summary", "")
    result["plan"] = {"summary": args.get("summary", ""), "details": args.get("details", [])}


def _handle_generate_page(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    cs = args.get("canvasStyle", {})
    cw = cs.get("width", state["canvas_width"])
    ch = cs.get("height", state["canvas_height"])
    comps = _normalize_components(args.get("components", []))
    comps = auto_layout_components(comps, cw, ch)
    if not seen_reply:
        result["reply"] = args.get("reply", "页面已生成")
    result["actions"].append({
        "type": "generate",
        "components": comps,
        "canvasStyle": {
            "width": cw, "height": ch, "scale": 100,
            "color": cs.get("color", "#000"), "opacity": cs.get("opacity", 100),
            "backgroundColor": cs.get("backgroundColor", "#ffffff"),
            "fontSize": cs.get("fontSize", 14),
        },
    })


def _handle_edit_page(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    if not seen_reply:
        result["reply"] = args.get("reply", "已修改")
    existing_ids = {c["id"] for c in state.get("components", [])}
    max_z = max((c.get("zIndex", 1) for c in state.get("components", [])), default=0)
    add_index = 0
    for op in args.get("operations", []):
        op_type = op.get("type")
        if op_type == "add" and op.get("component"):
            component = normalize_component(op["component"], max_z + add_index).model_dump()
            if component["id"] in existing_ids:
                component["id"] = _gen_id(8)
            existing_ids.add(component["id"])
            result["actions"].append({
                "type": "add",
                "component": component,
            })
            add_index += 1
        elif op_type == "modify" and op.get("id"):
            component_id = _resolve_component_id(op["id"], state["components"])
            if component_id:
                action: dict = {"type": "modify", "id": component_id}
                if isinstance(op.get("style"), dict) and op["style"]:
                    action["style"] = op["style"]
                if "propValue" in op:
                    action["propValue"] = op.get("propValue")
                if len(action) > 2:
                    result["actions"].append(action)
        elif op_type == "delete" and op.get("id"):
            component_id = _resolve_component_id(op["id"], state["components"])
            if component_id:
                result["actions"].append({"type": "delete", "id": component_id})
        elif op_type == "move" and op.get("id"):
            component_id = _resolve_component_id(op["id"], state["components"])
            if component_id:
                action = {"type": "move", "id": component_id}
                if "top" in op:
                    action["top"] = op["top"]
                if "left" in op:
                    action["left"] = op["left"]
                if len(action) > 2:
                    result["actions"].append(action)


def _handle_finish(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    result["reply"] = args.get("reply") or args.get("summary") or "当前画布已满足需求"
    result["finished"] = True


def _normalize_components(raw_components: list) -> list[dict]:
    """规范化生成结果，并保证组件 ID 唯一。"""
    normalized: list[dict] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_components):
        component = normalize_component(raw, index).model_dump()
        if not component["id"] or component["id"] in used_ids:
            component["id"] = _gen_id(8)
        used_ids.add(component["id"])
        normalized.append(component)
    return normalized


def _resolve_component_id(candidate: str, components: list[dict]) -> str | None:
    """将模型可能生成的语义 ID 解析为画布中的真实 ID。"""
    exact_ids = {c.get("id") for c in components}
    if candidate in exact_ids:
        return candidate
    normalized = str(candidate).lower().strip()
    for component in components:
        label = str(component.get("label", "")).lower()
        if label and (normalized == label or normalized in label or label in normalized):
            return component.get("id")
        prop_value = component.get("propValue")
        if isinstance(prop_value, str):
            content = prop_value.lower()
            if normalized and (normalized in content or content in normalized):
                return component.get("id")
    semantic_types = {
        "标题": lambda c: c.get("component") == "VText" and c.get("style", {}).get("fontSize", 0) >= 20,
        "title": lambda c: c.get("component") == "VText" and c.get("style", {}).get("fontSize", 0) >= 20,
        "背景": lambda c: c.get("component") == "RectShape" and c.get("zIndex", 0) <= 5,
        "background": lambda c: c.get("component") == "RectShape" and c.get("zIndex", 0) <= 5,
        "按钮": lambda c: c.get("component") == "VButton",
        "button": lambda c: c.get("component") == "VButton",
    }
    for keyword, predicate in semantic_types.items():
        if keyword in normalized:
            match = next((c for c in components if predicate(c)), None)
            if match:
                return match.get("id")
    return None


# 工具名 → 处理函数映射
_TOOL_HANDLERS = {
    "ask_question": _handle_ask_question,
    "propose_options": _handle_propose_options,
    "confirm_plan": _handle_confirm_plan,
    "generate_page": _handle_generate_page,
    "edit_page": _handle_edit_page,
    "finish": _handle_finish,
}


def _gen_id(length: int = 6) -> str:
    from app.utils.id_generator import generate_id
    return generate_id(length)


def _comps_to_dicts(comps: list) -> List[dict]:
    """ComponentData 列表转为 dict 列表（auto_layout_components 需要可变 dict）"""
    result = []
    for c in comps:
        d = c.model_dump()
        d["style"] = dict(d["style"])  # 确保 style 是可变 dict
        result.append(d)
    return result


def route_request(state: AgentState) -> dict:
    """LangGraph 路由节点：在模型调用前确定阶段和工具白名单。"""
    stage = resolve_stage(state["prompt"], state["components"], state.get("requested_stage"))
    return {"stage": stage, "allowed_tools": TOOLS_BY_STAGE[stage]}


def select_execution_node(state: AgentState) -> str:
    """条件边：需求分析阶段走 planner，执行/编辑阶段走 executor。"""
    return "executor" if state["stage"] in {"execute", "edit"} else "planner"


# ==================== 构建 LangGraph ====================

def _build_checkpointer():
    """按配置构建状态检查点：默认 MemorySaver，配置 redis 时尝试 RedisSaver。"""
    backend = getattr(settings, "AI_CHECKPOINT_BACKEND", "memory").lower()
    if backend == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver
            redis_url = getattr(settings, "AI_REDIS_URL", "") or "redis://localhost:6379"
            return RedisSaver.from_conn_string(redis_url)
        except Exception as error:
            logger.warning("[AI] RedisSaver 不可用（%s），回退 MemorySaver", error)
    return MemorySaver()


def _build_agent_graph():
    """构建并编译 LangGraph：route → planner（需求分析）/ executor（画布执行）。

    多 Agent 分工：
    - planner：负责 discover/design/plan/confirm 阶段，LLM 决策 + 用户交互，
      确认方案后把 plan 写入 state，供 executor 执行时注入上下文。
    - executor：负责 execute/edit 阶段，执行工具 → 验证 → 修复闭环。
    checkpointer 用于同一 thread_id 下的状态持久化与 interrupt 恢复。
    """
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


# ==================== 公开接口 ====================

async def run_agent(
    prompt: str,
    history: List[Dict[str, str]] | None = None,
    components: List[Dict[str, Any]] | None = None,
    canvas_style: Dict[str, Any] | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
    selected_component_ids: List[str] | None = None,
    viewport: Dict[str, Any] | None = None,
    project_knowledge: str = "",
    conversation_stage: str | None = None,
    thread_id: str | None = None,
    resume: Any | None = None,
) -> Dict[str, Any]:
    """运行 AI Agent：先路由阶段，再在阶段内执行一个工具。

    thread_id: 会话标识。同一 thread_id 下的执行状态由 checkpointer 持久化，
               支持 interrupt 挂起后用 `resume` 恢复，失败后可从最近 checkpoint 继续。
    resume:    中断恢复数据。传值时 LangGraph 从上次 interrupt 处继续执行，
               不会重复执行已完成的节点。
    """

    history = history or []
    components = components or []
    selected_component_ids = selected_component_ids or []
    cw = canvas_width or (canvas_style.get("width") if canvas_style else None) or DEFAULT_CANVAS_WIDTH
    ch = canvas_height or (canvas_style.get("height") if canvas_style else None) or DEFAULT_CANVAS_HEIGHT
    stage = resolve_stage(prompt, components, conversation_stage)

    messages = list(history)
    messages.append({"role": "user", "content": prompt})

    initial_state: AgentState = {
        "messages": messages,
        "prompt": prompt,
        "components": components,
        "canvas_style": canvas_style or {},
        "canvas_width": cw,
        "canvas_height": ch,
        "selected_component_ids": selected_component_ids,
        "viewport": viewport or {"width": cw, "height": ch, "scale": (canvas_style or {}).get("scale", 100)},
        "project_knowledge": project_knowledge,
        "requested_stage": conversation_stage,
        "stage": stage,
        "allowed_tools": TOOLS_BY_STAGE[stage],
        "result": {"reply": "", "actions": []},
        "plan": None,
    }

    if not settings.AI_API_KEY:
        return run_fallback_agent(initial_state, "AI_API_KEY is not configured")

    config = {
        "configurable": {
            "thread_id": thread_id or f"anon-{_gen_id(8)}",
        }
    }
    try:
        if resume is not None:
            # 从上次 interrupt 挂起点继续执行（不重复已完成的节点）
            result = await agent_graph.ainvoke(Command(resume=resume), config=config)
        else:
            result = await agent_graph.ainvoke(initial_state, config=config)
        return _extract_result(result, stage, config)
    except Exception as e:
        logger.error(f"[AI] Agent failed: {e}", exc_info=True)
        return {"reply": f"AI 处理失败: {str(e)}", "actions": [], "nextStage": stage}


def _extract_result(result: Dict[str, Any], stage: AgentStage, config: Dict[str, Any]) -> Dict[str, Any]:
    """从 LangGraph 返回值中提取前端可用的结果。

    - 正常结束：返回节点写入的 result。
    - interrupt 挂起（等待用户输入）：把挂起载荷（选项/问题/方案）转成响应，
      并附带 thread_id，前端后续请求凭 thread_id + resume 恢复执行。
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
            "threadId": config["configurable"]["thread_id"],
            "waitingForInput": True,
        }
    # 正常结束：返回节点写入的 result，并透传 planner 确认的方案（供评测/前端使用）
    normal_result = result.get("result", {"reply": "", "actions": []})
    if isinstance(normal_result, dict) and result.get("plan") is not None:
        normal_result = {**normal_result, "plan": result["plan"]}
    return normal_result

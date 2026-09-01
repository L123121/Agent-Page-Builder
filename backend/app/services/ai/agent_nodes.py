"""planner / executor 节点 — Agent 的 LLM 决策与闭环执行逻辑。

分工：
- planner_node：discover/design/plan/confirm 阶段的 LLM 决策与用户交互，
  需要用户输入时通过 interrupt 挂起图执行；
- executor_node：execute/edit 阶段的「执行 → 验证 → 修复」闭环，
  每轮工具调用后跑确定性验证器，验证结果回注下一轮 prompt。

自省修正（self-correction）三类触发源，全部以 ToolMessage 反馈回注：
- tool_not_allowed：工具不在当前阶段白名单；
- unresolved_component_ref：组件引用无法解析；
- no_canvas_diff：动作全部被跳过、画布无变化。
修正轮次写入 trace（type=correction），供 eval scorer 断言自省行为。
"""

import asyncio
import json
import logging
from copy import deepcopy
from typing import Any, Dict, List

from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

from app.config import settings

from .canvas_runtime import apply_actions_to_canvas, diff_canvas
from .component_utils import build_canvas_context
from .fallback import run_fallback_agent
from .llm import get_llm_client
from .prompts import build_system_prompt
from .schemas import AgentStage, AgentState
from .tool_handlers import process_tool_response
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

LOOP_INSTRUCTION = """你正在执行闭环画布任务。每轮只调用一个工具。
工具结果会返回真实执行状态和确定性验证报告。如果存在 error，必须根据报告继续调用 edit_page 修复；不要重复已经成功的操作。
修改/删除/移动组件时，id 必须使用画布状态中列出的组件 ID（方括号内的标识符）。
warning 可以按用户目标和设计意图决定是否修复。最多执行有限轮次，禁止重新询问已经明确的信息。"""


# ==================== LLM 调用 ====================

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


# ==================== 上下文构建辅助 ====================

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


def _correction_entry(step: int, error: str, detail: dict) -> dict:
    """修正轮次的 trace 记录（eval scorer 据此断言自省行为）。"""
    return {
        "type": "correction",
        "step": step,
        "error": error,
        "execution": [],
        "autoFixes": [],
        **detail,
    }


def _valid_component_directory(components: list[dict]) -> list[dict]:
    return [{"id": c.get("id"), "label": c.get("label", "")} for c in components]


# ==================== planner 节点 ====================

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

        # 自省修正：工具被拒 / 未调用工具 / 组件引用无法解析 → 注入反馈让模型重新决策
        unresolved_refs = result.get("unresolvedRefs") or []
        if (result.get("rejectedTools") or result.get("noToolCall") or unresolved_refs) and not (
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
            elif unresolved_refs:
                feedback = (
                    f"[系统反馈] 你引用的组件不存在：{json.dumps(unresolved_refs, ensure_ascii=False)}。"
                    f"画布上的组件：{json.dumps(_valid_component_directory(loop_state['components']), ensure_ascii=False)}。"
                    f"请使用上面列出的组件 id 重新决策。"
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


# ==================== executor 节点 ====================

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
                trace.append(_correction_entry(step, "tool_not_allowed", {"rejectedTools": rejected_tools}))
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

        # 自省修正：组件引用无法解析 → 附带有效组件清单注入下一轮，让模型用真实 ID 重试。
        # 本次所有操作不执行，避免「改对一半改错一半」的中间状态。
        unresolved_refs = step_result.get("unresolvedRefs") or []
        if unresolved_refs:
            feedback = {
                "error": "unresolved_component_ref",
                "unresolvedRefs": unresolved_refs,
                "validComponents": _valid_component_directory(working_components),
                "instruction": (
                    "你引用的组件在画布上不存在，本次所有操作均未执行。"
                    "请只使用 validComponents 中列出的组件 id 重新提交完整操作列表。"
                ),
            }
            trace.append(_correction_entry(step, "unresolved_component_ref", {"unresolvedRefs": unresolved_refs}))
            loop_messages.extend([
                response,
                ToolMessage(
                    content=json.dumps(feedback, ensure_ascii=False),
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
            # 自省修正：动作全部被跳过（ID 不存在 / 组件锁定等），画布无变化
            feedback = {
                "error": "no_canvas_diff",
                "execution": execution_events,
                "validComponents": _valid_component_directory(working_components),
                "instruction": (
                    "动作没有产生有效画布差异，请检查组件 ID、锁定状态和操作参数。"
                    "锁定（isLock=true）的组件无法修改，请改用其他组件或先提示用户。"
                ),
            }
            trace.append(_correction_entry(step, "no_canvas_diff", {"execution": execution_events}))
            loop_messages.extend([
                response,
                ToolMessage(
                    content=json.dumps(feedback, ensure_ascii=False),
                    tool_call_id=_tool_call_id(tool_call, step),
                ),
            ])
            continue

        tool_result = {
            "execution": execution_events,
            "autoFixes": auto_fixes,
            "validation": active_report,
            "instruction": (
                "根据 error 修复画布；不要重复已成功的动作。"
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

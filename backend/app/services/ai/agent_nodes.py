"""planner / await_user / executor 节点 — Agent 的 LLM 决策与闭环执行逻辑。

分工：
- planner_node：discover/design/plan/confirm 阶段的 LLM 决策与节点内修正闭环，
  需要用户输入时把挂起载荷写入 state["pending_input"] 并返回，由图路由到
  await_user 节点执行 interrupt；
- await_user_node：唯一调用 interrupt 的节点。LangGraph 的恢复语义是
  「从头重执行被中断的节点」，本节点除 interrupt 外无任何副作用，因此
  恢复零成本——对比把 interrupt 放在 planner 内部的旧实现（interrupt 之前的
  LLM 调用在恢复时被完整重放，每轮用户交互多付一次模型调用，且重放结果
  与用户选择不一致时用户输入会被静默丢弃）；
- executor_node：execute/edit 阶段的「执行 → 验证 → 修复」闭环，
  每轮工具调用后跑确定性验证器，验证结果回注下一轮 prompt。

自省修正（self-correction）触发源，全部以反馈消息回注：
- tool_not_allowed：工具不在当前阶段白名单；
- no_tool_call：没有调用任何工具（直接输出文本）；
- invalid_tool_args：工具参数不符合 Pydantic schema；
- unresolved_component_ref：组件引用无法解析；
- no_canvas_diff：动作全部被跳过、画布无变化。
修正轮次写入 trace（type=correction），供 eval scorer 断言自省行为，
并经 custom 流实时推送 SSE（见 _stream_emit）。

反馈消息的 API 合法性：OpenAI 协议要求 assistant 的每个 tool_call 都有
tool_call_id 精确对应的 ToolMessage 应答。带工具调用的响应统一经
_correction_messages 用真实 id 逐个应答；无工具调用的响应退化为
assistant + user 反馈（伪造 tool_call_id 会直接 400）。
"""

import asyncio
import json
import logging
from copy import deepcopy
from typing import Any, Dict

from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer
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
RETRY_AFTER_CAP_SECONDS = getattr(settings, "AI_RETRY_AFTER_CAP_SECONDS", 30.0)
MAX_AGENT_STEPS = getattr(settings, "AI_MAX_AGENT_STEPS", 6)
# 单次图执行允许的最大用户交互轮数：完整流程需要
# discover→design→plan→confirm 多次用户确认，10 次预留余量
MAX_INTERRUPT_ROUNDS = getattr(settings, "AI_MAX_INTERRUPT_ROUNDS", 10)

LOOP_INSTRUCTION = """你正在执行闭环画布任务。每轮只调用一个工具。
工具结果会返回真实执行状态和确定性验证报告。如果存在 error，必须根据报告继续调用 edit_page 修复；不要重复已经成功的操作。
修改/删除/移动组件时，id 必须使用画布状态中列出的组件 ID（方括号内的标识符）。
warning 可以按用户目标和设计意图决定是否修复。最多执行有限轮次，禁止重新询问已经明确的信息。"""


# ==================== 流式进度（custom stream） ====================

def _stream_emit(event: dict) -> None:
    """向 SSE custom 流推送实时进度事件。

    仅在流式图执行（astream 含 custom 模式）中有消费者；非流式调用与
    mock/单测直调节点时没有流上下文，get_stream_writer 会抛 RuntimeError，
    此处静默丢弃（进度是旁路，绝不影响主流程）。
    """
    try:
        get_stream_writer()(event)
    except RuntimeError:
        pass


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
                await asyncio.sleep(_retry_delay_seconds(error, attempt))
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_error}") from last_error


def _is_non_retryable_llm_error(error: Exception) -> bool:
    """401（鉴权失败）与 402（额度耗尽）重试无意义，立即失败走本地降级。"""
    message = str(error).lower()
    return (
        "401" in message
        or "402" in message
        or "invalid_api_key" in message
        or "incorrect api key" in message
        or "quota_exceeded" in message
    )


def _retry_delay_seconds(error: Exception, attempt: int) -> float:
    """指数退避；429 时尊重 Retry-After 响应头（封顶防请求挂死）。

    StepFun 等免费额度有 RPM 限流，固定 1s/2s 退避躲不开限流窗口，
    只能靠轮次耗尽后降级空画布——尊重 Retry-After 让限流下的请求大概率恢复。
    """
    delay = float(RETRY_BACKOFF_BASE ** attempt)
    retry_after = _parse_retry_after(error)
    if retry_after is not None:
        delay = max(delay, min(retry_after, RETRY_AFTER_CAP_SECONDS))
    return delay


def _parse_retry_after(error: Exception) -> float | None:
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _response_tool_call_ids(response) -> list[str]:
    """响应中全部 tool_call 的真实 id（用于构造 API 合法的反馈应答）。"""
    ids: list[str] = []
    for tool_call in getattr(response, "tool_calls", []) or []:
        tool_call_id = (
            tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
        )
        if tool_call_id:
            ids.append(tool_call_id)
    return ids


def _correction_messages(response, feedback: dict, step: int) -> list:
    """把修正反馈构造成 API 合法的消息序列。

    - 响应带 tool_calls：逐个用真实 tool_call_id 应答 ToolMessage
      （每个 tool_call 必须有应答，缺失会 400；第二个起附简短说明）；
    - 响应无 tool_calls：assistant 文本 + user 反馈（ToolMessage 无锚点会 400）。
    """
    payload = json.dumps(feedback, ensure_ascii=False)
    tool_call_ids = _response_tool_call_ids(response)
    if not tool_call_ids:
        return [
            {"role": "assistant", "content": getattr(response, "content", "") or ""},
            {"role": "user", "content": payload},
        ]
    messages: list = [response]
    for index, tool_call_id in enumerate(tool_call_ids):
        content = payload if index == 0 else "（本轮只处理第一个工具调用，反馈见前一条）"
        messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
    return messages


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


def _emit_correction(step: int | None, error: str, detail: dict | None = None) -> None:
    _stream_emit({
        "type": "self_correction",
        "step": step,
        "error": error,
        "detail": detail or {},
    })


def _valid_component_directory(components: list[dict]) -> list[dict]:
    return [{"id": c.get("id"), "label": c.get("label", "")} for c in components]


# ==================== planner 节点 ====================

async def planner_node(state: AgentState) -> Dict[str, Any]:
    """需求分析 Agent：discover/design/plan/confirm 阶段的 LLM 决策与节点内修正闭环。

    需要用户输入时不在这里 interrupt，而是把挂起载荷写入 state["pending_input"]
    并返回，由图条件边路由到 await_user 节点挂起——保证恢复时只重放无副作用的
    await_user，不重放本节点的 LLM 调用。
    确认后的设计方案写入 state["plan"]，供 executor 执行阶段注入上下文。
    """
    if state.get("interrupt_rounds", 0) > MAX_INTERRUPT_ROUNDS:
        return {"result": {"reply": "交互轮次过多，请重新描述需求", "actions": []}}

    confirmed_plan = state.get("plan")
    messages = list(state["messages"])
    for _ in range(MAX_INTERRUPT_ROUNDS):
        canvas_ctx = _build_canvas_context_from_state(state)
        system_content = build_system_prompt(state["stage"], canvas_ctx)
        llm_messages = [{"role": "system", "content": system_content}, *messages]
        tools = tools_for_stage(state["stage"])

        try:
            response = await _invoke_llm(llm_messages, tools)
        except Exception as error:
            logger.warning("[AI] switching to local fallback: %s", error)
            return {"result": run_fallback_agent(state, str(error)), "plan": confirmed_plan}

        result = process_tool_response(response, state)

        # 记录确认后的设计方案（confirm_plan 产出）
        if result.get("plan"):
            confirmed_plan = result["plan"]

        # 自省修正：工具被拒 / 未调用工具 / 引用无法解析 / 参数非法 → 注入反馈重新决策
        feedback = _planner_correction_feedback(result, state)
        if feedback is not None:
            messages = [
                *messages,
                {"role": "assistant", "content": result.get("reply") or ""},
                {"role": "user", "content": feedback["content"]},
            ]
            _emit_correction(None, feedback["error"], feedback.get("detail"))
            continue

        # 需要用户输入（选项 / 问题 / 方案确认）→ 写挂起载荷，交 await_user 节点 interrupt
        if result.get("options") or result.get("question") or result.get("plan"):
            return {
                "result": result,
                "plan": confirmed_plan,
                "pending_input": {
                    "type": "user_input",
                    "stage": state["stage"],
                    "nextStage": result.get("nextStage", state["stage"]),
                    "payload": result,
                },
            }

        # 产出可执行动作（generate / edit / finish）→ 交给前端执行
        return {"result": result, "plan": confirmed_plan}

    return {"result": {"reply": "交互轮次过多，请重新描述需求", "actions": []}, "plan": confirmed_plan}


def _planner_correction_feedback(result: dict, state: AgentState) -> dict | None:
    """planner 决策需要自省修正时返回反馈；返回 None 表示决策有效。

    修正优先级与 executor 的原子性语义对齐：
    - invalidArgs / unresolvedRefs 无条件修正：edit_page 一次调用里可能一半操作
      引用正确一半引用错误，若放行部分动作，unresolvedRefs 会被响应模型剥离、
      错误被静默吞掉，模型永远得不到纠正反馈；executor 对同信号是整批丢弃不
      执行，这里同样整批废弃、让模型重提交完整操作列表；
    - noToolCall / rejectedTools：仅在无有效产出时修正——白名单外的工具调用只是
      无害的旁支尝试，产出与修正信号并存时以产出为准。
    """
    invalid_args = result.get("invalidArgs")
    if invalid_args:
        return {
            "error": "invalid_tool_args",
            "detail": {"tool": invalid_args.get("tool"), "errors": invalid_args.get("errors")},
            "content": (
                f"[系统反馈] 你调用的工具 {invalid_args.get('tool')} 参数不符合定义："
                f"{json.dumps(invalid_args.get('errors', []), ensure_ascii=False)}。"
                f"请按工具定义修正参数后重新调用。"
            ),
        }
    unresolved_refs = result.get("unresolvedRefs") or []
    if unresolved_refs:
        return {
            "error": "unresolved_component_ref",
            "detail": {"unresolvedRefs": unresolved_refs},
            "content": (
                f"[系统反馈] 你引用的组件不存在，本次所有操作均未执行："
                f"{json.dumps(unresolved_refs, ensure_ascii=False)}。"
                f"画布上的组件：{json.dumps(_valid_component_directory(state['components']), ensure_ascii=False)}。"
                f"请只使用上面列出的组件 id 重新提交完整操作列表。"
            ),
        }
    if not (result.get("rejectedTools") or result.get("noToolCall")):
        return None
    if (
        result.get("actions") or result.get("options")
        or result.get("question") or result.get("plan") or result.get("finished")
    ):
        # 已有有效产出：修正信号与产出并存时以产出为准
        return None

    allowed = ", ".join(state["allowed_tools"])
    if result.get("noToolCall"):
        return {
            "error": "no_tool_call",
            "content": (
                f"[系统反馈] 你没有调用工具而是直接输出文本。当前阶段"
                f"（{state['stage']}）必须通过工具决策。"
                f"当前允许的工具：{allowed}。请重新决策并调用工具。"
            ),
        }
    rejected = result["rejectedTools"]
    return {
        "error": "tool_not_allowed",
        "detail": {"rejectedTools": rejected},
        "content": (
            f"[系统反馈] 你调用的工具 {rejected} 不在当前阶段"
            f"（{state['stage']}）允许的工具中。当前允许的工具：{allowed}。请重新决策。"
        ),
    }


# ==================== await_user 节点 ====================

async def await_user_node(state: AgentState) -> Dict[str, Any]:
    """等待用户输入：唯一调用 interrupt 的节点，恢复后应用用户选择。

    本节点除 interrupt 外无副作用——LangGraph 恢复语义是「从头重执行被中断
    的节点」，重放它零成本，planner 已完成的 LLM 决策因此不会被重复调用。
    """
    pending = state.get("pending_input") or {}
    user_input = interrupt(pending)

    payload = pending.get("payload") or {}
    assistant_reply = payload.get("reply") or ""
    next_stage = payload.get("nextStage") or pending.get("nextStage") or state["stage"]
    return {
        "messages": [
            *state["messages"],
            {"role": "assistant", "content": assistant_reply},
            {"role": "user", "content": str(user_input)},
        ],
        "stage": next_stage,
        "allowed_tools": TOOLS_BY_STAGE[next_stage],
        "pending_input": None,
        "interrupt_rounds": state.get("interrupt_rounds", 0) + 1,
    }


# ==================== executor 节点 ====================

async def executor_node(state: AgentState) -> Dict[str, Any]:
    """画布执行 Agent：执行工具 → 读取结果 → 验证 → 修复，直到完成或达到上限。

    从 planner 确认的方案（state["plan"]）注入执行上下文，保证生成结果
    与已确认的设计方向一致。每轮的工具调用/验证结果/自省修正经 custom 流
    实时推送（_stream_emit），SSE 端不再等整个节点跑完才回放 trace。
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
        unresolved_refs = step_result.get("unresolvedRefs") or []
        invalid_args = step_result.get("invalidArgs")
        if not tool_call:
            # 自省修正：工具不在阶段白名单 / 未调用工具 → 反馈注入下一轮重新决策
            if rejected_tools:
                feedback = {
                    "error": "tool_not_allowed",
                    "rejectedTools": rejected_tools,
                    "allowedTools": allowed_tools,
                    "instruction": "你调用的工具不在当前阶段白名单中，请只调用 allowedTools 列出的工具重新决策。",
                }
                trace.append(_correction_entry(step, "tool_not_allowed", {"rejectedTools": rejected_tools}))
                _emit_correction(step, "tool_not_allowed", {"rejectedTools": rejected_tools})
                loop_messages.extend(_correction_messages(response, feedback, step))
                continue
            feedback = {
                "error": "no_tool_call",
                "allowedTools": allowed_tools,
                "instruction": "你没有调用工具。当前阶段必须调用 allowedTools 中的工具推进任务，请重新决策。",
            }
            trace.append(_correction_entry(step, "no_tool_call", {}))
            _emit_correction(step, "no_tool_call")
            loop_messages.extend(_correction_messages(response, feedback, step))
            continue

        tool_name = _tool_call_name(tool_call)
        if step_result.get("finished"):
            trace.append({
                "step": step,
                "tool": tool_name,
                "execution": [],
                "autoFixes": [],
                "validation": final_validation,
            })
            _stream_emit({
                "type": "tool_call", "step": step, "tool": tool_name,
            })
            _stream_emit({
                "type": "tool_result", "step": step, "tool": tool_name,
                "status": "done", "validation": final_validation, "autoFixes": [],
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
            loop_messages.extend(_correction_messages(response, {
                "validation": final_validation,
                "instruction": "仍有 error，不能结束；请调用 edit_page 修复。",
            }, step))
            continue

        # 自省修正：参数非法 / 组件引用无法解析 → 附带有效清单注入下一轮重试。
        # 本次所有操作不执行，避免「改对一半改错一半」的中间状态。
        if invalid_args or unresolved_refs:
            if invalid_args:
                feedback = {
                    "error": "invalid_tool_args",
                    "tool": invalid_args.get("tool"),
                    "errors": invalid_args.get("errors"),
                    "instruction": "你调用的工具参数不符合定义，请按 errors 修正参数后重新提交完整操作。",
                }
                trace.append(_correction_entry(step, "invalid_tool_args", {"invalidArgs": invalid_args}))
                _emit_correction(step, "invalid_tool_args", {"invalidArgs": invalid_args})
            else:
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
                _emit_correction(step, "unresolved_component_ref", {"unresolvedRefs": unresolved_refs})
            loop_messages.extend(_correction_messages(response, feedback, step))
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

        _stream_emit({"type": "tool_call", "step": step, "tool": tool_name})
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

        def _emit_tool_result() -> None:
            _stream_emit({
                "type": "tool_result", "step": step, "tool": tool_name,
                "status": "done", "validation": active_report, "autoFixes": auto_fixes,
            })

        if active_report["valid"]:
            _emit_tool_result()
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
            _emit_correction(step, "no_canvas_diff", {"execution": execution_events})
            loop_messages.extend(_correction_messages(response, feedback, step))
            continue

        _emit_tool_result()
        tool_result = {
            "execution": execution_events,
            "autoFixes": auto_fixes,
            "validation": active_report,
            "instruction": (
                "根据 error 修复画布；不要重复已成功的动作。"
            ),
        }
        loop_messages.extend(_correction_messages(response, tool_result, step))

    return {
        "result": {
            "reply": f"{last_reply or '页面处理未完成'}；达到最大修复轮次，未应用存在错误的结果",
            "actions": [],
            "nextStage": state["stage"],
            "validation": final_validation,
            "trace": trace,
        }
    }

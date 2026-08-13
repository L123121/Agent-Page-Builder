"""Eval 评分器

将一次 Agent 运行结果与任务期望标准比对，输出：
  - 细粒度得分（0~100，按检查项加权）
  - 通过/未通过的检查项明细（便于复盘）
  - 是否整体通过（pass）

检查项覆盖：组件数量、组件类型、文本关键字、禁止组件、画布验证器、
步数预算、标题字号、初始方向确认、布局应用，以及 Python 版专属的
方案产出（planner→state）、阶段到达、自省修正、修复轮次上限。
"""

from typing import Any, Dict, List, Optional

from app.services.ai.validator import validate_canvas

from .tasks import EvalTask


class EvalRunResult(Dict[str, Any]):
    """一次 Agent 运行的评测结果（结构与 Node 版 eval.types 对齐）"""


def collect_texts(components: List[dict]) -> List[str]:
    """收集文本组件内容（VText/VButton 的 propValue 为字符串）"""
    texts = []
    for component in components:
        prop_value = component.get("propValue")
        if isinstance(prop_value, str) and prop_value.strip():
            texts.append(prop_value)
    return texts


def has_relayout(components: List[dict], tolerance: int = 30) -> bool:
    """组件是否被重新排布：至少一个根组件的位置不再是 (0,0) 附近"""
    return any(
        component.get("parentId") is None
        and (
            abs(float(component.get("style", {}).get("left") or 0)) > tolerance
            or abs(float(component.get("style", {}).get("top") or 0)) > tolerance
        )
        for component in components
    )


def has_centered_title(components: List[dict], canvas_style: dict, tolerance: int) -> bool:
    """标题是否水平居中（left + width/2 与画布中心接近）"""
    center_x = (float(canvas_style.get("width") or 375)) / 2
    return any(
        abs(
            float(component.get("style", {}).get("left") or 0)
            + (float(component.get("style", {}).get("width") or 0)) / 2
            - center_x
        ) <= tolerance
        for component in components
    )


def _tool_step_count(steps: List[dict]) -> int:
    return sum(1 for step in steps if step.get("type") == "tool_call")


def _self_corrected(trace: List[dict]) -> bool:
    """是否发生过自省修正：trace 中出现 tool_not_allowed 反馈后继续执行"""
    return any(
        step.get("error") == "tool_not_allowed"
        or "tool_not_allowed" in str(step)
        for step in trace or []
    )


def score_run(task: EvalTask, run: EvalRunResult) -> EvalRunResult:
    """评分一次运行结果"""
    expected = task.get("expected") or {}
    final_canvas = run.get("finalCanvas") or []
    canvas_style = run.get("canvasStyle") or task.get("canvasStyle") or {}
    steps = run.get("steps") or []
    trace = run.get("trace") or []
    failures: List[dict] = []
    passed_checks: List[dict] = []
    counts = {"checked": 0, "passed": 0}

    def check(code: str, passed: bool, message: str) -> None:
        counts["checked"] += 1
        if passed:
            counts["passed"] += 1
            passed_checks.append({"code": code, "message": message})
        else:
            failures.append({"code": code, "message": message})

    # 运行异常：直接判失败，不再做后续期望比对
    if run.get("error"):
        failures.append({"code": "RUN_ERROR", "message": str(run["error"])})
        return {
            "taskId": task.get("id", ""),
            "taskName": task.get("name", ""),
            "pass": False,
            "score": 0,
            "failures": failures,
            "passedChecks": passed_checks,
            "finalCanvas": final_canvas,
            "canvasStyle": canvas_style,
            "steps": steps,
            "trace": trace,
            "plan": run.get("plan"),
            "nextStage": run.get("nextStage"),
            "durationMs": run.get("durationMs", 0),
            "tokenUsage": run.get("tokenUsage"),
            "provider": run.get("provider"),
            "error": run["error"],
        }

    # ==================== 常规检查项 ====================

    if expected.get("minComponents") is not None:
        check(
            "MIN_COMPONENTS",
            len(final_canvas) >= expected["minComponents"],
            f"组件数 {len(final_canvas)} >= {expected['minComponents']}",
        )

    for component_type in expected.get("requireComponents") or []:
        present = any(c.get("component") == component_type for c in final_canvas)
        check(
            f"REQUIRE_COMPONENT_{component_type}",
            present,
            f"存在组件类型 {component_type}",
        )

    texts = collect_texts(final_canvas)
    for keyword in expected.get("requireText") or []:
        found = any(keyword in text for text in texts)
        check(
            f"REQUIRE_TEXT_{keyword}",
            found,
            f"文本内容包含「{keyword}」",
        )

    for component_type in expected.get("forbidComponents") or []:
        absent = not any(c.get("component") == component_type for c in final_canvas)
        check(
            f"FORBID_COMPONENT_{component_type}",
            absent,
            f"未包含组件类型 {component_type}",
        )

    if expected.get("validatorPass"):
        cw = int(canvas_style.get("width") or 375)
        ch = int(canvas_style.get("height") or 667)
        validation = validate_canvas(final_canvas, cw, ch, canvas_style)
        check(
            "VALIDATOR_PASS",
            validation["errorCount"] == 0,
            f"画布通过验证器（errors={validation['errorCount']}, warnings={validation['warningCount']}）",
        )

    if expected.get("maxSteps") is not None:
        tool_steps = _tool_step_count(steps)
        check(
            "MAX_STEPS",
            tool_steps <= expected["maxSteps"],
            f"工具步数 {tool_steps} <= {expected['maxSteps']}",
        )

    if expected.get("titleFontSizeMin") is not None:
        font_sizes = [
            float(c.get("style", {}).get("fontSize") or 0)
            for c in final_canvas if c.get("component") == "VText"
        ]
        max_font = max(font_sizes) if font_sizes else 0
        check(
            "TITLE_FONT_SIZE",
            max_font >= expected["titleFontSizeMin"],
            f"标题字号 {max_font} >= {expected['titleFontSizeMin']}",
        )

    if expected.get("requireInitialChoice"):
        asked = any(
            step.get("type") in ("ask_user", "user_input") or step.get("tool") == "ask_user"
            for step in steps
        ) or bool(run.get("waitingForInput"))
        check("REQUIRE_INITIAL_CHOICE", asked, "模糊需求触发了方向确认")

    if expected.get("layoutApplied"):
        check("LAYOUT_APPLIED", has_relayout(final_canvas), "组件被重新排布（布局已应用）")

    if expected.get("centeredLeftTolerance") is not None:
        check(
            "CENTERED_TITLE",
            has_centered_title(final_canvas, canvas_style, expected["centeredLeftTolerance"]),
            f"标题水平居中（容差 {expected['centeredLeftTolerance']}px）",
        )

    # ==================== Python 版专属检查项 ====================

    if expected.get("planWritten"):
        check("PLAN_WRITTEN", bool(run.get("plan")), "planner 产出了设计方案并写入 state")

    if expected.get("requiredStage"):
        check(
            "STAGE_REACHED",
            run.get("nextStage") == expected["requiredStage"],
            f"最终阶段 {run.get('nextStage')} == {expected['requiredStage']}",
        )

    if expected.get("selfCorrected"):
        check("SELF_CORRECTED", _self_corrected(trace), "发生过工具被拒后的自省修正")

    if expected.get("maxRepairRounds") is not None:
        repair_count = sum(
            1 for step in trace or []
            if step.get("autoFixes") and len(step["autoFixes"]) > 0
        )
        check(
            "REPAIR_BOUNDED",
            repair_count <= expected["maxRepairRounds"],
            f"修复轮次 {repair_count} <= {expected['maxRepairRounds']}",
        )

    # ==================== 汇总 ====================

    score = 100 if counts["checked"] == 0 else round((counts["passed"] / counts["checked"]) * 100)

    return {
        "taskId": task.get("id", ""),
        "taskName": task.get("name", ""),
        "pass": len(failures) == 0,
        "score": score,
        "failures": failures,
        "passedChecks": passed_checks,
        "finalCanvas": final_canvas,
        "canvasStyle": canvas_style,
        "steps": steps,
        "trace": trace,
        "plan": run.get("plan"),
        "nextStage": run.get("nextStage"),
        "durationMs": run.get("durationMs", 0),
        "tokenUsage": run.get("tokenUsage"),
        "provider": run.get("provider"),
    }

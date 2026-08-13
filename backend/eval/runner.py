"""Agent Eval 运行器 — mock / live 双模式

mock 模式：脚本化 LLM 决策（不调真实模型），确定性回归工具执行、
验证-修复循环、多 Agent（planner/executor）逻辑，适合 CI。
live 模式：真实 LLM 全链路运行，量化质量（组件覆盖、验证器通过率、
方案产出），改 prompt / 工具 / 验证器后对比分数。

用法：
  python -m eval.runner --mode mock            # 跑全部任务（mock）
  python -m eval.runner --mode live            # 跑全部任务（真实 LLM）
  python -m eval.runner --mode live --task poster_dance_recruit
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

# 允许从 backend/ 目录直接执行 python -m eval.runner
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai.agent import executor_node, planner_node, run_agent  # noqa: E402
from app.services.ai.canvas_runtime import apply_actions_to_canvas  # noqa: E402
from app.services.ai.component_utils import normalize_component  # noqa: E402

from .scorer import EvalRunResult, score_run  # noqa: E402
from .tasks import EvalTask, get_eval_tasks  # noqa: E402
from .judge import judge_run  # noqa: E402

logger = logging.getLogger("eval")


# ==================== Mock LLM（脚本化决策） ====================

class MockToolCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class MockResponse:
    content = ""

    def __init__(self, *tool_calls: MockToolCall):
        self.tool_calls = list(tool_calls)


def _text(title: str, font_size: int = 24, **style_overrides) -> dict:
    style = {
        "width": 300, "height": 60, "top": 60, "left": 37,
        "fontSize": font_size, "fontWeight": 700, "color": "#111111",
        "textAlign": "center", "padding": 4,
    }
    style.update(style_overrides)
    return {"component": "VText", "label": title, "propValue": title, "style": style}


def _button(text: str) -> dict:
    return {
        "component": "VButton",
        "label": text,
        "propValue": text,
        "style": {
            "width": 200, "height": 48, "top": 400, "left": 87,
            "fontSize": 18, "fontWeight": 600, "color": "#ffffff",
            "backgroundColor": "#409eff", "textAlign": "center",
        },
    }


def _mock_generate_components(task: EvalTask) -> list:
    """按任务 id 构造满足期望的 mock 生成结果（确定性回归用）"""
    task_id = task.get("id", "")
    if task_id == "poster_dance_recruit":
        return [
            _text("街舞社招新", 32),
            _text("时间：9月15日 地点：大学生活动中心", 16, fontWeight=400, top=140),
            _button("立即报名"),
        ]
    if task_id == "poster_activity_promo":
        return [
            _text("校园音乐节", 32),
            _text("时间：周五晚 地点：操场", 16, fontWeight=400, top=140),
            _text("等你来嗨", 14, fontWeight=400, top=220),
        ]
    if task_id == "form_registration":
        return [
            _text("社团报名表", 28),
            _text("姓名：____ 联系方式：____", 16, fontWeight=400, top=140),
            _button("提交报名"),
        ]
    return [_text("默认标题", 24)]


def _mock_response_for_task(task: EvalTask, state: dict) -> MockResponse:
    """根据任务 id 构造 mock LLM 的 tool_call 响应"""
    task_id = task.get("id", "")
    if task_id == "edit_title_font":
        return MockResponse(MockToolCall("edit_page", {
            "reply": "已放大标题",
            "operations": [{"type": "modify", "id": "title_1", "style": {"fontSize": 32}}],
        }))
    if task_id == "delete_component":
        return MockResponse(MockToolCall("edit_page", {
            "reply": "已删除图片",
            "operations": [{"type": "delete", "id": "pic_1"}],
        }))
    if task_id == "layout_center_focus":
        return MockResponse(MockToolCall("edit_page", {
            "reply": "已居中布局",
            "operations": [
                {"type": "move", "id": "t1", "top": 60, "left": 37},
                {"type": "move", "id": "t2", "top": 140, "left": 37},
            ],
        }))
    if task_id == "empty_canvas_vague":
        # 模糊需求：planner 应产出方向确认（propose_options），而非直接生成
        return MockResponse(MockToolCall("propose_options", {
            "reply": "请选择页面方向",
            "options": [
                {"id": "poster", "title": "宣传海报", "description": "主视觉 + 行动入口"},
                {"id": "form", "title": "报名表", "description": "信息登记"},
            ],
        }))
    # 生成类默认：generate_page
    return MockResponse(MockToolCall("generate_page", {
        "reply": "页面已生成",
        "canvasStyle": {"width": 375, "height": 667, "backgroundColor": "#ffffff"},
        "components": _mock_generate_components(task),
    }))


def _build_state(task: EvalTask, stage: str = "execute") -> dict:
    """从任务构建 AgentState（mock 模式直接驱动节点）"""
    canvas_style = task.get("canvasStyle") or {}
    return {
        "messages": [{"role": "user", "content": task.get("prompt", "")}],
        "prompt": task.get("prompt", ""),
        "components": deepcopy(task.get("initialCanvas") or []),
        "canvas_style": canvas_style,
        "canvas_width": int(canvas_style.get("width") or 375),
        "canvas_height": int(canvas_style.get("height") or 667),
        "selected_component_ids": [],
        "viewport": {"width": int(canvas_style.get("width") or 375), "height": int(canvas_style.get("height") or 667), "scale": 100},
        "project_knowledge": "",
        "requested_stage": stage,
        "stage": stage,
        "allowed_tools": [],
        "result": {"reply": "", "actions": []},
        "plan": None,
    }


def _assemble_steps(trace: list) -> list:
    """把节点 trace 转成 EvalRunResult.steps（供 MAX_STEPS 检查）"""
    steps = []
    for step in trace or []:
        if isinstance(step, dict) and step.get("tool"):
            steps.append({"type": "tool_call", "tool": step["tool"]})
    return steps


async def run_mock(task: EvalTask) -> EvalRunResult:
    """mock 模式：脚本化 LLM 驱动 executor（执行类）或 planner（交互类）"""
    start = time.monotonic()
    expected = task.get("expected") or {}

    try:
        if expected.get("requireInitialChoice"):
            # 交互类：走 planner，mock interrupt 捕获方向确认
            state = _build_state(task, stage="discover")
            state["allowed_tools"] = ["propose_options", "ask_question"]
            captured = {}

            def fake_interrupt(payload):
                captured["payload"] = payload
                return "我选择「宣传海报」"

            with patch("app.services.ai.agent.interrupt", side_effect=fake_interrupt), \
                 patch("app.services.ai.agent._invoke_llm", new=AsyncMock(return_value=_mock_response_for_task(task, state))):
                result = await planner_node(state)

            plan = result.get("plan")
            trace = result.get("result", {}).get("trace", [])
            steps = _assemble_steps(trace)
            waiting = bool(captured.get("payload"))
            return {
                "taskId": task.get("id", ""),
                "taskName": task.get("name", ""),
                "pass": False,
                "score": 0,
                "failures": [],
                "passedChecks": [],
                "finalCanvas": [],
                "canvasStyle": task.get("canvasStyle") or {},
                "steps": steps,
                "trace": trace,
                "plan": plan,
                "nextStage": result.get("result", {}).get("nextStage") or "discover",
                "waitingForInput": waiting,
                "durationMs": int((time.monotonic() - start) * 1000),
                "tokenUsage": None,
                "provider": "mock",
            }

        # 执行类：走 executor，mock LLM 返回一个合法工具调用
        state = _build_state(task, stage="execute")
        state["allowed_tools"] = ["generate_page", "edit_page", "finish"]
        state["plan"] = {"summary": task.get("name", ""), "details": ["确定性 mock 回归"]}

        with patch("app.services.ai.agent._invoke_llm", new=AsyncMock(return_value=_mock_response_for_task(task, state))):
            result = await executor_node(state)

        payload = result.get("result", {})
        actions = payload.get("actions", [])
        final_canvas, final_style, _ = apply_actions_to_canvas(
            deepcopy(task.get("initialCanvas") or []),
            deepcopy(task.get("canvasStyle") or {}),
            actions,
        )
        return {
            "taskId": task.get("id", ""),
            "taskName": task.get("name", ""),
            "pass": False,
            "score": 0,
            "failures": [],
            "passedChecks": [],
            "finalCanvas": final_canvas,
            "canvasStyle": final_style,
            "steps": _assemble_steps(payload.get("trace", [])),
            "trace": payload.get("trace", []),
            "plan": state["plan"],
            "nextStage": payload.get("nextStage"),
            "durationMs": int((time.monotonic() - start) * 1000),
            "tokenUsage": None,
            "provider": "mock",
        }
    except Exception as error:  # 运行异常：交给 scorer 判 RUN_ERROR
        logger.warning("mock run failed for %s: %s", task.get("id"), error)
        return {
            "taskId": task.get("id", ""),
            "taskName": task.get("name", ""),
            "pass": False,
            "score": 0,
            "failures": [],
            "passedChecks": [],
            "finalCanvas": [],
            "canvasStyle": task.get("canvasStyle") or {},
            "steps": [],
            "trace": [],
            "plan": None,
            "nextStage": None,
            "durationMs": int((time.monotonic() - start) * 1000),
            "tokenUsage": None,
            "provider": "mock",
            "error": str(error),
        }


async def run_live(task: EvalTask, thread_id: str | None = None) -> EvalRunResult:
    """live 模式：真实 LLM 全链路运行（route → planner → executor）

    自动模拟多轮交互：当 Agent 挂起等待用户输入（interrupt）时，
    按 options → plan → suggestions 的优先级自动给出用户回复，
    用 Command(resume) 恢复执行，直到产出可执行动作或达到轮次上限。
    """
    start = time.monotonic()
    canvas_style = task.get("canvasStyle") or {}
    initial_canvas = task.get("initialCanvas") or []
    max_rounds = 10
    trace_all: list = []
    last_result: dict = {}

    try:
        result = await run_agent(
            prompt=task.get("prompt", ""),
            history=[],
            components=initial_canvas,
            canvas_style=canvas_style,
            canvas_width=int(canvas_style.get("width") or 375),
            canvas_height=int(canvas_style.get("height") or 667),
            selected_component_ids=[],
            viewport={"width": int(canvas_style.get("width") or 375), "height": int(canvas_style.get("height") or 667), "scale": 100},
            project_knowledge="",
            conversation_stage=None,
            thread_id=thread_id,
        )
        last_result = result
        trace_all.extend(result.get("trace", []))

        # 多轮交互：Agent interrupt 挂起时自动回复并恢复，直到拿到可执行动作
        for _round in range(max_rounds):
            if not result.get("waitingForInput"):
                break

            resume_value = _auto_resume(result)
            if resume_value is None:
                break

            result = await run_agent(
                prompt=resume_value,
                thread_id=result.get("threadId") or thread_id,
                resume=resume_value,
            )
            last_result = result
            trace_all.extend(result.get("trace", []))

        if last_result.get("waitingForInput"):
            # 轮次耗尽仍未生成：把最后挂起的信息作为证据返回
            return {
                "taskId": task.get("id", ""),
                "taskName": task.get("name", ""),
                "pass": False,
                "score": 0,
                "failures": [],
                "passedChecks": [],
                "finalCanvas": initial_canvas,
                "canvasStyle": canvas_style,
                "steps": [],
                "trace": trace_all,
                "plan": last_result.get("plan"),
                "nextStage": last_result.get("nextStage"),
                "waitingForInput": True,
                "durationMs": int((time.monotonic() - start) * 1000),
                "tokenUsage": None,
                "provider": "live",
            }

        actions = last_result.get("actions", [])
        final_canvas, final_style, _ = apply_actions_to_canvas(
            deepcopy(initial_canvas),
            deepcopy(canvas_style),
            actions,
        )
        return {
            "taskId": task.get("id", ""),
            "taskName": task.get("name", ""),
            "pass": False,
            "score": 0,
            "failures": [],
            "passedChecks": [],
            "finalCanvas": final_canvas,
            "canvasStyle": final_style,
            "steps": [],
            "trace": trace_all,
            "plan": last_result.get("plan"),
            "nextStage": last_result.get("nextStage"),
            "durationMs": int((time.monotonic() - start) * 1000),
            "tokenUsage": None,
            "provider": "live",
        }
    except Exception as error:
        logger.error("live run failed for %s: %s", task.get("id"), error)
        return {
            "taskId": task.get("id", ""),
            "taskName": task.get("name", ""),
            "pass": False,
            "score": 0,
            "failures": [],
            "passedChecks": [],
            "finalCanvas": initial_canvas,
            "canvasStyle": canvas_style,
            "steps": [],
            "trace": trace_all,
            "plan": None,
            "nextStage": None,
            "durationMs": int((time.monotonic() - start) * 1000),
            "tokenUsage": None,
            "provider": "live",
            "error": str(error),
        }


def _auto_resume(result: dict) -> str | None:
    """根据挂起载荷自动生成用户回复（模拟用户点击/确认）"""
    options = result.get("options")
    if options:
        first = options[0]
        return f"我选择「{first.get('title')}」"
    if result.get("plan"):
        return "确认，请生成"
    suggestions = result.get("suggestions")
    if suggestions:
        return suggestions[0]
    return None


async def run_eval(
    tasks: Optional[List[EvalTask]] = None,
    mode: str = "mock",
    report_dir: Optional[Path] = None,
    delay_seconds: float = 0,
) -> dict:
    """运行全部任务并汇总报告

    delay_seconds: live 模式任务间延迟（秒）。StepFun 免费额度有 RPM 限流
    （约 10 次/分钟），生成类任务一次要多轮 LLM 调用，连续跑易触发 429，
    任务间加延迟可避开限流窗口，得到真实质量分数。
    """
    tasks = tasks if tasks is not None else get_eval_tasks()
    results = []
    for index, task in enumerate(tasks):
        if mode == "live" and delay_seconds > 0 and index > 0:
            logger.info("[eval] waiting %.1fs before next live task (RPM throttle)", delay_seconds)
            await asyncio.sleep(delay_seconds)
        if mode == "live":
            run = await run_live(task, thread_id=f"eval-{task.get('id')}")
        else:
            run = await run_mock(task)
        scored = score_run(task, run)
        if mode == "live":
            # LLM-as-a-Judge：规则化评分之外的 0~100 质量评审（仅 live 消耗 token）
            judged = await judge_run(task, run)
            scored["judgeScore"] = judged["judgeScore"]
            scored["judgeSummary"] = judged["judgeSummary"]
            scored["judgeIssues"] = judged["judgeIssues"]
            scored["judgeError"] = judged["judgeError"]
            judge_text = f" judge={judged['judgeScore']}" if judged["judgeScore"] is not None else " judge=err"
        else:
            judge_text = ""
        results.append(scored)
        print(f"[{mode}] {task.get('id'):<28} score={scored['score']:>3} pass={scored['pass']} failures={len(scored['failures'])}{judge_text}")

    total_score = round(sum(r["score"] for r in results) / len(results)) if results else 0
    passed = sum(1 for r in results if r["pass"])
    judge_scores = [r["judgeScore"] for r in results if r.get("judgeScore") is not None]
    avg_judge = round(sum(judge_scores) / len(judge_scores)) if judge_scores else None
    summary = {
        "mode": mode,
        "taskCount": len(results),
        "passedCount": passed,
        "passRate": round(passed / len(results) * 100) if results else 0,
        "avgScore": total_score,
        "avgJudgeScore": avg_judge,
        "results": results,
    }

    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"eval-{mode}-{time.strftime('%Y-%m-%dT%H-%M-%S')}.json"
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {report_path}")

    judge_text = f"  平均 Judge 分: {avg_judge}" if avg_judge is not None else ""
    print(f"\n===== 汇总 ({mode}) =====")
    print(f"任务数: {summary['taskCount']}  通过: {summary['passedCount']}  通过率: {summary['passRate']}%  平均分: {summary['avgScore']}{judge_text}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Agent 评测")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--task", default=None, help="只跑指定任务 id")
    parser.add_argument("--report-dir", default=str(BACKEND_DIR / "eval" / "reports"))
    parser.add_argument("--delay", type=float, default=7.0,
                        help="live 模式任务间延迟秒数（默认 7s，避开 StepFun RPM 限流）")
    parser.add_argument("--require-pass-rate", type=float, default=None,
                        help="通过率门禁（0~100）：评测结束后若通过率低于该值则退出码非 0。"
                             "CI 用 mock 模式 + 100 门禁做回归防劣化")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    tasks = get_eval_tasks()
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]

    summary = asyncio.run(run_eval(
        tasks=tasks,
        mode=args.mode,
        report_dir=Path(args.report_dir),
        delay_seconds=args.delay if args.mode == "live" else 0,
    ))

    # CI 门禁：通过率不达标时非零退出（供 GitHub Actions 判定失败）
    if args.require_pass_rate is not None:
        rate = summary["passRate"]
        if rate < args.require_pass_rate:
            print(f"\n[CI-GATE] 通过率 {rate}% < 要求 {args.require_pass_rate}% → 评测未通过，退出码 1")
            sys.exit(1)
        print(f"\n[CI-GATE] 通过率 {rate}% >= 要求 {args.require_pass_rate}% → 评测通过")


if __name__ == "__main__":
    main()

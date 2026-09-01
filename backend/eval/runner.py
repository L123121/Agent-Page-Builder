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


# 生成类任务：任务 id → 满足期望标准的组件脚本（确定性回归用）
_MOCK_GENERATION_SCRIPTS: Dict[str, list] = {
    "poster_dance_recruit": [
        _text("街舞社招新", 32),
        _text("时间：9月15日 地点：大学生活动中心", 16, fontWeight=400, top=140),
        _button("立即报名"),
    ],
    "poster_activity_promo": [
        _text("校园音乐节", 32),
        _text("时间：周五晚 地点：操场", 16, fontWeight=400, top=140),
        _text("等你来嗨", 14, fontWeight=400, top=220),
    ],
    "form_registration": [
        _text("社团报名表", 28),
        _text("姓名：____ 联系方式：____", 16, fontWeight=400, top=140),
        _button("提交报名"),
    ],
    "poster_lecture": [
        _text("人工智能前沿讲座", 32),
        _text("主讲人：张教授 时间：10月12日 地点：图书馆报告厅", 16, fontWeight=400, top=140),
    ],
    "poster_job_fair": [
        _text("秋季双选会", 32),
        _text("时间：11月1日 地点：体育馆", 16, fontWeight=400, top=140),
        _button("投递简历"),
    ],
    "poster_movie_night": [
        _text("露天电影之夜", 32),
        _text("本周五晚 19:00 操场草坪", 16, fontWeight=400, top=140),
    ],
    "poster_sports_meet": [
        _text("校运动会", 32),
        _text("时间：10月20-21日 地点：田径场", 16, fontWeight=400, top=140),
        _button("报名参赛"),
    ],
    "form_questionnaire": [
        _text("校园服务满意度问卷", 28),
        _text("请留下你的真实反馈，帮助我们一起改进", 16, fontWeight=400, top=140),
        _button("提交问卷"),
    ],
    "form_vote": [
        _text("社团最佳节目投票", 28),
        _text("每人限投一票，结果实时公示", 16, fontWeight=400, top=140),
        _button("立即投票"),
    ],
    "page_club_intro": [
        _text("动漫社团介绍", 32),
        _text("我们是一个热爱二次元的大家庭", 16, fontWeight=400, top=140),
        _text("每周六社团活动室见", 14, fontWeight=400, top=220),
    ],
    "page_lost_found": [
        _text("失物招领", 28),
        _text("拾到物品请交至学生会办公室", 16, fontWeight=400, top=140),
    ],
    "page_notice": [
        _text("放假通知", 28),
        _text("国庆节放假安排如下", 16, fontWeight=400, top=140),
        _text("10月1日至10月7日", 14, fontWeight=400, top=220),
    ],
}


def _mock_generate_components(task: EvalTask) -> list:
    """按任务 id 构造满足期望的 mock 生成结果（确定性回归用）"""
    return _MOCK_GENERATION_SCRIPTS.get(task.get("id", ""), [_text("默认标题", 24)])


# 单轮编辑类任务：任务 id → 一次 edit_page 调用脚本
_MOCK_EDIT_SCRIPTS: Dict[str, MockResponse] = {
    "edit_title_font": MockResponse(MockToolCall("edit_page", {
        "reply": "已放大标题",
        "operations": [{"type": "modify", "id": "title_1", "style": {"fontSize": 32}}],
    })),
    "edit_button_text": MockResponse(MockToolCall("edit_page", {
        "reply": "已修改按钮文案",
        "operations": [{"type": "modify", "id": "btn_1", "propValue": "立即参与"}],
    })),
    "edit_text_color": MockResponse(MockToolCall("edit_page", {
        "reply": "已调整标题颜色",
        "operations": [{"type": "modify", "id": "title_1", "style": {"color": "#0a58ce"}}],
    })),
    "edit_move_component": MockResponse(MockToolCall("edit_page", {
        "reply": "已移动标题到底部",
        "operations": [{"type": "move", "id": "title_1", "top": 500, "left": 37}],
    })),
    "edit_font_shrink": MockResponse(MockToolCall("edit_page", {
        "reply": "已缩小正文标题",
        "operations": [{"type": "modify", "id": "t1", "style": {"fontSize": 16}}],
    })),
    "edit_multi_component": MockResponse(MockToolCall("edit_page", {
        "reply": "已放大标题并下移按钮",
        "operations": [
            {"type": "modify", "id": "title_1", "style": {"fontSize": 32}},
            {"type": "move", "id": "btn_1", "top": 520, "left": 87},
        ],
    })),
    "delete_component": MockResponse(MockToolCall("edit_page", {
        "reply": "已删除图片",
        "operations": [{"type": "delete", "id": "pic_1"}],
    })),
    "delete_button": MockResponse(MockToolCall("edit_page", {
        "reply": "已删除按钮",
        "operations": [{"type": "delete", "id": "btn_1"}],
    })),
    "delete_second_text": MockResponse(MockToolCall("edit_page", {
        "reply": "已删除第二个文本",
        "operations": [{"type": "delete", "id": "t2"}],
    })),
    "layout_center_focus": MockResponse(MockToolCall("edit_page", {
        "reply": "已居中布局",
        "operations": [
            {"type": "move", "id": "t1", "top": 60, "left": 37},
            {"type": "move", "id": "t2", "top": 140, "left": 37},
        ],
    })),
    "layout_vertical_stack": MockResponse(MockToolCall("edit_page", {
        "reply": "已改为纵向堆叠布局",
        "operations": [
            {"type": "move", "id": "t1", "top": 40, "left": 37},
            {"type": "move", "id": "t2", "top": 140, "left": 37},
            {"type": "move", "id": "t3", "top": 240, "left": 37},
        ],
    })),
    # 对抗性：move 超出画布边界 → 验证器报错 → 自动修复（bounds clamp）闭环
    "adv_out_of_bounds_repair": MockResponse(MockToolCall("edit_page", {
        "reply": "把标题移到右下",
        "operations": [{"type": "move", "id": "title_1", "top": 600, "left": 900}],
    })),
}


# 多轮对抗性脚本：模拟「模型犯错 → 系统反馈 → 自省修正」的完整闭环。
# 顺序注入 _invoke_llm（side_effect），响应耗尽即抛错——脚本必须精确覆盖
# 任务的预期轮数，否则评测失败，这本身就是防劣化断言。
_MOCK_MULTI_STEP_SCRIPTS: Dict[str, List[MockResponse]] = {
    # 组件引用无法解析（「大标题」不是 id 也不是 label）→ 反馈有效 ID → 重试成功
    "adv_unknown_ref_self_correct": [
        MockResponse(MockToolCall("edit_page", {
            "reply": "放大主标题",
            "operations": [{"type": "modify", "id": "大标题", "style": {"fontSize": 32}}],
        })),
        MockResponse(MockToolCall("edit_page", {
            "reply": "已放大标题",
            "operations": [{"type": "modify", "id": "title_1", "style": {"fontSize": 32}}],
        })),
    ],
    # edit 阶段首步误调 edit 前先被白名单拒绝（execute 阶段只允许 generate_page）→ 修正重试
    "adv_rejected_tool_self_correct": [
        MockResponse(MockToolCall("edit_page", {
            "reply": "已放大标题",
            "operations": [{"type": "modify", "id": "title_1", "style": {"fontSize": 32}}],
        })),
        MockResponse(MockToolCall("edit_page", {
            "reply": "已放大标题",
            "operations": [{"type": "modify", "id": "title_1", "style": {"fontSize": 32}}],
        })),
    ],
    # 目标组件被锁定 → 动作被跳过、画布无差异 → 反馈后改改未锁定组件
    "adv_locked_component_redirect": [
        MockResponse(MockToolCall("edit_page", {
            "reply": "修改标题",
            "operations": [{"type": "modify", "id": "title_1", "propValue": "新标题"}],
        })),
        MockResponse(MockToolCall("edit_page", {
            "reply": "标题已锁定，已修改副标题",
            "operations": [{"type": "modify", "id": "subtitle_1", "propValue": "新副标题"}],
        })),
    ],
    # 删除不存在的组件 → unresolvedRef 反馈 → 用真实 ID 重试
    "adv_delete_missing_self_correct": [
        MockResponse(MockToolCall("edit_page", {
            "reply": "删除配图",
            "operations": [{"type": "delete", "id": "pic_9"}],
        })),
        MockResponse(MockToolCall("edit_page", {
            "reply": "已删除图片",
            "operations": [{"type": "delete", "id": "pic_1"}],
        })),
    ],
    # planner：discover 阶段误调 confirm_plan 被拒 → 两轮选择 → 方案确认 → 生成
    "adv_planner_self_correct": [
        MockResponse(MockToolCall("confirm_plan", {
            "summary": "读书分享会方案", "details": ["大标题", "时间地点", "报名入口"],
        })),
        MockResponse(MockToolCall("propose_options", {
            "reply": "请选择页面方向",
            "options": [
                {"id": "poster", "title": "宣传海报", "description": "主视觉 + 行动入口"},
                {"id": "form", "title": "报名表", "description": "信息登记"},
            ],
        })),
        MockResponse(MockToolCall("propose_options", {
            "reply": "请选择视觉风格",
            "options": [
                {"id": "bright", "title": "明亮清新", "description": "浅色背景"},
                {"id": "dark", "title": "深色质感", "description": "深色背景"},
            ],
        })),
        MockResponse(MockToolCall("confirm_plan", {
            "summary": "读书分享会宣传海报",
            "details": ["活动标题", "时间地点", "报名入口"],
        })),
        MockResponse(MockToolCall("generate_page", {
            "reply": "页面已生成",
            "canvasStyle": {"width": 375, "height": 667, "backgroundColor": "#ffffff"},
            "components": [
                _text("读书分享会", 32),
                _text("时间：9月20日 地点：多功能厅", 16, fontWeight=400, top=140),
                _button("立即报名"),
            ],
        })),
    ],
}


def _mock_response_for_task(task: EvalTask, state: dict) -> MockResponse:
    """根据任务 id 构造 mock LLM 的单轮 tool_call 响应"""
    if task.get("id", "") in _MOCK_EDIT_SCRIPTS:
        return _MOCK_EDIT_SCRIPTS[task["id"]]
    if (task.get("expected") or {}).get("requireInitialChoice"):
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


def _mock_response_sequence(task: EvalTask, state: dict) -> List[MockResponse]:
    """任务对应的 mock 响应序列：多轮脚本优先，否则包装为单元素序列"""
    multi = _MOCK_MULTI_STEP_SCRIPTS.get(task.get("id", ""))
    if multi:
        return list(multi)
    return [_mock_response_for_task(task, state)]


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
    """把节点 trace 转成 EvalRunResult.steps（供 MAX_STEPS 检查）

    correction 类型（自省修正轮次）不计入工具步数——它们是反馈轮而非工具执行。
    """
    steps = []
    for step in trace or []:
        if isinstance(step, dict) and step.get("tool") and step.get("type") != "correction":
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

            with patch("app.services.ai.agent_nodes.interrupt", side_effect=fake_interrupt), \
                 patch("app.services.ai.agent_nodes._invoke_llm", new=AsyncMock(side_effect=_mock_response_sequence(task, state))):
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

        # 执行类：走 executor，mock LLM 按脚本序列响应（支持多轮对抗性用例）。
        # 画布非空默认 edit 阶段（与真实路由一致）；对抗性任务可用 mockStage 覆盖。
        mock_stage = task.get("mockStage") or ("edit" if task.get("initialCanvas") else "execute")
        state = _build_state(task, stage=mock_stage)
        state["allowed_tools"] = ["generate_page", "edit_page", "finish"]
        state["plan"] = {"summary": task.get("name", ""), "details": ["确定性 mock 回归"]}

        with patch("app.services.ai.agent_nodes._invoke_llm", new=AsyncMock(side_effect=_mock_response_sequence(task, state))):
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

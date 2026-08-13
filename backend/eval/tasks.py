"""Agent Eval 任务集（golden set）

每条任务包含：用户输入、画布初始状态、期望结果标准。
用于：
  - mock 模式：脚本化 LLM 决策，确定性回归工具/循环/多 Agent 逻辑
  - live 模式：真实 LLM 生成，量化质量（组件覆盖、验证器通过率、方案产出）

期望标准字段说明：
  - minComponents: 画布组件数下限
  - requireComponents: 必须出现的组件类型集合
  - requireText: 必须出现在某个文本组件 propValue 中的关键字（任一命中即满足）
  - forbidComponents: 禁止出现的组件类型（删除类任务）
  - validatorPass: 完成时画布必须通过 validate_canvas（无 error）
  - maxSteps: 允许的最大工具步数（防失控）
  - planWritten: planner 必须产出方案并写入 state（多 Agent 协作）
  - requiredStage: 任务完成时应到达的阶段
  - selfCorrected: 是否发生过工具被拒后的自省修正
  - maxRepairRounds: 修复轮次上限（防死循环）
"""

from typing import Any, Dict, List, Optional, TypedDict


class EvalExpected(TypedDict, total=False):
    minComponents: int
    requireComponents: List[str]
    requireText: List[str]
    forbidComponents: List[str]
    validatorPass: bool
    maxSteps: int
    planWritten: bool
    requiredStage: str
    selfCorrected: bool
    maxRepairRounds: int
    requireInitialChoice: bool
    titleFontSizeMin: int
    layoutApplied: bool
    centeredLeftTolerance: int


class EvalTask(TypedDict):
    id: str
    name: str
    prompt: str
    canvasStyle: Dict[str, Any]
    initialCanvas: List[Dict[str, Any]]
    expected: EvalExpected


def _text_style(font_size: int = 24, **overrides) -> Dict[str, Any]:
    style = {
        "width": 300, "height": 60, "top": 60, "left": 37,
        "rotate": 0, "opacity": 1, "fontSize": font_size, "fontWeight": 700,
        "lineHeight": "", "letterSpacing": 0, "textAlign": "center",
        "color": "#333333", "backgroundColor": "", "borderColor": "",
        "borderWidth": 0, "borderStyle": "solid", "borderRadius": "", "padding": 4,
    }
    style.update(overrides)
    return style


def _button_style(**overrides) -> Dict[str, Any]:
    style = {
        "width": 200, "height": 48, "top": 400, "left": 87,
        "rotate": 0, "opacity": 1, "fontSize": 18, "fontWeight": 400,
        "lineHeight": "", "letterSpacing": 0, "textAlign": "center",
        "color": "#ffffff", "backgroundColor": "#409eff", "borderColor": "",
        "borderWidth": 0, "borderStyle": "solid", "borderRadius": "8", "padding": 4,
    }
    style.update(overrides)
    return style


def _component(
    component: str,
    label: str,
    prop_value: Any,
    style: Dict[str, Any],
    z_index: int = 1,
    cid: str = "",
) -> Dict[str, Any]:
    return {
        "id": cid or component.lower() + "_1",
        "component": component,
        "label": label,
        "icon": "",
        "propValue": prop_value,
        "style": style,
        "parentId": None,
        "slot": "default",
        "zIndex": z_index,
        "animations": [],
        "events": {},
        "groupStyle": {},
        "isLock": False,
        "collapseName": "style",
        "linkage": {"duration": 0, "data": []},
    }


DEFAULT_CANVAS_STYLE = {
    "width": 375,
    "height": 667,
    "scale": 100,
    "color": "#000000",
    "opacity": 100,
    "backgroundColor": "#ffffff",
    "fontSize": 14,
}


EVAL_TASKS: List[EvalTask] = [
    {
        "id": "poster_dance_recruit",
        "name": "街舞社招新海报",
        "prompt": "做一个街舞社招新海报，标题突出，包含时间地点和报名按钮",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText", "VButton"],
            "requireText": ["街舞", "招新"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "poster_activity_promo",
        "name": "活动宣传海报",
        "prompt": "做一个校园音乐节宣传海报，包含活动名称、时间和地点",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText"],
            "requireText": ["音乐节", "时间", "地点"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "form_registration",
        "name": "社团报名表",
        "prompt": "做一个社团报名表页面，包含姓名、联系方式字段和一个提交按钮",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText", "VButton"],
            "requireText": ["报名", "姓名", "联系"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "edit_title_font",
        "name": "修改标题字号",
        "prompt": "把页面上的主标题字号改大一些，突出一点",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
            _component("VButton", "报名按钮", "立即报名", _button_style(), z_index=2, cid="btn_1"),
        ],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText"],
            "requireText": [],
            "titleFontSizeMin": 28,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 8,
        },
    },
    {
        "id": "delete_component",
        "name": "删除图片",
        "prompt": "把页面上的图片删掉",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "标题", "页面标题", _text_style(font_size=24), z_index=1, cid="title_1"),
            _component("Picture", "配图", {"url": "https://placehold.co/300x200", "flip": {"horizontal": False, "vertical": False}}, {
                "width": 300, "height": 200, "top": 200, "left": 37,
                "rotate": 0, "opacity": 1, "fontSize": 14, "fontWeight": 400,
                "lineHeight": "", "letterSpacing": 0, "textAlign": "center",
                "color": "#333333", "backgroundColor": "", "borderColor": "",
                "borderWidth": 0, "borderStyle": "solid", "borderRadius": "", "padding": 4,
            }, z_index=2, cid="pic_1"),
        ],
        "expected": {
            "minComponents": 1,
            "forbidComponents": ["Picture"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "layout_center_focus",
        "name": "居中聚焦布局",
        "prompt": "用居中聚焦的布局重新排一下页面",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "标题", "活动标题", _text_style(font_size=24, top=0, left=0), z_index=1, cid="t1"),
            _component("VText", "正文", "详情说明", _text_style(font_size=16, fontWeight=400, top=0, left=0), z_index=2, cid="t2"),
        ],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText"],
            "layoutApplied": True,
            "centeredLeftTolerance": 30,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 8,
        },
    },
    {
        "id": "empty_canvas_vague",
        "name": "空画布模糊需求（应询问方向）",
        "prompt": "做个海报",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "requireInitialChoice": True,
            "minComponents": 0,
            "maxSteps": 3,
        },
    },
]


def get_eval_tasks() -> List[EvalTask]:
    """获取全部任务集"""
    return EVAL_TASKS


def get_eval_task(task_id: str) -> Optional[EvalTask]:
    """按 id 获取任务"""
    return next((task for task in EVAL_TASKS if task["id"] == task_id), None)

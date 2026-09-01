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


class EvalTask(TypedDict, total=False):
    id: str
    name: str
    prompt: str
    canvasStyle: Dict[str, Any]
    initialCanvas: List[Dict[str, Any]]
    expected: EvalExpected
    # mock 运行提示：强制 executor 起始阶段（默认按画布是否有内容推断）。
    # 用于对抗性任务，如模拟「execute 阶段误调 edit 工具被白名单拒绝」。
    mockStage: str


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


def _picture_style(**overrides) -> Dict[str, Any]:
    style = {
        "width": 300, "height": 200, "top": 200, "left": 37,
        "rotate": 0, "opacity": 1, "fontSize": 14, "fontWeight": 400,
        "lineHeight": "", "letterSpacing": 0, "textAlign": "center",
        "color": "#333333", "backgroundColor": "", "borderColor": "",
        "borderWidth": 0, "borderStyle": "solid", "borderRadius": "", "padding": 4,
    }
    style.update(overrides)
    return style


def _picture(cid: str = "pic_1", z_index: int = 2) -> Dict[str, Any]:
    return _component(
        "Picture", "配图",
        {"url": "https://placehold.co/300x200", "flip": {"horizontal": False, "vertical": False}},
        _picture_style(),
        z_index=z_index,
        cid=cid,
    )


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

    # ==================== 生成类扩展 ====================

    {
        "id": "poster_lecture",
        "name": "学术讲座海报",
        "prompt": "做一个学术讲座宣传海报，主题是人工智能前沿讲座，包含主讲人和时间地点",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText"],
            "requireText": ["讲座"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "poster_job_fair",
        "name": "双选会海报",
        "prompt": "做一个秋季双选会海报，包含时间地点和投递简历入口",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText", "VButton"],
            "requireText": ["双选会"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "poster_movie_night",
        "name": "露天电影海报",
        "prompt": "做一个露天电影之夜海报，包含放映时间和地点",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText"],
            "requireText": ["电影"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "poster_sports_meet",
        "name": "运动会海报",
        "prompt": "做一个校运动会海报，包含时间地点和报名参赛按钮",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText", "VButton"],
            "requireText": ["运动会", "报名"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "form_questionnaire",
        "name": "满意度问卷页",
        "prompt": "做一个校园服务满意度问卷页面，包含说明和提交按钮",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText", "VButton"],
            "requireText": ["问卷"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "form_vote",
        "name": "投票页",
        "prompt": "做一个社团最佳节目投票页面，包含说明和立即投票按钮",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText", "VButton"],
            "requireText": ["投票"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "page_club_intro",
        "name": "社团介绍页",
        "prompt": "做一个动漫社团的介绍页面，包含社团名称和活动安排",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText"],
            "requireText": ["社团"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "page_lost_found",
        "name": "失物招领页",
        "prompt": "做一个失物招领页面，包含标题和领取说明",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText"],
            "requireText": ["失物招领"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },
    {
        "id": "page_notice",
        "name": "通知公告页",
        "prompt": "做一个国庆放假通知页面，包含标题和放假时间",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText"],
            "requireText": ["通知"],
            "validatorPass": True,
            "planWritten": True,
            "requiredStage": "edit",
            "maxSteps": 14,
        },
    },

    # ==================== 编辑类扩展 ====================

    {
        "id": "edit_button_text",
        "name": "修改按钮文案",
        "prompt": "把报名按钮的文字改成「立即参与」",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
            _component("VButton", "报名按钮", "立即报名", _button_style(), z_index=2, cid="btn_1"),
        ],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VButton"],
            "requireText": ["立即参与"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "edit_text_color",
        "name": "修改标题颜色",
        "prompt": "把主标题的颜色改成蓝色",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
        ],
        "expected": {
            "minComponents": 1,
            "requireComponents": ["VText"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "edit_move_component",
        "name": "移动标题到底部",
        "prompt": "把主标题移动到页面底部",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
        ],
        "expected": {
            "minComponents": 1,
            "requireComponents": ["VText"],
            "layoutApplied": True,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "edit_font_shrink",
        "name": "缩小标题字号",
        "prompt": "把标题字号缩小一点，低调一些",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="t1"),
        ],
        "expected": {
            "minComponents": 1,
            "requireComponents": ["VText"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "edit_multi_component",
        "name": "多组件组合编辑",
        "prompt": "标题字号放大突出一点，按钮移到页面更靠下的位置",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
            _component("VButton", "报名按钮", "立即报名", _button_style(), z_index=2, cid="btn_1"),
        ],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText", "VButton"],
            "titleFontSizeMin": 28,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },

    # ==================== 删除类扩展 ====================

    {
        "id": "delete_button",
        "name": "删除按钮",
        "prompt": "把页面上的报名按钮删掉",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
            _component("VButton", "报名按钮", "立即报名", _button_style(), z_index=2, cid="btn_1"),
        ],
        "expected": {
            "minComponents": 1,
            "forbidComponents": ["VButton"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "delete_second_text",
        "name": "删除指定文本",
        "prompt": "把页面上的第二个文本组件删掉",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "活动标题", _text_style(font_size=24), z_index=1, cid="t1"),
            _component("VText", "副标题", "活动副标题", _text_style(font_size=16, fontWeight=400, top=140), z_index=2, cid="t2"),
            _component("VText", "正文", "活动详情说明", _text_style(font_size=14, fontWeight=400, top=220), z_index=3, cid="t3"),
        ],
        "expected": {
            "minComponents": 2,
            "requireComponents": ["VText"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },

    # ==================== 布局类扩展 ====================

    {
        "id": "layout_vertical_stack",
        "name": "纵向堆叠布局",
        "prompt": "把页面上的三个组件纵向堆叠排列，间距均匀",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "标题", "活动标题", _text_style(font_size=24, top=0, left=0), z_index=1, cid="t1"),
            _component("VText", "正文", "详情说明", _text_style(font_size=16, fontWeight=400, top=0, left=0), z_index=2, cid="t2"),
            _component("VText", "附注", "更多说明", _text_style(font_size=14, fontWeight=400, top=0, left=0), z_index=3, cid="t3"),
        ],
        "expected": {
            "minComponents": 3,
            "requireComponents": ["VText"],
            "layoutApplied": True,
            "centeredLeftTolerance": 30,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 8,
        },
    },

    # ==================== 交互类扩展 ====================

    {
        "id": "empty_canvas_style_choice",
        "name": "空画布风格模糊（应询问方向）",
        "prompt": "帮我做一个好看的海报",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "requireInitialChoice": True,
            "minComponents": 0,
            "maxSteps": 3,
        },
    },

    # ==================== 对抗性用例（错误 → 反馈 → 自省修正闭环） ====================

    {
        "id": "adv_out_of_bounds_repair",
        "name": "越界移动自动修复",
        "prompt": "把标题移到画面右下角，越出去一点也没关系",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
        ],
        "expected": {
            "minComponents": 1,
            "validatorPass": True,
            "maxRepairRounds": 1,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "adv_unknown_ref_self_correct",
        "name": "未知组件引用自省修正",
        "prompt": "把主标题字号放大",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
            _component("VButton", "报名按钮", "立即报名", _button_style(), z_index=2, cid="btn_1"),
        ],
        "expected": {
            "minComponents": 2,
            "selfCorrected": True,
            "titleFontSizeMin": 28,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "adv_rejected_tool_self_correct",
        "name": "阶段白名单拒绝后修正",
        "prompt": "把主标题字号放大",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "mockStage": "execute",
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
        ],
        "expected": {
            "minComponents": 1,
            "selfCorrected": True,
            "titleFontSizeMin": 28,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "adv_locked_component_redirect",
        "name": "锁定组件跳过重定向",
        "prompt": "把页面标题文案改成新标题",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            {**_component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"), "isLock": True},
            _component("VText", "副标题", "欢迎加入", _text_style(font_size=16, fontWeight=400, top=140), z_index=2, cid="subtitle_1"),
        ],
        "expected": {
            "minComponents": 2,
            "selfCorrected": True,
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "adv_delete_missing_self_correct",
        "name": "删除不存在组件后修正",
        "prompt": "把页面上的图片删掉",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [
            _component("VText", "主标题", "招新海报", _text_style(font_size=24), z_index=1, cid="title_1"),
            _picture(cid="pic_1"),
        ],
        "expected": {
            "minComponents": 1,
            "selfCorrected": True,
            "forbidComponents": ["Picture"],
            "validatorPass": True,
            "requiredStage": "edit",
            "maxSteps": 6,
        },
    },
    {
        "id": "adv_planner_self_correct",
        "name": "planner 阶段误调工具后修正",
        "prompt": "做一个读书分享会宣传海报，包含时间地点和报名入口",
        "canvasStyle": {**DEFAULT_CANVAS_STYLE},
        "initialCanvas": [],
        "expected": {
            "requireInitialChoice": True,
            "planWritten": True,
            "minComponents": 0,
            "maxSteps": 6,
        },
    },
]


def get_eval_tasks() -> List[EvalTask]:
    """获取全部任务集"""
    return EVAL_TASKS


def get_eval_task(task_id: str) -> Optional[EvalTask]:
    """按 id 获取任务"""
    return next((task for task in EVAL_TASKS if task["id"] == task_id), None)

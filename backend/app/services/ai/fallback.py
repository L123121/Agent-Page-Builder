"""本地降级 Agent — 模型不可用时保证选择、确认和画布生成链路可用。"""

import re
from copy import deepcopy

from .component_utils import auto_layout_components, normalize_component
from .schemas import AgentState
from .validator import repair_canvas, validate_canvas


def run_fallback_agent(state: AgentState, reason: str = "") -> dict:
    stage = state["stage"]
    if stage == "discover":
        result = _discover_options(state)
    elif stage == "design":
        result = _design_options(state)
    elif stage == "plan":
        result = _confirm_plan(state)
    elif stage == "execute":
        result = _generate_page(state)
    else:
        result = _edit_page(state)
    result.setdefault("trace", []).append({
        "step": 0,
        "tool": "local_fallback",
        "reason": _safe_reason(reason),
    })
    return result


def _discover_options(state: AgentState) -> dict:
    requirement = _requirement_text(state)
    if "报名" in requirement or "表单" in requirement:
        options = [
            _option("form-card", "卡片式报名页", "顶部活动介绍，下方分区展示报名字段和提交入口", "推荐"),
            _option("form-table", "信息登记表", "强调字段完整性，采用规整表格式信息布局"),
            _option("form-poster", "宣传海报 + 报名", "先展示活动主视觉，再突出报名时间和入口"),
        ]
    else:
        options = [
            _option("hero-poster", "主视觉宣传海报", "大标题配合醒目视觉中心，适合招新和活动宣传", "推荐"),
            _option("info-poster", "信息卡片海报", "重点突出时间、地点和活动内容，阅读路径清晰"),
            _option("poster-action", "海报 + 行动入口", "在宣传信息下增加报名或了解详情按钮"),
        ]
    return {
        "reply": "先选择你希望采用的页面方向：",
        "actions": [],
        "options": options,
        "nextStage": "design",
    }


def _design_options(state: AgentState) -> dict:
    return {
        "reply": "再选择一个视觉风格，我会据此整理最终方案：",
        "actions": [],
        "options": [
            _option("vivid", "活力潮流", "深色背景、明亮强调色和较强视觉层次", "推荐"),
            _option("fresh", "清新明亮", "浅色背景、自然配色和轻量装饰元素"),
            _option("minimal", "简约现代", "克制配色、大留白和清晰的信息层级"),
        ],
        "nextStage": "plan",
    }


def _confirm_plan(state: AgentState) -> dict:
    requirement = _requirement_text(state)
    return {
        "reply": "方案已经整理完成，请确认后生成。",
        "actions": [],
        "plan": {
            "summary": f"围绕“{_title_from_requirement(requirement)}”生成一版结构清晰的活动页面",
            "details": [
                "保留明确的标题、时间地点和核心说明",
                "按照已选择的页面方向组织信息层级",
                "使用已选择的视觉风格统一颜色与装饰",
                "生成后执行越界、内容和对比度验证",
            ],
        },
        "nextStage": "confirm",
    }


def _generate_page(state: AgentState) -> dict:
    requirement = _requirement_text(state)
    width = state["canvas_width"]
    height = state["canvas_height"]
    palette = _palette(requirement)
    title = _title_from_requirement(requirement)
    detail = _detail_from_requirement(requirement, title)
    content_width = max(240, int(width * 0.76))
    content_left = max(20, int((width - content_width) / 2))
    title_size = max(28, min(52, int(width * 0.045)))
    components = [
        _component("RectShape", "页面背景", "&nbsp;", {
            "width": width, "height": height, "top": 0, "left": 0,
            "backgroundColor": palette["background"], "borderWidth": 0,
        }, 1),
        _component("CircleShape", "装饰圆", "&nbsp;", {
            "width": max(100, int(width * 0.18)), "height": max(100, int(width * 0.18)),
            "top": -30, "left": width - max(130, int(width * 0.2)),
            "backgroundColor": palette["accent"], "opacity": 0.22, "borderWidth": 0,
        }, 2),
        _component("VText", "主标题", title, {
            "width": content_width, "height": max(70, int(title_size * 1.7)),
            "top": max(50, int(height * 0.09)), "left": content_left,
            "fontSize": title_size, "fontWeight": 700, "textAlign": "left",
            "color": palette["title"], "backgroundColor": "", "padding": 4,
        }, 20),
        _component("VText", "活动说明", detail, {
            "width": content_width, "height": max(90, int(height * 0.14)),
            "top": max(145, int(height * 0.25)), "left": content_left,
            "fontSize": max(16, min(24, int(width * 0.02))), "fontWeight": 400,
            "textAlign": "left", "color": palette["text"], "backgroundColor": "", "padding": 4,
        }, 20),
        _component("RectShape", "信息卡片", "&nbsp;", {
            "width": content_width, "height": max(150, int(height * 0.25)),
            "top": max(270, int(height * 0.46)), "left": content_left,
            "backgroundColor": palette["surface"], "borderRadius": "20px", "borderWidth": 0,
        }, 8),
        _component("VText", "活动信息", _information_text(requirement), {
            "width": content_width - 48, "height": max(95, int(height * 0.16)),
            "top": max(295, int(height * 0.5)), "left": content_left + 24,
            "fontSize": max(15, min(22, int(width * 0.018))), "fontWeight": 500,
            "textAlign": "left", "color": palette["surfaceText"], "backgroundColor": "", "padding": 4,
        }, 20),
        _component("VButton", "行动按钮", "立即了解", {
            "width": max(150, int(width * 0.22)), "height": 52,
            "top": min(height - 82, max(490, int(height * 0.78))), "left": content_left,
            "fontSize": 18, "fontWeight": 600, "color": "#ffffff",
            "backgroundColor": palette["button"], "borderRadius": "12px", "borderWidth": 0,
        }, 25),
    ]
    components = auto_layout_components(components, width, height)
    canvas_style = {
        **deepcopy(state["canvas_style"]),
        "width": width,
        "height": height,
        "scale": 100,
        "backgroundColor": palette["background"],
    }
    report = validate_canvas(components, width, height, canvas_style)
    components, fixes = repair_canvas(components, width, height, canvas_style, report["issues"], True)
    report = validate_canvas(components, width, height, canvas_style)
    return {
        "reply": "页面已由本地设计引擎生成并完成基础验证。",
        "actions": [{"type": "generate", "components": components, "canvasStyle": canvas_style}],
        "nextStage": "edit",
        "validation": report,
        "trace": [{"step": 1, "tool": "local_generate_page", "autoFixes": fixes, "validation": report}],
    }


def _edit_page(state: AgentState) -> dict:
    prompt = state["prompt"]
    targets = _edit_targets(state)
    actions: list[dict] = []
    color = _requested_color(prompt)
    if color:
        actions.extend({"type": "modify", "id": component["id"], "style": {"color": color}} for component in targets)
    title_match = re.search(r"标题.*?(?:改成|修改为|换成)[「『\"“]?([^」』\"”]+)", prompt)
    if title_match and not color:
        title = title_match.group(1).strip(" ，。")
        if title and targets:
            actions.append({"type": "modify", "id": targets[0]["id"], "propValue": title})
    if "大一点" in prompt or "放大" in prompt:
        for component in targets:
            current_size = component.get("style", {}).get("fontSize", 16)
            actions.append({"type": "modify", "id": component["id"], "style": {"fontSize": int(current_size * 1.2)}})
    if not actions:
        return {
            "reply": "当前模型服务不可用，本地模式暂时无法理解这条复杂修改。你可以尝试“标题改成…、标题改成蓝色、标题放大”。",
            "actions": [],
            "nextStage": "edit",
        }
    return {
        "reply": "已在本地模式下完成修改。",
        "actions": actions,
        "nextStage": "edit",
    }


def _component(component_type: str, label: str, prop_value, style: dict, z_index: int) -> dict:
    return normalize_component({
        "component": component_type,
        "label": label,
        "propValue": prop_value,
        "style": style,
        "zIndex": z_index,
    }, z_index).model_dump()


def _option(option_id: str, title: str, description: str, tag: str = "") -> dict:
    return {"id": option_id, "title": title, "description": description, "tag": tag}


def _requirement_text(state: AgentState) -> str:
    user_messages = [
        str(message.get("content", ""))
        for message in state["messages"]
        if message.get("role") == "user"
    ]
    return "；".join(user_messages) or state["prompt"]


def _title_from_requirement(requirement: str) -> str:
    candidates = [part.strip() for part in re.split(r"[，,。；;\n]", requirement) if part.strip()]
    for candidate in candidates:
        if "我选择" not in candidate and "确认" not in candidate and "修改方案" not in candidate:
            return candidate[:24]
    return "精彩活动"


def _detail_from_requirement(requirement: str, title: str) -> str:
    cleaned = requirement.replace(title, "", 1).strip("，,。；; ")
    return cleaned[:100] or "汇聚热爱，期待与你一起创造精彩。"


def _information_text(requirement: str) -> str:
    time_match = re.search(r"(?:时间|日期)[:：]?\s*([^，,。；;]+)", requirement)
    place_match = re.search(r"(?:地点|地址)[:：]?\s*([^，,。；;]+)", requirement)
    lines = []
    if time_match:
        lines.append(f"时间：{time_match.group(1).strip()}")
    if place_match:
        lines.append(f"地点：{place_match.group(1).strip()}")
    if not lines:
        lines = ["活动信息：请在画布中继续补充时间与地点", "面向对象：欢迎感兴趣的同学参加"]
    return "\n".join(lines)


def _palette(requirement: str) -> dict:
    if "清新" in requirement or "明亮" in requirement:
        return {
            "background": "#ecfdf5", "accent": "#10b981", "title": "#064e3b",
            "text": "#166534", "surface": "#ffffff", "surfaceText": "#14532d", "button": "#047857",
        }
    if "简约" in requirement or "现代" in requirement:
        return {
            "background": "#f8fafc", "accent": "#64748b", "title": "#0f172a",
            "text": "#334155", "surface": "#ffffff", "surfaceText": "#1e293b", "button": "#1d4ed8",
        }
    return {
        "background": "#111827", "accent": "#f97316", "title": "#ffffff",
        "text": "#dbeafe", "surface": "#1f2937", "surfaceText": "#f9fafb", "button": "#2563eb",
    }


def _edit_targets(state: AgentState) -> list[dict]:
    selected = set(state["selected_component_ids"])
    if selected:
        matches = [component for component in state["components"] if component.get("id") in selected and not component.get("isLock")]
        if matches:
            return matches
    title = next((
        component for component in state["components"]
        if component.get("component") == "VText" and component.get("style", {}).get("fontSize", 0) >= 24 and not component.get("isLock")
    ), None)
    return [title] if title else []


def _requested_color(prompt: str) -> str | None:
    colors = {
        "蓝色": "#2563eb", "红色": "#dc2626", "绿色": "#059669", "橙色": "#ea580c",
        "紫色": "#7c3aed", "黑色": "#111827", "白色": "#ffffff",
    }
    return next((value for name, value in colors.items() if name in prompt), None)


def _safe_reason(reason: str) -> str:
    if "401" in reason or "invalid_api_key" in reason.lower() or "incorrect api key" in reason.lower():
        return "AI provider authentication failed; local fallback enabled"
    return "AI provider unavailable; local fallback enabled"

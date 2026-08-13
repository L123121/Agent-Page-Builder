"""确定性画布验证器 — 为 Agent 提供可执行、可复现的质量反馈。"""

import math
import re
from copy import deepcopy

from app.utils.id_generator import generate_id

from .component_utils import auto_layout_components


DECORATIVE_TYPES = {"RectShape", "CircleShape", "LineShape"}
TEXT_TYPES = {"VText", "VButton"}


def validate_canvas(
    components: list[dict],
    canvas_width: int,
    canvas_height: int,
    canvas_style: dict | None = None,
) -> dict:
    issues: list[dict] = []
    canvas_style = canvas_style or {}
    seen_ids: set[str] = set()

    for component in components:
        component_id = str(component.get("id", ""))
        style = component.get("style", {})
        width = _number(style.get("width"), 0)
        height = _number(style.get("height"), 0)
        left = _number(style.get("left"), 0)
        top = _number(style.get("top"), 0)

        if not component_id or component_id in seen_ids:
            issues.append(_issue("duplicate_id", "error", "组件 ID 缺失或重复", [component_id]))
        seen_ids.add(component_id)

        if width <= 0 or height <= 0:
            issues.append(_issue("invalid_size", "error", "组件宽高必须大于 0", [component_id]))
        if left < 0 or top < 0 or left + width > canvas_width or top + height > canvas_height:
            issues.append(_issue("out_of_bounds", "error", "组件超出画布边界", [component_id]))

        if component.get("component") in TEXT_TYPES:
            text = component.get("propValue")
            if not isinstance(text, str) or not text.strip():
                issues.append(_issue("missing_content", "error", "文本或按钮内容为空", [component_id], False))
            elif _has_text_overflow(text, style):
                issues.append(_issue("text_overflow", "warning", "文本可能超出组件高度", [component_id]))
            contrast = _text_contrast(style, canvas_style)
            if contrast is not None and contrast < _required_contrast(style):
                issues.append(_issue("low_contrast", "warning", f"文字对比度不足（{contrast:.2f}:1）", [component_id]))

        if component.get("component") == "Picture":
            prop_value = component.get("propValue")
            image_url = prop_value.get("url") if isinstance(prop_value, dict) else ""
            if not image_url:
                issues.append(_issue("missing_content", "error", "图片地址为空", [component_id], False))

    content_components = [component for component in components if not _is_decorative(component, canvas_width, canvas_height)]
    for index, first in enumerate(content_components):
        for second in content_components[index + 1:]:
            if first.get("parentId") != second.get("parentId"):
                continue
            ratio = _overlap_ratio(first, second)
            if ratio >= 0.35:
                issues.append(_issue(
                    "component_overlap",
                    "warning",
                    f"组件重叠比例过高（{ratio:.0%}）",
                    [str(first.get("id", "")), str(second.get("id", ""))],
                ))

    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "valid": error_count == 0,
        "errorCount": error_count,
        "warningCount": warning_count,
        "issues": issues,
        "summary": f"{error_count} 个错误，{warning_count} 个警告",
    }


def repair_canvas(
    components: list[dict],
    canvas_width: int,
    canvas_height: int,
    canvas_style: dict,
    issues: list[dict],
    allow_reflow: bool,
) -> tuple[list[dict], list[dict]]:
    repaired = deepcopy(components)
    fixes: list[dict] = []
    issue_ids_by_code: dict[str, set[str]] = {}
    for issue in issues:
        if not issue.get("autoFixable", True):
            continue
        issue_ids_by_code.setdefault(issue.get("code", ""), set()).update(issue.get("componentIds", []))
    issue_codes = set(issue_ids_by_code)
    used_ids: set[str] = set()

    for component in repaired:
        component_id = str(component.get("id", ""))
        if not component_id or component_id in used_ids:
            component["id"] = generate_id(8)
            fixes.append({"code": "duplicate_id", "id": component["id"]})
        used_ids.add(component["id"])

        style = component.setdefault("style", {})
        width = min(max(1, int(_number(style.get("width"), 1))), canvas_width)
        height = min(max(1, int(_number(style.get("height"), 1))), canvas_height)
        left = min(max(0, int(_number(style.get("left"), 0))), max(0, canvas_width - width))
        top = min(max(0, int(_number(style.get("top"), 0))), max(0, canvas_height - height))
        if any(component_id in issue_ids_by_code.get(code, set()) for code in ("invalid_size", "out_of_bounds")):
            if (style.get("width"), style.get("height"), style.get("left"), style.get("top")) != (width, height, left, top):
                fixes.append({"code": "bounds", "id": component["id"]})
            style.update({"width": width, "height": height, "left": left, "top": top})

        if component.get("component") in TEXT_TYPES and component_id in issue_ids_by_code.get("text_overflow", set()):
            required_height = _estimated_text_height(str(component.get("propValue", "")), style)
            if required_height > height:
                style["height"] = min(required_height, canvas_height - top)
                fixes.append({"code": "text_overflow", "id": component["id"]})

        if component.get("component") in TEXT_TYPES and component_id in issue_ids_by_code.get("low_contrast", set()):
            background = style.get("backgroundColor") or canvas_style.get("backgroundColor") or "#ffffff"
            style["color"] = "#ffffff" if _relative_luminance(background) < 0.35 else "#111111"
            fixes.append({"code": "low_contrast", "id": component["id"]})

    if allow_reflow and "component_overlap" in issue_codes:
        repaired = auto_layout_components(repaired, canvas_width, canvas_height)
        fixes.append({"code": "component_overlap", "id": "canvas"})

    return repaired, fixes


def issue_key(issue: dict) -> tuple:
    return issue.get("code"), tuple(sorted(issue.get("componentIds", [])))


def _issue(code: str, severity: str, message: str, component_ids: list[str], auto_fixable: bool = True) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "componentIds": component_ids,
        "autoFixable": auto_fixable,
    }


def _number(value, default: float) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _is_decorative(component: dict, canvas_width: int, canvas_height: int) -> bool:
    if component.get("component") in DECORATIVE_TYPES:
        return True
    style = component.get("style", {})
    return (
        component.get("component") == "Picture"
        and _number(style.get("width"), 0) >= canvas_width * 0.8
        and _number(style.get("height"), 0) >= canvas_height * 0.8
    )


def _overlap_ratio(first: dict, second: dict) -> float:
    first_style = first.get("style", {})
    second_style = second.get("style", {})
    left = max(_number(first_style.get("left"), 0), _number(second_style.get("left"), 0))
    top = max(_number(first_style.get("top"), 0), _number(second_style.get("top"), 0))
    right = min(
        _number(first_style.get("left"), 0) + _number(first_style.get("width"), 0),
        _number(second_style.get("left"), 0) + _number(second_style.get("width"), 0),
    )
    bottom = min(
        _number(first_style.get("top"), 0) + _number(first_style.get("height"), 0),
        _number(second_style.get("top"), 0) + _number(second_style.get("height"), 0),
    )
    if right <= left or bottom <= top:
        return 0
    intersection = (right - left) * (bottom - top)
    first_area = max(1, _number(first_style.get("width"), 0) * _number(first_style.get("height"), 0))
    second_area = max(1, _number(second_style.get("width"), 0) * _number(second_style.get("height"), 0))
    return intersection / min(first_area, second_area)


def _has_text_overflow(text: str, style: dict) -> bool:
    return _estimated_text_height(text, style) > _number(style.get("height"), 0) + 2


def _estimated_text_height(text: str, style: dict) -> int:
    font_size = max(8, _number(style.get("fontSize"), 14))
    width = max(font_size, _number(style.get("width"), 100) - _number(style.get("padding"), 0) * 2)
    chars_per_line = max(1, int(width / font_size))
    lines = sum(max(1, math.ceil(len(line) / chars_per_line)) for line in text.splitlines() or [""])
    return int(math.ceil(lines * font_size * 1.45 + _number(style.get("padding"), 0) * 2))


def _text_contrast(style: dict, canvas_style: dict) -> float | None:
    foreground = style.get("color")
    background = style.get("backgroundColor") or canvas_style.get("backgroundColor")
    if not _is_hex_color(foreground) or not _is_hex_color(background):
        return None
    lighter = max(_relative_luminance(foreground), _relative_luminance(background))
    darker = min(_relative_luminance(foreground), _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _required_contrast(style: dict) -> float:
    return 3 if _number(style.get("fontSize"), 14) >= 24 or _number(style.get("fontWeight"), 400) >= 700 else 4.5


def _is_hex_color(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))


def _relative_luminance(color: str) -> float:
    if not _is_hex_color(color):
        return 1
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    converted = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * converted[0] + 0.7152 * converted[1] + 0.0722 * converted[2]

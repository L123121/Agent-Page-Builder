"""组件工具函数 — 规范化、自动布局、画布上下文构建"""

import json
from typing import List

from app.utils.id_generator import generate_id

from .schemas import ComponentData, ComponentStyle


# ==================== 组件类型映射 ====================

COMPONENT_TYPE_MAP = {
    "text": "VText", "button": "VButton", "image": "Picture",
    "picture": "Picture", "rect": "RectShape", "circle": "CircleShape",
    "line": "LineShape", "table": "VTable",
}


def normalize_component(raw: dict, index: int = 0) -> ComponentData:
    """规范化组件数据，兼容 LLM 返回的简化格式和标准格式"""
    cid = raw.get("id", generate_id(8))
    raw_type = raw.get("component") or raw.get("type", "VText")
    component = COMPONENT_TYPE_MAP.get(raw_type.lower(), raw_type)
    is_simple = "style" not in raw and ("x" in raw or "y" in raw)
    text = raw.get("text")
    if text is None:
        text = raw.get("propValue", "")

    if is_simple:
        style = _build_style_from_simple(raw, component, text)
    else:
        style = _merge_style(raw.get("style", {}))

    return ComponentData(
        id=cid,
        component=component,
        label=raw.get("label", "组件"),
        icon=raw.get("icon", ""),
        propValue=_get_prop_value(raw, component, text),
        style=style,
        parentId=raw.get("parentId"),
        slot=raw.get("slot", "default"),
        zIndex=raw.get("zIndex", index + 1),
        animations=raw.get("animations", []),
        events=raw.get("events", {}),
        groupStyle=raw.get("groupStyle", {}),
        isLock=raw.get("isLock", False),
        collapseName=raw.get("collapseName", "style"),
        linkage=raw.get("linkage", {}),
    )


def _build_style_from_simple(raw: dict, component: str, text: str) -> ComponentStyle:
    """从简化格式构建样式"""
    return ComponentStyle(
        width=raw.get("width", 200),
        height=raw.get("height", 28),
        top=raw.get("y", raw.get("top", 0)),
        left=raw.get("x", raw.get("left", 0)),
        rotate=raw.get("rotate", 0),
        opacity=raw.get("opacity", 1),
        fontSize=raw.get("fontSize", 14),
        fontWeight=raw.get("fontWeight", 400),
        lineHeight=raw.get("lineHeight", ""),
        letterSpacing=raw.get("letterSpacing", 0),
        textAlign=raw.get("textAlign", "center"),
        color=raw.get("color", "#333"),
        backgroundColor=raw.get("backgroundColor", raw.get("background", "")),
        borderColor=raw.get("borderColor", ""),
        borderWidth=raw.get("borderWidth", 0),
        borderStyle=raw.get("borderStyle", "solid"),
        borderRadius=raw.get("borderRadius", ""),
        padding=raw.get("padding", 4),
    )


def _merge_style(style_override: dict) -> ComponentStyle:
    """合并样式覆盖"""
    base = ComponentStyle()
    for key, value in style_override.items():
        if hasattr(base, key) and value is not None:
            setattr(base, key, value)
    return base


def _get_prop_value(raw: dict, component: str, text: str):
    """根据组件类型获取 propValue"""
    prop_value = raw.get("propValue")
    if component == "Picture":
        if isinstance(prop_value, dict):
            return {
                "url": prop_value.get("url", ""),
                "flip": prop_value.get("flip", {"horizontal": False, "vertical": False}),
            }
        return {"url": raw.get("url", f"https://placehold.co/{raw.get('width', 200)}x{raw.get('height', 200)}"), "flip": {"horizontal": False, "vertical": False}}
    if component == "VTable":
        if isinstance(prop_value, dict):
            return prop_value
        return {"data": raw.get("data", [["表头"]]), "stripe": True, "thBold": True}
    if component in ("RectShape", "CircleShape"):
        return "&nbsp;"
    if component == "LineShape":
        return ""
    return text if text is not None else ""


# ==================== 画布上下文 ====================

# 画布观察结果最大 token 预算（与 Node 版 promptBuilder 的 OBSERVATION_TOKEN_BUDGET 对齐）
OBSERVATION_TOKEN_BUDGET = 3000
# 项目知识最大 token 预算
PROJECT_KNOWLEDGE_TOKEN_BUDGET = 1000


def estimate_tokens(text) -> int:
    """粗略估算文本 token 数：中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token。

    仅用于上下文预算控制，不追求精确（与 Node 版 estimateTokens 一致）。
    """
    cjk = 0
    other = 0
    for ch in str(text or ""):
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
        else:
            other += 1
    return max(1, cjk + other // 4)


def truncate_by_budget(text: str, budget: int) -> str:
    """按 token 预算截断文本，超限时保留开头并追加省略标记。"""
    if estimate_tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return f"{text[:low]}\n…(上下文过长已截断)"


def summarize_component(c: dict) -> str:
    """单行摘要画布上的一个组件"""
    style = c.get("style", {})
    pv = c.get("propValue", "")
    if isinstance(pv, str):
        pv = pv[:50]
    elif isinstance(pv, dict):
        pv = json.dumps(pv, ensure_ascii=False)[:80]
    return (
        f"- [{c.get('id')}] {c.get('component')} \"{pv}\" "
        f"位置({style.get('left')},{style.get('top')}) "
        f"尺寸{style.get('width')}x{style.get('height')} "
        f"字号{style.get('fontSize')} 颜色{style.get('color')} "
        f"背景{style.get('backgroundColor')} "
        f"层级{c.get('zIndex')} 父级{c.get('parentId')} 锁定{bool(c.get('isLock'))}"
    )


def _build_component_list(components: List[dict], budget: int) -> str:
    """在 token 预算内逐条累积组件摘要，超限时省略剩余组件并提示数量。"""
    lines: List[str] = []
    used = 0
    total = len(components)
    for index, component in enumerate(components):
        line = summarize_component(component)
        cost = estimate_tokens(line) + 1  # +1 换行
        if used + cost > budget and lines:
            remaining = total - index
            lines.append(f"\n…(画布组件过多，已省略 {remaining} 个)")
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


def build_canvas_context(
    components: List[dict],
    canvas_width: int,
    canvas_height: int,
    canvas_style: dict | None = None,
    selected_component_ids: List[str] | None = None,
    viewport: dict | None = None,
    project_knowledge: str = "",
) -> str:
    """构建画布上下文描述（注入到 LLM 的 system message）

    通过 token 预算控制上下文体积：组件列表按 OBSERVATION_TOKEN_BUDGET
    累积截断、项目知识按 PROJECT_KNOWLEDGE_TOKEN_BUDGET 截断，
    避免画布组件过多时单次请求 token 消耗爆炸（撞 TPM 限流）。
    """
    selected_component_ids = selected_component_ids or []
    ctx = f"当前画布: {canvas_width}x{canvas_height}px"
    if canvas_style:
        ctx += f"\n画布样式: {json.dumps(canvas_style, ensure_ascii=False)}"
    if viewport:
        ctx += f"\n当前视口: {json.dumps(viewport, ensure_ascii=False)}"
    if selected_component_ids:
        ctx += f"\n当前选中组件: {', '.join(selected_component_ids)}"
    if project_knowledge:
        ctx += f"\n项目知识: {truncate_by_budget(project_knowledge, PROJECT_KNOWLEDGE_TOKEN_BUDGET)}"
    if components:
        ctx += f"\n画布上已有 {len(components)} 个组件:\n"
        ctx += _build_component_list(components, OBSERVATION_TOKEN_BUDGET)
    else:
        ctx += "\n画布为空。"
    return ctx


# ==================== 自动布局 ====================

MAX_OVERLAP_ITERATIONS = 20
OVERLAP_MARGIN = 8


def auto_layout_components(components: List[dict], canvas_width: int, canvas_height: int) -> List[dict]:
    """只整理内容流组件，保留背景和装饰组件的图层叠加关系。"""
    if not components:
        return components

    decorative_types = {"RectShape", "CircleShape", "LineShape"}

    def is_decorative(comp: dict) -> bool:
        if comp.get("component") in decorative_types:
            return True
        style = comp.get("style", {})
        return (
            comp.get("component") == "Picture"
            and style.get("width", 0) >= canvas_width * 0.8
            and style.get("height", 0) >= canvas_height * 0.8
        )

    sorted_comps = sorted(
        (c for c in components if not is_decorative(c)),
        key=lambda c: (c.get("zIndex", 1), c["style"].get("top", 0)),
    )
    placed: List[dict] = []

    for comp in sorted_comps:
        s = comp["style"]
        cw = s.get("width", 200)
        ch = s.get("height", 28)
        ct = s.get("top", 0)
        cl = s.get("left", 0)

        for _ in range(MAX_OVERLAP_ITERATIONS):
            overlap = False
            for p in placed:
                ps = p["style"]
                pw, ph = ps.get("width", 200), ps.get("height", 28)
                pt, pl = ps.get("top", 0), ps.get("left", 0)

                if (cl < pl + pw + OVERLAP_MARGIN and cl + cw + OVERLAP_MARGIN > pl and
                    ct < pt + ph + OVERLAP_MARGIN and ct + ch + OVERLAP_MARGIN > pt):
                    overlap = True
                    ct = pt + ph + OVERLAP_MARGIN
                    break

            if not overlap:
                break

        comp["style"]["top"] = ct
        comp["style"]["left"] = cl
        placed.append(comp)

    # 保持原始字号和比例，只将组件裁剪回画布范围。
    for c in components:
        s = c["style"]
        s["width"] = min(max(1, s.get("width", 200)), canvas_width)
        s["height"] = min(max(1, s.get("height", 28)), canvas_height)
        if s.get("top", 0) < 0: s["top"] = 0
        if s.get("left", 0) < 0: s["left"] = 0
        if s.get("top", 0) + s.get("height", 28) > canvas_height:
            s["top"] = max(0, canvas_height - s.get("height", 28))
        if s.get("left", 0) + s.get("width", 200) > canvas_width:
            s["left"] = max(0, canvas_width - s.get("width", 200))

    return components

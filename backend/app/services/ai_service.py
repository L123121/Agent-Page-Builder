"""LangGraph AI Agent — 单节点 + 5 工具，LLM 自主决策"""

import time
import json
import logging
from typing import Any, Dict, List, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.config import settings
from app.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# ==================== 系统提示词（复用原 Node.js 版） ====================

SYSTEM_PROMPT = """你是一个低代码页面搭建 AI Agent，为大学社团运营部生成海报和报名表。

## 你的 5 个工具

1. **ask_question** — 开放式提问。当你需要用户提供具体信息时使用（如"海报标题写什么？""需要放哪些信息？"）。用户会自由输入回答。
2. **propose_options** — 选择题。当有 2~3 个明确方案可选时使用（如布局方式、配色风格）。用户点击选择。
3. **confirm_plan** — 方案确认。生成前展示你的设计方案摘要，让用户确认或提出修改意见。
4. **generate_page** — 生成页面。用户确认后执行。
5. **edit_page** — 修改页面。画布已有组件时，用户给出修改指令直接执行。

## 决策逻辑（你是 Agent，自主判断）

**核心原则：永远优先给选项让用户点击，而不是让用户打字。**

分析用户输入，然后**自主选择**最合适的工具：

- 用户描述模糊（"做个海报"）→ propose_options 给出 2~3 种方向（如"招新海报 / 活动宣传 / 报名表"），让用户点选
- 用户选了方向但细节不明 → propose_options 继续给选项（如风格"酷炫 / 文艺 / 简约"）
- 方向明确了 → confirm_plan 展示方案让用户确认
- 用户确认了 → generate_page 生成
- 用户说"直接生成"/"不用确认了" → 跳过确认直接 generate_page
- 画布有组件 + 用户要改 → edit_page 直接执行
- 用户描述非常具体 → 可以跳过选项直接 confirm_plan 或 generate_page
- **只有**当用户意图完全无法猜测、且无法给出合理选项时，才用 ask_question（极少使用）

**禁止连续 ask_question。能猜就猜，能给选项就给选项。**

## 关键规则
- 每次必须调用一个工具，不要只回复文字
- ask_question 一次只问一个问题，不要一次问多个
- propose_options 给 2~3 个选项，description 要具体
- confirm_plan 的 summary 要简洁，details 列出 3~5 个要点
- 生成时严格遵循用户之前表达的所有偏好
- 修改时只改用户提到的部分

## 组件类型
VText(文字) VButton(按钮) Picture(图片,用https://placehold.co/宽x高) RectShape(矩形/色块) CircleShape(圆形) LineShape(直线) VTable(表格)

## 组件格式
{ "id": "8位随机串", "component": "类型", "label": "中文名", "icon": "", "propValue": "内容",
  "style": { "width": 数字, "height": 数字, "top": 数字, "left": 数字, "rotate": 0, "opacity": 1, "fontSize": 数字, "fontWeight": 数字, "lineHeight": "", "letterSpacing": 0, "textAlign": "center", "color": "颜色", "backgroundColor": "背景色", "borderColor": "", "borderWidth": 0, "borderStyle": "solid", "borderRadius": "", "padding": 4 },
  "parentId": null, "slot": "default", "zIndex": 数字,
  "animations": [], "events": {}, "groupStyle": {}, "isLock": false, "collapseName": "style",
  "linkage": { "duration": 0, "data": [{ "id": "", "label": "", "event": "", "style": [{ "key": "", "value": "" }] }] } }

propValue: VText=字符串(\\n换行) VButton=字符串 Picture={"url":"","flip":{"horizontal":false,"vertical":false}} RectShape/CircleShape="&nbsp;" LineShape="" VTable={"data":[["表头"]],"stripe":true,"thBold":true}

## 设计原则
组件不超画布 | 标题24-36px 正文14-16px 说明12px | 配色协调 | zIndex背景1内容10+标题20+ | 间距16-24px"""

# ==================== 5 个工具定义 ====================

ASK_QUESTION_TOOL = [{
    "type": "function",
    "function": {
        "name": "ask_question",
        "description": "向用户提出一个开放式问题（极少使用，优先用 propose_options）。附带 2~3 个快捷回复建议供用户点选。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问用户的问题"},
                "suggestions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2~3 个快捷回复建议，用户可点击直接发送",
                },
            },
            "required": ["question", "suggestions"],
        },
    },
}]

PROPOSE_OPTIONS_TOOL = [{
    "type": "function",
    "function": {
        "name": "propose_options",
        "description": "给出 2~3 种方案供用户点击选择（布局、风格等有明确选项的场景）",
        "parameters": {
            "type": "object",
            "properties": {
                "reply": {"type": "string", "description": "引导语"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "tag": {"type": "string"},
                        },
                        "required": ["id", "title", "description"],
                    },
                },
            },
            "required": ["reply", "options"],
        },
    },
}]

CONFIRM_PLAN_TOOL = [{
    "type": "function",
    "function": {
        "name": "confirm_plan",
        "description": "生成前展示设计方案摘要，让用户确认或提出修改",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "方案一句话概述"},
                "details": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3~5 个设计要点",
                },
            },
            "required": ["summary", "details"],
        },
    },
}]

GENERATE_PAGE_TOOL = [{
    "type": "function",
    "function": {
        "name": "generate_page",
        "description": "生成全新页面（用户确认方案后执行）",
        "parameters": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "canvasStyle": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "backgroundColor": {"type": "string"},
                    },
                    "required": ["width", "height", "backgroundColor"],
                },
                "components": {
                    "type": "array",
                    "description": "页面组件列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "component": {"type": "string", "description": "VText/VButton/Picture/RectShape/CircleShape/LineShape/VTable"},
                            "label": {"type": "string"},
                            "propValue": {"description": "内容"},
                            "style": {
                                "type": "object",
                                "properties": {
                                    "width": {"type": "number"},
                                    "height": {"type": "number"},
                                    "top": {"type": "number"},
                                    "left": {"type": "number"},
                                    "fontSize": {"type": "number"},
                                    "color": {"type": "string"},
                                    "backgroundColor": {"type": "string"},
                                    "textAlign": {"type": "string"},
                                    "fontWeight": {"type": "number"},
                                },
                            },
                        },
                        "required": ["component", "style"],
                    },
                },
            },
            "required": ["reply", "canvasStyle", "components"],
        },
    },
}]

EDIT_PAGE_TOOL = [{
    "type": "function",
    "function": {
        "name": "edit_page",
        "description": "增量修改现有页面",
        "parameters": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["add", "modify", "delete", "move"]},
                            "id": {"type": "string"},
                            "component": {"type": "object"},
                            "style": {"type": "object"},
                            "propValue": {},
                            "top": {"type": "number"},
                            "left": {"type": "number"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["reply", "operations"],
        },
    },
}]

ALL_TOOLS = ASK_QUESTION_TOOL + PROPOSE_OPTIONS_TOOL + CONFIRM_PLAN_TOOL + GENERATE_PAGE_TOOL + EDIT_PAGE_TOOL


# ==================== 辅助函数 ====================

def normalize_component(raw: dict, index: int = 0) -> dict:
    """规范化组件数据，兼容 LLM 返回的简化格式和标准格式"""
    cid = raw.get("id", generate_id(8))
    raw_type = raw.get("component") or raw.get("type", "VText")
    component_map = {
        "text": "VText", "button": "VButton", "image": "Picture",
        "picture": "Picture", "rect": "RectShape", "circle": "CircleShape",
        "line": "LineShape", "table": "VTable",
    }
    component = component_map.get(raw_type.lower(), raw_type)
    is_simple = "style" not in raw and ("x" in raw or "y" in raw)

    if is_simple:
        text = raw.get("text") or raw.get("propValue", "")
        if component == "Picture":
            prop_value = {"url": raw.get("url", f"https://placehold.co/{raw.get('width', 200)}x{raw.get('height', 200)}"), "flip": {"horizontal": False, "vertical": False}}
        elif component == "VTable":
            prop_value = {"data": raw.get("data", [["表头"]]), "stripe": True, "thBold": True}
        elif component in ("RectShape", "CircleShape"):
            prop_value = "&nbsp;"
        elif component == "LineShape":
            prop_value = ""
        else:
            prop_value = text or ""
        style = {
            "width": raw.get("width", 200), "height": raw.get("height", 28),
            "top": raw.get("y", raw.get("top", 0)), "left": raw.get("x", raw.get("left", 0)),
            "rotate": raw.get("rotate", 0), "opacity": raw.get("opacity", 1),
            "fontSize": raw.get("fontSize", 14), "fontWeight": raw.get("fontWeight", 400),
            "lineHeight": raw.get("lineHeight", ""), "letterSpacing": raw.get("letterSpacing", 0),
            "textAlign": raw.get("textAlign", "center"), "color": raw.get("color", "#333"),
            "backgroundColor": raw.get("backgroundColor", raw.get("background", "")),
            "borderColor": raw.get("borderColor", ""), "borderWidth": raw.get("borderWidth", 0),
            "borderStyle": raw.get("borderStyle", "solid"), "borderRadius": raw.get("borderRadius", ""),
            "padding": raw.get("padding", 4),
        }
    else:
        prop_value = raw.get("propValue", "")
        style = {
            "width": 200, "height": 28, "top": 0, "left": 0,
            "rotate": 0, "opacity": 1, "fontSize": 14, "fontWeight": 400,
            "lineHeight": "", "letterSpacing": 0, "textAlign": "left",
            "color": "#333", "backgroundColor": "", "borderColor": "",
            "borderWidth": 0, "borderStyle": "solid", "borderRadius": "", "padding": 0,
        }
        style.update(raw.get("style", {}))

    return {
        "id": cid, "component": component, "label": raw.get("label", "组件"),
        "icon": raw.get("icon", ""), "propValue": prop_value, "style": style,
        "parentId": None, "slot": "default", "zIndex": raw.get("zIndex", index + 1),
        "animations": [], "events": {}, "groupStyle": {}, "isLock": False,
        "collapseName": "style",
        "linkage": {"duration": 0, "data": [{"id": "", "label": "", "event": "", "style": [{"key": "", "value": ""}]}]},
    }


def summarize_component(c: dict) -> str:
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
        f"背景{style.get('backgroundColor')}"
    )


def build_canvas_context(components: list, canvas_width: int, canvas_height: int) -> str:
    ctx = f"当前画布: {canvas_width}x{canvas_height}px"
    if components:
        ctx += f"\n画布上已有 {len(components)} 个组件:\n"
        ctx += "\n".join(summarize_component(c) for c in components)
    else:
        ctx += "\n画布为空。"
    return ctx


def auto_layout_components(components: list, canvas_width: int, canvas_height: int) -> list:
    """检测组件重叠并自动调整位置，确保所有组件在画布内且不重叠"""
    if not components:
        return components

    margin = 8

    # 第一遍：按 zIndex 排序，解决重叠
    sorted_comps = sorted(components, key=lambda c: (c.get("zIndex", 1), c["style"].get("top", 0)))
    placed: list = []

    for comp in sorted_comps:
        s = comp["style"]
        cw = s.get("width", 200)
        ch = s.get("height", 28)
        ct = s.get("top", 0)
        cl = s.get("left", 0)

        for _ in range(20):
            overlap = False
            for p in placed:
                ps = p["style"]
                pw, ph = ps.get("width", 200), ps.get("height", 28)
                pt, pl = ps.get("top", 0), ps.get("left", 0)

                if (cl < pl + pw + margin and cl + cw + margin > pl and
                    ct < pt + ph + margin and ct + ch + margin > pt):
                    overlap = True
                    ct = pt + ph + margin
                    break

            if not overlap:
                break

        comp["style"]["top"] = ct
        comp["style"]["left"] = cl
        placed.append(comp)

    # 第二遍：检测是否有组件超出画布，整体缩放
    max_bottom = max((c["style"].get("top", 0) + c["style"].get("height", 28)) for c in components)
    if max_bottom > canvas_height:
        # 计算缩放比例，保留 10% 边距
        scale = (canvas_height * 0.9) / max_bottom
        for c in components:
            s = c["style"]
            s["top"] = int(s.get("top", 0) * scale)
            s["left"] = int(s.get("left", 0) * scale)
            s["width"] = max(20, int(s.get("width", 200) * scale))
            s["height"] = max(10, int(s.get("height", 28) * scale))
            s["fontSize"] = max(8, int(s.get("fontSize", 14) * scale))

    # 第三遍：确保所有组件在画布内
    for c in components:
        s = c["style"]
        if s.get("top", 0) < 0: s["top"] = 0
        if s.get("left", 0) < 0: s["left"] = 0
        if s.get("top", 0) + s.get("height", 28) > canvas_height:
            s["top"] = max(0, canvas_height - s.get("height", 28))
        if s.get("left", 0) + s.get("width", 200) > canvas_width:
            s["left"] = max(0, canvas_width - s.get("width", 200))

    return components


# ==================== LangGraph Agent — 单节点 ====================

class AgentState(TypedDict):
    messages: List[Dict[str, Any]]
    components: List[Dict[str, Any]]
    canvas_style: Dict[str, Any]
    canvas_width: int
    canvas_height: int
    result: Dict[str, Any]


def call_llm(state: AgentState) -> Dict[str, Any]:
    """调用 LLM，带全部 5 个工具，LLM 自主选择"""
    llm = ChatOpenAI(
        model=settings.AI_MODEL,
        api_key=settings.AI_API_KEY,
        base_url=settings.AI_BASE_URL,
        temperature=0.7,
        max_tokens=4096,
    )

    cw = state["canvas_width"]
    ch = state["canvas_height"]
    canvas_ctx = build_canvas_context(state["components"], cw, ch)

    # 构建消息：系统提示词 + 历史 + 画布上下文
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(state["messages"])

    # 将画布上下文拼接到最后一条 user 消息
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += f"\n\n【画布状态】\n{canvas_ctx}"
    else:
        messages.append({"role": "user", "content": f"请继续。\n\n【画布状态】\n{canvas_ctx}"})

    # 重试逻辑
    last_error = None
    for attempt in range(3):
        try:
            response = llm.invoke(messages, tools=ALL_TOOLS, tool_choice="required")
            return {"result": process_tool_response(response, state)}
        except Exception as e:
            last_error = e
            logger.warning(f"[AI] LLM call failed (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # 指数退避: 1s, 2s

    logger.error(f"[AI] LLM call failed after 3 retries: {last_error}")
    return {"result": {"reply": f"AI 服务异常，请稍后重试: {str(last_error)}", "actions": []}}


def process_tool_response(response, state: AgentState) -> dict:
    """解析 LLM 工具调用结果（支持多个 tool_call 合并）"""
    result: dict = {"reply": "", "actions": []}

    if not getattr(response, "tool_calls", None):
        return {"reply": response.content or "抱歉，我没有理解你的需求", "actions": []}

    seen_reply = False  # 只让第一个非空 reply 覆盖默认值

    for tc in response.tool_calls:
        args = tc.get("args", {}) if isinstance(tc, dict) else tc.args
        name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")

        if name == "ask_question":
            result["question"] = args.get("question", "")
            if not seen_reply:
                result["reply"] = args.get("question", "")
                seen_reply = True
            result["suggestions"] = args.get("suggestions", [])

        elif name == "propose_options":
            if not seen_reply:
                result["reply"] = args.get("reply", "")
                seen_reply = True
            result["options"] = [
                {"id": opt.get("id", generate_id(6)), "title": opt.get("title", "方案"),
                 "description": opt.get("description", ""), "tag": opt.get("tag", "")}
                for opt in args.get("options", [])
            ]

        elif name == "confirm_plan":
            if not seen_reply:
                result["reply"] = args.get("summary", "")
                seen_reply = True
            result["plan"] = {"summary": args.get("summary", ""), "details": args.get("details", [])}

        elif name == "generate_page":
            cs = args.get("canvasStyle", {})
            cw = cs.get("width", state["canvas_width"])
            ch = cs.get("height", state["canvas_height"])
            comps = [normalize_component(c, i) for i, c in enumerate(args.get("components", []))]
            comps = auto_layout_components(comps, cw, ch)
            if not seen_reply:
                result["reply"] = args.get("reply", "页面已生成")
                seen_reply = True
            result["actions"].append({
                "type": "generate",
                "components": comps,
                "canvasStyle": {
                    "width": cw, "height": ch,
                    "scale": 100, "color": cs.get("color", "#000"),
                    "opacity": cs.get("opacity", 100),
                    "backgroundColor": cs.get("backgroundColor", "#ffffff"),
                    "fontSize": cs.get("fontSize", 14),
                },
            })

        elif name == "edit_page":
            if not seen_reply:
                result["reply"] = args.get("reply", "已修改")
                seen_reply = True
            existing_ids = {c["id"] for c in state.get("components", [])}
            max_z = max(
                (c.get("zIndex", 1) for c in state.get("components", [])),
                default=0
            )
            add_index = 0
            for op in args.get("operations", []):
                op_type = op.get("type")
                if op_type == "add" and op.get("component"):
                    result["actions"].append({
                        "type": "add",
                        "component": normalize_component(op["component"], max_z + add_index),
                    })
                    add_index += 1
                elif op_type == "modify" and op.get("id"):
                    action = {"type": "modify", "id": op["id"]}
                    if op.get("style"): action["style"] = op["style"]
                    if op.get("propValue"): action["propValue"] = op["propValue"]
                    result["actions"].append(action)
                elif op_type == "delete" and op.get("id"):
                    result["actions"].append({"type": "delete", "id": op["id"]})
                elif op_type == "move" and op.get("id"):
                    result["actions"].append({"type": "move", "id": op["id"], "top": op.get("top"), "left": op.get("left")})

    return result


# ==================== 构建 LangGraph ====================

workflow = StateGraph(AgentState)
workflow.add_node("agent", call_llm)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)
agent_graph = workflow.compile()


# ==================== 公开接口 ====================

async def run_agent(
    prompt: str,
    history: List[Dict[str, str]] | None = None,
    components: List[Dict[str, Any]] | None = None,
    canvas_style: Dict[str, Any] | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
) -> Dict[str, Any]:
    """运行 AI Agent（单节点 + 5 工具，LLM 自主决策）"""

    if not settings.AI_API_KEY:
        return {"reply": "AI 服务未配置，请设置 AI_API_KEY", "actions": []}

    history = history or []
    components = components or []
    cw = canvas_width or (canvas_style.get("width") if canvas_style else None) or 375
    ch = canvas_height or (canvas_style.get("height") if canvas_style else None) or 667

    messages = list(history)
    messages.append({"role": "user", "content": prompt})

    initial_state: AgentState = {
        "messages": messages,
        "components": components,
        "canvas_style": canvas_style or {},
        "canvas_width": cw,
        "canvas_height": ch,
        "result": {"reply": "", "actions": []},
    }

    try:
        result = await agent_graph.ainvoke(initial_state)
        return result.get("result", {"reply": "", "actions": []})
    except Exception as e:
        logger.error(f"[AI] Agent failed: {e}")
        return {"reply": f"AI 处理失败: {str(e)}", "actions": []}
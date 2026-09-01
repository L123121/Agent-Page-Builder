"""工具响应处理 — 解析 LLM 工具调用并转为可执行动作。

三条容错边界（全部走「反馈让模型自纠」而非静默丢弃或直接报错）：
- rejectedTools：调用了当前阶段白名单外的工具；
- noToolCall：没有调用任何工具（直接输出文本）；
- unresolvedRefs：edit_page 引用了画布上不存在的组件。

组件引用解析只接受精确 ID 或精确 label（大小写不敏感）——画布上下文
中两者都已显式列出，模型照抄即可。子串/语义关键词等模糊匹配已移除：
模糊匹配把「模型引用错误」悄悄变成「改错组件」，比失败更难排查。
引用失败会作为 unresolvedRefs 反馈给模型，附带有效组件清单让它重试。
"""

from app.utils.id_generator import generate_id

from .component_utils import auto_layout_components, normalize_component
from .schemas import AgentState
from .stage_routing import next_stage_for_tool

import logging

logger = logging.getLogger(__name__)


def process_tool_response(response, state: AgentState) -> dict:
    """只执行第一个合法工具调用，杜绝跨阶段动作被合并。

    返回结构含 rejectedTools：记录被阶段白名单拒绝的工具名，
    供上层把失败原因注入下一轮 prompt 自省修正。
    noToolCall：模型未调用任何工具（直接输出文本），同样需要自省修正。
    unresolvedRefs：edit_page 中无法解析的组件引用（见 resolve_component_reference）。
    """
    result: dict = {"reply": "", "actions": [], "rejectedTools": []}

    if not getattr(response, "tool_calls", None):
        return {
            "reply": response.content or "抱歉，我没有理解你的需求",
            "actions": [],
            "rejectedTools": [],
            "noToolCall": True,
        }

    for tc in response.tool_calls:
        args = tc.get("args", {}) if isinstance(tc, dict) else tc.args
        name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
        if name not in state["allowed_tools"]:
            logger.warning("[AI] ignored tool outside stage: stage=%s tool=%s", state["stage"], name)
            result["rejectedTools"].append(name)
            continue
        handler = _TOOL_HANDLERS.get(name)
        if handler:
            handler(args, state, result, False)
            result["nextStage"] = next_stage_for_tool(name, state["stage"])
            return result

    return {
        "reply": "当前响应与执行阶段不匹配，请重新描述需求",
        "actions": [],
        "nextStage": state["stage"],
        "rejectedTools": result["rejectedTools"],
    }


# ==================== 组件引用解析 ====================

def resolve_component_reference(candidate: str, components: list[dict]) -> str | None:
    """把模型对组件的引用解析为画布真实 ID。

    只接受两种精确引用（画布上下文中均已显式列出）：
    - 组件 ID（大小写不敏感，容忍模型改写大小写）；
    - 组件 label 精确匹配（模型最常犯的错是「描述性称呼」，
      如画布 label 是「主标题」它说「大标题」——这类一律判为未解析，
      交由反馈闭环让模型用有效 ID 重试）。
    """
    if not candidate:
        return None
    normalized = str(candidate).strip().lower()
    if not normalized:
        return None
    for component in components:
        component_id = str(component.get("id", "")).strip().lower()
        if component_id and component_id == normalized:
            return component.get("id")
    for component in components:
        label = str(component.get("label", "")).strip().lower()
        if label and label == normalized:
            return component.get("id")
    return None


# ==================== 各工具的处理函数 ====================

def _handle_ask_question(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    result["question"] = args.get("question", "")
    if not seen_reply:
        result["reply"] = args.get("question", "")
    result["suggestions"] = args.get("suggestions", [])


def _handle_propose_options(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    if not seen_reply:
        result["reply"] = args.get("reply", "")
    result["options"] = [
        {"id": opt.get("id", _gen_id()), "title": opt.get("title", "方案"),
         "description": opt.get("description", ""), "tag": opt.get("tag", "")}
        for opt in args.get("options", [])
    ]


def _handle_confirm_plan(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    if not seen_reply:
        result["reply"] = args.get("summary", "")
    result["plan"] = {"summary": args.get("summary", ""), "details": args.get("details", [])}


def _handle_generate_page(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    cs = args.get("canvasStyle", {})
    cw = cs.get("width", state["canvas_width"])
    ch = cs.get("height", state["canvas_height"])
    comps = _normalize_components(args.get("components", []))
    comps = auto_layout_components(comps, cw, ch)
    if not seen_reply:
        result["reply"] = args.get("reply", "页面已生成")
    result["actions"].append({
        "type": "generate",
        "components": comps,
        "canvasStyle": {
            "width": cw, "height": ch, "scale": 100,
            "color": cs.get("color", "#000"), "opacity": cs.get("opacity", 100),
            "backgroundColor": cs.get("backgroundColor", "#ffffff"),
            "fontSize": cs.get("fontSize", 14),
        },
    })


def _handle_edit_page(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    if not seen_reply:
        result["reply"] = args.get("reply", "已修改")
    existing_ids = {c["id"] for c in state.get("components", [])}
    max_z = max((c.get("zIndex", 1) for c in state.get("components", [])), default=0)
    add_index = 0
    for op in args.get("operations", []):
        op_type = op.get("type")
        if op_type == "add" and op.get("component"):
            component = normalize_component(op["component"], max_z + add_index).model_dump()
            if component["id"] in existing_ids:
                component["id"] = _gen_id(8)
            existing_ids.add(component["id"])
            result["actions"].append({
                "type": "add",
                "component": component,
            })
            add_index += 1
        elif op_type in ("modify", "delete", "move") and op.get("id"):
            component_id = resolve_component_reference(op["id"], state.get("components", []))
            if not component_id:
                # 引用无法解析：记录并跳过该操作，由上层注入反馈让模型重试
                result.setdefault("unresolvedRefs", []).append({
                    "op": op_type,
                    "ref": op["id"],
                })
                continue
            if op_type == "modify":
                action: dict = {"type": "modify", "id": component_id}
                if isinstance(op.get("style"), dict) and op["style"]:
                    action["style"] = op["style"]
                if "propValue" in op:
                    action["propValue"] = op.get("propValue")
                if len(action) > 2:
                    result["actions"].append(action)
            elif op_type == "delete":
                result["actions"].append({"type": "delete", "id": component_id})
            else:  # move
                action = {"type": "move", "id": component_id}
                if "top" in op:
                    action["top"] = op["top"]
                if "left" in op:
                    action["left"] = op["left"]
                if len(action) > 2:
                    result["actions"].append(action)


def _handle_finish(args: dict, state: AgentState, result: dict, seen_reply: bool) -> None:
    result["reply"] = args.get("reply") or args.get("summary") or "当前画布已满足需求"
    result["finished"] = True


def _normalize_components(raw_components: list) -> list[dict]:
    """规范化生成结果，并保证组件 ID 唯一。"""
    normalized: list[dict] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_components):
        component = normalize_component(raw, index).model_dump()
        if not component["id"] or component["id"] in used_ids:
            component["id"] = _gen_id(8)
        used_ids.add(component["id"])
        normalized.append(component)
    return normalized


def _gen_id(length: int = 6) -> str:
    return generate_id(length)


# 工具名 → 处理函数映射
_TOOL_HANDLERS = {
    "ask_question": _handle_ask_question,
    "propose_options": _handle_propose_options,
    "confirm_plan": _handle_confirm_plan,
    "generate_page": _handle_generate_page,
    "edit_page": _handle_edit_page,
    "finish": _handle_finish,
}

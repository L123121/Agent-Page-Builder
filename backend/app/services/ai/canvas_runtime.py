"""画布工具运行时 — 在隔离快照中执行动作并生成最终差异。"""

from copy import deepcopy
from typing import Any


def apply_actions_to_canvas(
    components: list[dict],
    canvas_style: dict,
    actions: list[dict],
) -> tuple[list[dict], dict, list[dict]]:
    working_components = deepcopy(components)
    working_canvas_style = deepcopy(canvas_style)
    execution_events: list[dict] = []

    for action in actions:
        action_type = action.get("type")
        if action_type == "generate":
            working_components = deepcopy(action.get("components", []))
            working_canvas_style.update(deepcopy(action.get("canvasStyle", {})))
            execution_events.append({"type": "generate", "status": "success", "count": len(working_components)})
            continue

        if action_type == "add" and action.get("component"):
            component = deepcopy(action["component"])
            if any(item.get("id") == component.get("id") for item in working_components):
                execution_events.append({"type": "add", "status": "skipped", "reason": "duplicate_id"})
                continue
            working_components.append(component)
            execution_events.append({"type": "add", "status": "success", "id": component.get("id")})
            continue

        component_id = action.get("id")
        target = next((item for item in working_components if item.get("id") == component_id), None)
        if not target:
            execution_events.append({"type": action_type, "status": "skipped", "id": component_id, "reason": "not_found"})
            continue
        if target.get("isLock"):
            execution_events.append({"type": action_type, "status": "skipped", "id": component_id, "reason": "locked"})
            continue

        if action_type == "modify":
            if isinstance(action.get("style"), dict):
                target.setdefault("style", {}).update(deepcopy(action["style"]))
            if "propValue" in action:
                target["propValue"] = deepcopy(action.get("propValue"))
            execution_events.append({"type": "modify", "status": "success", "id": component_id})
        elif action_type == "move":
            if action.get("top") is not None:
                target.setdefault("style", {})["top"] = action["top"]
            if action.get("left") is not None:
                target.setdefault("style", {})["left"] = action["left"]
            execution_events.append({"type": "move", "status": "success", "id": component_id})
        elif action_type == "delete":
            working_components = [item for item in working_components if item.get("id") != component_id]
            execution_events.append({"type": "delete", "status": "success", "id": component_id})

    return working_components, working_canvas_style, execution_events


def diff_canvas(
    original_components: list[dict],
    final_components: list[dict],
    original_canvas_style: dict,
    final_canvas_style: dict,
    replace_all: bool = False,
) -> list[dict]:
    if replace_all or original_canvas_style != final_canvas_style:
        return [{
            "type": "generate",
            "components": deepcopy(final_components),
            "canvasStyle": deepcopy(final_canvas_style),
        }]

    original_by_id = {component.get("id"): component for component in original_components}
    final_by_id = {component.get("id"): component for component in final_components}
    actions: list[dict] = []

    for component_id in original_by_id.keys() - final_by_id.keys():
        actions.append({"type": "delete", "id": component_id})

    for component_id in final_by_id.keys() - original_by_id.keys():
        actions.append({"type": "add", "component": deepcopy(final_by_id[component_id])})

    for component_id in original_by_id.keys() & final_by_id.keys():
        original = original_by_id[component_id]
        final = final_by_id[component_id]
        style_changes = {
            key: value
            for key, value in final.get("style", {}).items()
            if original.get("style", {}).get(key) != value
        }
        action: dict[str, Any] = {"type": "modify", "id": component_id}
        if style_changes:
            action["style"] = style_changes
        if original.get("propValue") != final.get("propValue"):
            action["propValue"] = deepcopy(final.get("propValue"))
        if len(action) > 2:
            actions.append(action)

    return actions

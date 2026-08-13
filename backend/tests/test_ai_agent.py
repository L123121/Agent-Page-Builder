import unittest
from unittest.mock import AsyncMock, patch

from app.services.ai.agent import (
    executor_node,
    next_stage_for_tool,
    planner_node,
    process_tool_response,
    resolve_stage,
)
from app.services.ai.canvas_runtime import apply_actions_to_canvas, diff_canvas
from app.services.ai.component_utils import auto_layout_components, build_canvas_context, normalize_component
from app.services.ai.fallback import run_fallback_agent
from app.services.ai.validator import repair_canvas, validate_canvas
from app.services.ai.tools import TOOLS_BY_STAGE


class ToolCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class Response:
    content = ""

    def __init__(self, *tool_calls: ToolCall):
        self.tool_calls = list(tool_calls)


class AgentBehaviorTests(unittest.TestCase):
    def test_standard_text_component_keeps_prop_value(self):
        component = normalize_component({
            "id": "title-1",
            "component": "VText",
            "propValue": "社团招新",
            "style": {"top": 40, "left": 20, "fontSize": 30},
        })
        self.assertEqual(component.propValue, "社团招新")

    def test_layout_preserves_background_overlap(self):
        background = normalize_component({
            "id": "bg",
            "component": "RectShape",
            "style": {"width": 375, "height": 667, "top": 0, "left": 0},
            "zIndex": 1,
        }).model_dump()
        title = normalize_component({
            "id": "title",
            "component": "VText",
            "propValue": "招新",
            "style": {"width": 300, "height": 40, "top": 40, "left": 30},
            "zIndex": 10,
        }).model_dump()
        result = auto_layout_components([background, title], 375, 667)
        self.assertEqual(result[1]["style"]["top"], 40)

    def test_stage_router_prioritizes_edit_and_execute(self):
        self.assertEqual(resolve_stage("确认，请生成", [], "confirm"), "execute")
        self.assertEqual(resolve_stage("标题改成蓝色", [{"id": "title"}], "edit"), "edit")
        self.assertEqual(resolve_stage("做一个新的招新海报", [{"id": "title"}], "discover"), "discover")
        self.assertEqual(resolve_stage("做个海报", [], None), "discover")

    def test_new_page_requires_two_choice_rounds(self):
        self.assertEqual(resolve_stage("街舞社招新海报，9月15日", [], "discover"), "discover")
        self.assertEqual(next_stage_for_tool("propose_options", "discover"), "design")
        self.assertEqual(next_stage_for_tool("propose_options", "design"), "plan")
        self.assertNotIn("confirm_plan", TOOLS_BY_STAGE["discover"])
        self.assertNotIn("confirm_plan", TOOLS_BY_STAGE["design"])
        self.assertEqual(TOOLS_BY_STAGE["discover"], ["propose_options"])
        self.assertEqual(TOOLS_BY_STAGE["design"], ["propose_options"])
        self.assertEqual(TOOLS_BY_STAGE["plan"], ["confirm_plan"])
        self.assertEqual(resolve_stage("不用确认，直接生成", [], "discover"), "execute")

    def test_processes_only_one_allowed_tool_and_keeps_empty_prop_value(self):
        state = {
            "messages": [],
            "prompt": "清空标题",
            "components": [{
                "id": "real-title",
                "component": "VText",
                "label": "标题",
                "propValue": "旧标题",
                "style": {"fontSize": 28},
            }],
            "canvas_style": {},
            "canvas_width": 375,
            "canvas_height": 667,
            "stage": "edit",
            "allowed_tools": ["edit_page"],
            "result": {"reply": "", "actions": []},
        }
        response = Response(
            ToolCall("propose_options", {"reply": "错误", "options": []}),
            ToolCall("edit_page", {
                "reply": "已清空",
                "operations": [{"type": "modify", "id": "标题", "propValue": ""}],
            }),
        )
        result = process_tool_response(response, state)
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["id"], "real-title")
        self.assertEqual(result["actions"][0]["propValue"], "")

    def test_canvas_context_contains_selection_and_viewport(self):
        context = build_canvas_context(
            [],
            375,
            667,
            {"backgroundColor": "#ffffff"},
            ["title-1"],
            {"width": 1200, "height": 740, "scale": 100},
            "品牌主色为蓝色",
        )
        self.assertIn("title-1", context)
        self.assertIn("品牌主色为蓝色", context)
        self.assertIn("1200", context)

    def test_validator_repairs_bounds_but_keeps_missing_content_error(self):
        component = normalize_component({
            "id": "title",
            "component": "VText",
            "propValue": "",
            "style": {"width": 500, "height": 0, "top": -10, "left": -20},
        }).model_dump()
        report = validate_canvas([component], 375, 667, {"backgroundColor": "#ffffff"})
        repaired, fixes = repair_canvas(
            [component],
            375,
            667,
            {"backgroundColor": "#ffffff"},
            report["issues"],
            allow_reflow=True,
        )
        repaired_report = validate_canvas(repaired, 375, 667, {"backgroundColor": "#ffffff"})
        self.assertTrue(fixes)
        self.assertEqual(repaired[0]["style"]["left"], 0)
        self.assertEqual(repaired_report["errorCount"], 1)
        self.assertEqual(repaired_report["issues"][0]["code"], "missing_content")

    def test_runtime_respects_locked_components_and_builds_diff(self):
        original = [normalize_component({
            "id": "title",
            "component": "VText",
            "propValue": "旧标题",
            "style": {"top": 10, "left": 10},
            "isLock": True,
        }).model_dump()]
        updated, canvas_style, events = apply_actions_to_canvas(
            original,
            {"width": 375, "height": 667},
            [{"type": "modify", "id": "title", "propValue": "新标题"}],
        )
        self.assertEqual(updated[0]["propValue"], "旧标题")
        self.assertEqual(events[0]["reason"], "locked")
        self.assertEqual(diff_canvas(original, updated, canvas_style, canvas_style), [])


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_loop_repairs_after_validation_feedback(self):
        state = {
            "messages": [{"role": "user", "content": "把标题改成新标题"}],
            "prompt": "把标题改成新标题",
            "components": [{
                "id": "title",
                "component": "VText",
                "label": "标题",
                "propValue": "旧标题",
                "style": {"width": 200, "height": 40, "top": 20, "left": 20, "fontSize": 24, "color": "#111111"},
                "zIndex": 10,
                "isLock": False,
            }],
            "canvas_style": {"width": 375, "height": 667, "backgroundColor": "#ffffff"},
            "canvas_width": 375,
            "canvas_height": 667,
            "selected_component_ids": ["title"],
            "viewport": {"width": 375, "height": 667, "scale": 100},
            "project_knowledge": "",
            "requested_stage": "edit",
            "stage": "edit",
            "allowed_tools": ["edit_page", "finish"],
            "result": {"reply": "", "actions": []},
        }
        responses = [
            Response(ToolCall("edit_page", {
                "reply": "先修改标题",
                "operations": [{"type": "modify", "id": "title", "propValue": ""}],
            })),
            Response(ToolCall("edit_page", {
                "reply": "已修复标题内容",
                "operations": [{"type": "modify", "id": "title", "propValue": "新标题"}],
            })),
        ]
        with patch("app.services.ai.agent._invoke_llm", new=AsyncMock(side_effect=responses)):
            result = await executor_node(state)
        payload = result["result"]
        self.assertTrue(payload["validation"]["valid"])
        self.assertEqual(len(payload["trace"]), 2)
        self.assertEqual(payload["actions"][0]["propValue"], "新标题")


class AgentSelfCorrectionTests(unittest.IsolatedAsyncioTestCase):
    """覆盖多 Agent 分工（planner 产出方案 / executor 注入方案）与失败自省修正。"""

    def _planner_state(self, stage: str = "discover") -> dict:
        return {
            "messages": [{"role": "user", "content": "街舞社招新海报"}],
            "prompt": "街舞社招新海报",
            "components": [],
            "canvas_style": {"width": 375, "height": 667, "backgroundColor": "#ffffff"},
            "canvas_width": 375,
            "canvas_height": 667,
            "selected_component_ids": [],
            "viewport": {"width": 375, "height": 667, "scale": 100},
            "project_knowledge": "",
            "requested_stage": stage,
            "stage": stage,
            "allowed_tools": TOOLS_BY_STAGE[stage],
            "result": {"reply": "", "actions": []},
            "plan": None,
        }

    async def test_planner_rejects_out_of_stage_tool_and_retries(self):
        """planner 阶段工具被拒 → 注入反馈自省修正，不再直接返回错误。"""
        state = self._planner_state("discover")
        responses = [
            Response(ToolCall("confirm_plan", {"summary": "方案", "details": ["a"]})),
            Response(ToolCall("propose_options", {
                "reply": "选择方向",
                "options": [{"id": "poster", "title": "海报", "description": "x"}],
            })),
        ]
        with patch("app.services.ai.agent._invoke_llm", new=AsyncMock(side_effect=responses)), \
             patch("app.services.ai.agent.interrupt", return_value="我选择「海报」") as mock_interrupt:
            result = await planner_node(state)
        # 第一轮 confirm_plan 被拒，第二轮 propose_options 触发 interrupt 挂起
        self.assertTrue(mock_interrupt.called)
        payload = mock_interrupt.call_args[0][0]["payload"]
        self.assertEqual(payload["options"][0]["id"], "poster")

    async def test_planner_confirm_plan_writes_plan_to_state(self):
        """confirm_plan 产出的方案写入 state，供 executor 注入。"""
        state = self._planner_state("plan")
        responses = [
            Response(ToolCall("confirm_plan", {
                "summary": "深色潮流海报",
                "details": ["大标题", "动感配色", "报名入口"],
            })),
        ]
        with patch("app.services.ai.agent._invoke_llm", new=AsyncMock(return_value=responses[0])), \
             patch("app.services.ai.agent.interrupt", return_value="确认，请生成"):
            result = await planner_node(state)
        self.assertEqual(result["plan"]["summary"], "深色潮流海报")
        self.assertEqual(len(result["plan"]["details"]), 3)

    async def test_executor_injects_confirmed_plan_into_prompt(self):
        """executor 执行阶段把 planner 的方案注入系统提示词。"""
        state = self._planner_state("execute")
        state["plan"] = {"summary": "深色潮流海报", "details": ["大标题", "报名入口"]}
        state["allowed_tools"] = TOOLS_BY_STAGE["execute"]
        responses = [
            Response(ToolCall("generate_page", {
                "reply": "已生成",
                "canvasStyle": {"width": 375, "height": 667, "backgroundColor": "#111827"},
                "components": [{
                    "component": "VText",
                    "label": "标题",
                    "propValue": "街舞社招新",
                    "style": {"width": 300, "height": 60, "top": 40, "left": 20, "fontSize": 32, "color": "#ffffff"},
                }],
            })),
        ]
        with patch("app.services.ai.agent._invoke_llm", new=AsyncMock(return_value=responses[0])) as mock_llm:
            result = await executor_node(state)
        payload = result["result"]
        self.assertTrue(payload["validation"]["valid"])
        # 系统提示词包含已确认方案
        sent_messages = mock_llm.await_args.args[0]
        self.assertIn("深色潮流海报", sent_messages[0]["content"])

    def test_process_tool_response_records_rejected_tools(self):
        """阶段白名单外的工具被记录到 rejectedTools，合法的后续工具仍正常执行。"""
        state = {
            "messages": [],
            "prompt": "加个按钮",
            "components": [],
            "canvas_style": {},
            "canvas_width": 375,
            "canvas_height": 667,
            "selected_component_ids": [],
            "viewport": {},
            "project_knowledge": "",
            "requested_stage": "edit",
            "stage": "edit",
            "allowed_tools": ["edit_page", "finish"],
            "result": {"reply": "", "actions": []},
            "plan": None,
        }
        response = Response(
            ToolCall("propose_options", {"reply": "错误", "options": []}),
            ToolCall("edit_page", {
                "reply": "已添加",
                "operations": [{
                    "type": "add",
                    "component": {"component": "VText", "label": "新文本", "propValue": "你好", "style": {}},
                }],
            }),
        )
        result = process_tool_response(response, state)
        # propose_options 不在 edit 阶段白名单 → 记录到 rejectedTools
        self.assertIn("propose_options", result["rejectedTools"])
        # 后续合法的 edit_page 仍被正常执行
        self.assertEqual(result["actions"][0]["type"], "add")


class FallbackAgentTests(unittest.TestCase):
    def _state(self, stage: str, prompt: str = "街舞社招新海报，时间9月15日，地点大学生活动中心"):
        return {
            "messages": [{"role": "user", "content": prompt}],
            "prompt": prompt,
            "components": [],
            "canvas_style": {"width": 1200, "height": 740, "scale": 100, "backgroundColor": "#ffffff"},
            "canvas_width": 1200,
            "canvas_height": 740,
            "selected_component_ids": [],
            "viewport": {"width": 1200, "height": 740, "scale": 100},
            "project_knowledge": "",
            "requested_stage": stage,
            "stage": stage,
            "allowed_tools": TOOLS_BY_STAGE[stage],
            "result": {"reply": "", "actions": []},
        }

    def test_fallback_preserves_choice_and_generation_flow(self):
        discover = run_fallback_agent(self._state("discover"), "401 invalid_api_key")
        self.assertEqual(len(discover["options"]), 3)
        self.assertEqual(discover["nextStage"], "design")

        design = run_fallback_agent(self._state("design"), "401 invalid_api_key")
        self.assertEqual(len(design["options"]), 3)
        self.assertEqual(design["nextStage"], "plan")

        plan = run_fallback_agent(self._state("plan"), "401 invalid_api_key")
        self.assertIn("plan", plan)
        self.assertEqual(plan["nextStage"], "confirm")

        generated = run_fallback_agent(self._state("execute", "确认，请生成"), "401 invalid_api_key")
        self.assertEqual(generated["actions"][0]["type"], "generate")
        self.assertTrue(generated["actions"][0]["components"])
        self.assertTrue(generated["validation"]["valid"])


if __name__ == "__main__":
    unittest.main()

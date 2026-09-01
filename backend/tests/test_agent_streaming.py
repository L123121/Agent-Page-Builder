"""Agent 流式执行与 checkpointer 淘汰测试。

streaming 测试直接驱动 run_agent_streaming（graph.astream 真实执行，
仅 mock agent_nodes._invoke_llm），覆盖：
- planner interrupt → agent_done 携带 waitingForInput/options/threadId；
- resume 恢复挂起线程 → 继续在下一阶段产出；
- checkpoint 丢失时 resume 降级为新请求，不报错；
- executor trace → tool_call / tool_result / self_correction 事件；
- TTLMemorySaver 的 TTL 与容量淘汰。
"""
import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.dependencies import get_current_user
from app.services.ai.agent_streaming import run_agent_streaming
from app.services.ai.graph import TTLMemorySaver, agent_graph


def make_options_response():
    class FakeResponse:
        content = ""
        tool_calls = [{
            "name": "propose_options",
            "args": {
                "reply": "请选择页面方向",
                "options": [
                    {"id": "a", "title": "海报", "description": "宣传海报"},
                    {"id": "b", "title": "报名表", "description": "信息登记"},
                ],
            },
        }]
    return FakeResponse()


async def fake_invoke_options(_messages, _tools=None, **_kwargs):
    """_invoke_llm 的 AsyncMock side_effect：恒定返回选项工具调用。"""
    return make_options_response()


def make_generate_response():
    class FakeResponse:
        content = ""
        tool_calls = [{
            "name": "generate_page",
            "args": {
                "reply": "页面已生成",
                "canvasStyle": {"width": 375, "height": 667},
                "components": [
                    {
                        "component": "VText",
                        "label": "主标题",
                        "propValue": "社团招新",
                        "style": {"width": 300, "height": 50, "top": 40, "left": 20, "fontSize": 30},
                    },
                    {
                        "component": "VButton",
                        "label": "行动按钮",
                        "propValue": "立即报名",
                        "style": {"width": 120, "height": 44, "top": 120, "left": 20, "fontSize": 16},
                    },
                ],
            },
        }]
    return FakeResponse()


def make_bad_ref_then_fix_responses():
    """第一轮引用不存在的组件（触发自省修正），第二轮用正确 ID 修复。"""

    class BadResponse:
        content = ""
        tool_calls = [{
            "name": "edit_page",
            "args": {"reply": "改标题", "operations": [
                {"type": "modify", "id": "no-such-id", "propValue": "新标题"},
            ]},
        }]

    class FixResponse:
        content = ""
        tool_calls = [{
            "name": "edit_page",
            "args": {"reply": "改标题", "operations": [
                {"type": "modify", "id": "real-title", "propValue": "新标题"},
            ]},
        }]

    return [BadResponse(), FixResponse()]


async def collect_stream(**kwargs):
    events = []
    async for event in run_agent_streaming(**kwargs):
        events.append(event)
    return events


class AgentStreamingTests(unittest.TestCase):
    def _invoke_llm_mock(self, responses):
        """把 _invoke_llm mock 成按脚本逐轮返回；返回进入上下文管理器。"""
        if not isinstance(responses, list):
            responses = [responses]
        iterator = iter(responses * 20)  # 超出脚本后重复最后一个，避免 StopIteration

        async def fake_invoke(messages, tools=None, **_kwargs):
            return next(iterator)

        return patch("app.services.ai.agent_nodes._invoke_llm", side_effect=fake_invoke)

    def test_planner_interrupt_surfaces_waiting_agent_done(self):
        async def scenario():
            with self._invoke_llm_mock(make_options_response()):
                return await collect_stream(prompt="帮我做一个招新海报")

        events = asyncio.run(scenario())

        self.assertEqual(events[0]["type"], "agent_start")
        self.assertEqual(events[0]["stage"], "discover")
        dones = [e for e in events if e["type"] == "agent_done"]
        self.assertEqual(len(dones), 1)
        result = dones[0]["result"]
        self.assertTrue(result["waitingForInput"])
        self.assertEqual([o["title"] for o in result["options"]], ["海报", "报名表"])
        self.assertEqual(result["nextStage"], "design")
        self.assertTrue(result["threadId"])
        self.assertNotIn("agent_error", [e["type"] for e in events])

    def test_executor_stream_emits_tool_events_and_actions(self):
        async def scenario():
            with self._invoke_llm_mock(make_generate_response()):
                return await collect_stream(
                    prompt="确认，请生成",
                    conversation_stage="execute",
                )

        events = asyncio.run(scenario())

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        tool_results = [e for e in events if e["type"] == "tool_result"]
        dones = [e for e in events if e["type"] == "agent_done"]
        self.assertEqual([e["tool"] for e in tool_calls], ["generate_page"])
        self.assertEqual(tool_results[0]["status"], "done")
        self.assertEqual(tool_results[0]["step"], tool_calls[0]["step"])
        self.assertEqual(dones[0]["result"]["actions"][0]["type"], "generate")
        self.assertEqual(dones[0]["result"]["nextStage"], "edit")
        self.assertFalse(dones[0]["result"]["waitingForInput"])
        self.assertGreater(len(dones[0]["result"]["actions"][0]["components"]), 0)

    def test_executor_self_correction_streaming(self):
        async def scenario():
            responses = make_bad_ref_then_fix_responses()
            with self._invoke_llm_mock(responses):
                return await collect_stream(
                    prompt="标题改成新标题",
                    components=[{
                        "id": "real-title",
                        "component": "VText",
                        "label": "主标题",
                        "propValue": "旧标题",
                        "style": {"width": 300, "height": 40, "top": 20, "left": 20, "fontSize": 24},
                    }],
                    conversation_stage="edit",
                )

        events = asyncio.run(scenario())

        corrections = [e for e in events if e["type"] == "self_correction"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["error"], "unresolved_component_ref")
        dones = [e for e in events if e["type"] == "agent_done"]
        modify = dones[0]["result"]["actions"][0]
        self.assertEqual(modify["type"], "modify")
        self.assertEqual(modify["id"], "real-title")
        self.assertEqual(modify["propValue"], "新标题")

    def test_resume_continues_interrupted_thread(self):
        thread_id = "stream-resume-test"

        async def scenario():
            with self._invoke_llm_mock(make_options_response()):
                first = await collect_stream(prompt="做个海报", thread_id=thread_id)
                # 第一轮挂起后，模拟用户点选 → resume 恢复
                second = await collect_stream(
                    prompt="我选择「海报」",
                    thread_id=thread_id,
                    resume="我选择「海报」",
                )
            return first, second

        first, second = asyncio.run(scenario())

        first_done = [e for e in first if e["type"] == "agent_done"][0]
        self.assertTrue(first_done["result"]["waitingForInput"])
        second_done = [e for e in second if e["type"] == "agent_done"][0]
        self.assertTrue(second_done["result"]["waitingForInput"])
        # resume 后 planner 从 design 阶段继续（discover → design → ...）
        self.assertEqual(second_done["result"]["nextStage"], "plan")

    def test_resume_falls_back_to_fresh_run_without_checkpoint(self):
        async def scenario():
            # 从未在该 thread 上执行过：resume 应安全降级为新请求
            with self._invoke_llm_mock(make_options_response()):
                return await collect_stream(
                    prompt="做个海报",
                    thread_id="stream-never-seen",
                    resume="我选择「海报」",
                )

        events = asyncio.run(scenario())

        dones = [e for e in events if e["type"] == "agent_done"]
        self.assertEqual(len(dones), 1)
        self.assertTrue(dones[0]["result"]["waitingForInput"])
        self.assertNotIn("agent_error", [e["type"] for e in events])

    def test_fresh_run_discards_stale_pending_interrupt(self):
        thread_id = "stream-stale-interrupt"

        async def scenario():
            with self._invoke_llm_mock(make_options_response()):
                await collect_stream(prompt="做个海报", thread_id=thread_id)
                # 页面刷新后 waitingForInput 丢失：不带 resume 的新请求应正常执行
                return await collect_stream(prompt="换个风格", thread_id=thread_id)

        events = asyncio.run(scenario())

        dones = [e for e in events if e["type"] == "agent_done"]
        self.assertEqual(len(dones), 1)
        self.assertTrue(dones[0]["result"]["waitingForInput"])
        self.assertNotIn("agent_error", [e["type"] for e in events])


def _put_checkpoint(saver: TTLMemorySaver, thread_id: str, ts: str) -> None:
    checkpoint = {"ts": ts, "id": f"cp-{ts}", "channel_values": {}, "channel_versions": {}}
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": checkpoint["id"]}}
    saver.put(config, checkpoint, {"source": "loop", "step": 1}, {})


# ==================== 路由层 SSE 冒烟（main.app 全链路） ====================

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

STREAM_CHAT_PAYLOAD = {
    "prompt": "帮我做一个招新海报",
    "history": [],
    "components": [],
    "canvasStyle": {"width": 375, "height": 667},
}


class StreamRouterTests(unittest.TestCase):
    """POST /api/ai/chat/stream：鉴权依赖覆盖 + LLM 打桩，验证 SSE 事件协议。"""

    def setUp(self):
        from main import app
        self._saved = {
            get_db: app.dependency_overrides.get(get_db),
            get_current_user: app.dependency_overrides.get(get_current_user),
        }
        app.dependency_overrides[get_db] = self._override_get_db
        app.dependency_overrides[get_current_user] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        from main import app
        for dependency, saved in self._saved.items():
            if saved is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = saved

    @staticmethod
    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    def _post_stream(self, payload):
        events = []
        with patch("app.services.ai.agent_nodes._invoke_llm", side_effect=fake_invoke_options), \
             patch("app.services.ai.agent_streaming.log_agent_run"):
            with self.client.stream("POST", "/api/ai/chat/stream", json=payload) as response:
                self.assertEqual(response.status_code, 200)
                for line in response.iter_lines():
                    line = line.strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        events.append(json.loads(line[len("data: "):]))
        return events

    def test_stream_endpoint_emits_waiting_agent_done(self):
        events = self._post_stream(STREAM_CHAT_PAYLOAD)
        self.assertEqual(events[0]["type"], "agent_start")
        dones = [e for e in events if e["type"] == "agent_done"]
        self.assertEqual(len(dones), 1)
        result = dones[0]["result"]
        self.assertTrue(result["waitingForInput"])
        self.assertEqual(len(result["options"]), 2)
        self.assertTrue(result["threadId"])

    def test_stream_endpoint_rejects_oversize_prompt(self):
        with patch("app.services.ai.agent_streaming.log_agent_run"):
            response = self.client.post(
                "/api/ai/chat/stream",
                json={**STREAM_CHAT_PAYLOAD, "prompt": "超" * 5000},
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()


class TTLMemorySaverTests(unittest.TestCase):
    def test_expired_thread_is_evicted(self):
        saver = TTLMemorySaver(ttl_seconds=100, max_threads=10)
        _put_checkpoint(saver, "old-thread", "2020-01-01T00:00:00+00:00")
        _put_checkpoint(saver, "new-thread", "2100-01-01T00:00:00+00:00")
        saver._sweep(force=True)
        self.assertNotIn("old-thread", saver.storage)
        self.assertIn("new-thread", saver.storage)

    def test_capacity_overflow_evicts_least_recent(self):
        saver = TTLMemorySaver(ttl_seconds=0, max_threads=2)
        _put_checkpoint(saver, "t1", "2020-01-01T00:00:00+00:00")
        _put_checkpoint(saver, "t2", "2021-01-01T00:00:00+00:00")
        _put_checkpoint(saver, "t3", "2022-01-01T00:00:00+00:00")
        saver._sweep(force=True)
        self.assertNotIn("t1", saver.storage)
        self.assertEqual(set(saver.storage), {"t2", "t3"})

    def test_eviction_cleans_writes_and_blobs(self):
        saver = TTLMemorySaver(ttl_seconds=100, max_threads=10)
        _put_checkpoint(saver, "gone", "2020-01-01T00:00:00+00:00")
        config = {
            "configurable": {
                "thread_id": "gone",
                "checkpoint_ns": "",
                "checkpoint_id": f"cp-2020-01-01T00:00:00+00:00",
            }
        }
        saver.put_writes(config, [("channel", "value")], "task-1")
        self.assertTrue(saver.writes)
        saver._sweep(force=True)
        self.assertEqual(saver.storage, {})
        self.assertEqual(saver.writes, {})
        self.assertEqual(saver.blobs, {})

    def test_compiled_graph_uses_ttl_saver(self):
        self.assertIsInstance(agent_graph.checkpointer, TTLMemorySaver)


if __name__ == "__main__":
    unittest.main()

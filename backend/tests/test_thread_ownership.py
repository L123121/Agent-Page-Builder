"""AI 会话线程的用户归属隔离测试。

覆盖：
- resolve_thread 按用户命名空间生成内部 checkpoint 键，对外 threadId 不变；
- 他人挂起的线程不能被其他用户 resume，原挂起状态保持完整、可由所有者继续；
- 伪造的 threadId 与他人线程的表现一致（降级为新会话，不泄露存在性）；
- 路由层：未登录 401、非法 threadId 422、双用户 HTTP 调用的归属传递。

LLM 调用通过 _invoke_llm 打桩，checkpointer 为进程内实现，无外部依赖。
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

from app.config import settings
from app.database import Base, get_db
from app.dependencies import get_current_user
from app.services.ai.agent_streaming import run_agent_streaming
from app.services.ai.graph import agent_graph, has_pending_interrupt
from app.services.ai.run_context import build_graph_config, resolve_thread
from main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

PROMPT = "做个海报"

_api_key_patch = None


def setUpModule():
    """流式入口未配置 AI_API_KEY 时直接返回 agent_error；LLM 已打桩，与本机环境无关。"""
    global _api_key_patch
    _api_key_patch = patch.object(settings, "AI_API_KEY", "test-key")
    _api_key_patch.start()


def tearDownModule():
    if _api_key_patch is not None:
        _api_key_patch.stop()


class FakeUser:
    def __init__(self, user_id: str):
        self.id = user_id


def _override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


class _OptionsResponse:
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


async def _fake_invoke_options(_messages, _tools=None, **_kwargs):
    return _OptionsResponse()


def _llm_patch():
    return patch("app.services.ai.agent_nodes._invoke_llm", side_effect=_fake_invoke_options)


async def _collect(owner_id, **kwargs):
    events = []
    async for event in run_agent_streaming(owner_id=owner_id, **kwargs):
        events.append(event)
    return events


def _done(events):
    dones = [event for event in events if event["type"] == "agent_done"]
    return dones[0]["result"] if dones else None


class ResolveThreadTests(unittest.TestCase):
    def test_same_public_id_maps_to_different_checkpoints_per_owner(self):
        public_a, internal_a = resolve_thread("shared-id", "alice")
        public_b, internal_b = resolve_thread("shared-id", "bob")
        self.assertEqual(public_a, "shared-id")
        self.assertEqual(public_b, "shared-id")
        self.assertNotEqual(internal_a, internal_b)

    def test_missing_thread_id_generates_public_id(self):
        public, internal = resolve_thread(None, "alice")
        self.assertTrue(public.startswith("thread-"))
        self.assertIn(public, internal)


class ThreadOwnershipTests(unittest.TestCase):
    def test_other_user_cannot_resume_pending_interrupt(self):
        thread_id = "ownership-pending-a"

        async def scenario():
            with _llm_patch():
                first = await _collect("alice", prompt=PROMPT, thread_id=thread_id)
                # bob 使用 alice 的 threadId 恢复：应降级为 bob 自己的新会话
                intruder = await _collect(
                    "bob", prompt=PROMPT, thread_id=thread_id, resume="我选择「海报」",
                )
            _, alice_internal = resolve_thread(thread_id, "alice")
            alice_still_pending = await has_pending_interrupt(
                agent_graph, build_graph_config(alice_internal),
            )
            with _llm_patch():
                resumed = await _collect(
                    "alice", prompt=PROMPT, thread_id=thread_id, resume="我选择「海报」",
                )
            return first, intruder, alice_still_pending, resumed

        first, intruder, alice_still_pending, resumed = asyncio.run(scenario())

        self.assertTrue(_done(first)["waitingForInput"])
        intruder_result = _done(intruder)
        # 新会话从 discover 开始，下一阶段是 design；若误恢复 alice 的线程则会是 plan
        self.assertEqual(intruder_result["nextStage"], "design")
        self.assertEqual(intruder_result["threadId"], thread_id)
        self.assertTrue(alice_still_pending, "bob 的请求不得消费 alice 的挂起状态")
        # alice 本人仍可正常恢复
        self.assertEqual(_done(resumed)["nextStage"], "plan")

    def test_forged_thread_behaves_like_unknown_thread(self):
        async def scenario():
            with _llm_patch():
                return await _collect(
                    "mallory", prompt=PROMPT, thread_id="forged-never-issued", resume="我选择「海报」",
                )

        events = asyncio.run(scenario())

        self.assertNotIn("agent_error", [event["type"] for event in events])
        result = _done(events)
        self.assertEqual(result["nextStage"], "design")
        self.assertEqual(result["threadId"], "forged-never-issued")


class ThreadOwnershipRouterTests(unittest.TestCase):
    def setUp(self):
        self.current = {"id": "alice"}
        self._saved = {
            get_db: app.dependency_overrides.get(get_db),
            get_current_user: app.dependency_overrides.get(get_current_user),
        }
        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_current_user] = lambda: FakeUser(self.current["id"])
        self.client = TestClient(app)

    def tearDown(self):
        for dependency, saved in self._saved.items():
            if saved is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = saved

    def _post_stream(self, payload):
        events = []
        with _llm_patch(), patch("app.services.ai.agent_streaming.log_agent_run"):
            with self.client.stream("POST", "/api/ai/chat/stream", json=payload) as response:
                self.assertEqual(response.status_code, 200)
                for line in response.iter_lines():
                    line = line.strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        events.append(json.loads(line[len("data: "):]))
        return events

    def test_stream_requires_authentication(self):
        app.dependency_overrides.pop(get_current_user, None)
        response = self.client.post("/api/ai/chat/stream", json={"prompt": PROMPT})
        self.assertEqual(response.status_code, 401)

    def test_invalid_thread_id_is_rejected(self):
        for bad in ["../../etc", "a" * 129, "has space", "x|thread:y"]:
            with self.subTest(thread_id=bad):
                response = self.client.post(
                    "/api/ai/chat/stream", json={"prompt": PROMPT, "threadId": bad},
                )
                self.assertEqual(response.status_code, 422)

    def test_http_resume_across_users_is_isolated(self):
        thread_id = "http-ownership-thread"
        self.current["id"] = "alice"
        first = self._post_stream({"prompt": PROMPT, "threadId": thread_id})
        self.assertTrue(_done(first)["waitingForInput"])

        self.current["id"] = "bob"
        intruder = self._post_stream({
            "prompt": PROMPT, "threadId": thread_id, "resume": "我选择「海报」",
        })
        self.assertEqual(_done(intruder)["nextStage"], "design")

        self.current["id"] = "alice"
        resumed = self._post_stream({
            "prompt": PROMPT, "threadId": thread_id, "resume": "我选择「海报」",
        })
        self.assertEqual(_done(resumed)["nextStage"], "plan")


if __name__ == "__main__":
    unittest.main()

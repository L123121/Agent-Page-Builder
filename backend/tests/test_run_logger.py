"""运行日志与 golden 飞轮测试 — 落库字段、状态判定、候选导出"""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.agent_run import AgentRun
from app.services.ai import run_logger
from app.services.ai.run_logger import log_agent_run
from eval.golden_suggest import build_report

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _log(**kwargs) -> None:
    """在测试会话上执行日志（patch 掉模块级 SessionLocal）"""
    with patch.object(run_logger, "SessionLocal", TestSession):
        log_agent_run(**kwargs)


class RunLoggerTests(unittest.TestCase):
    def setUp(self):
        with TestSession() as db:
            db.query(AgentRun).delete()
            db.commit()

    def _runs(self):
        with TestSession() as db:
            runs = db.query(AgentRun).order_by(AgentRun.id).all()
            db.expunge_all()
            return runs

    def test_status_resolution_and_fields(self):
        _log(
            source="chat", thread_id="t1", stage="edit",
            result={
                "reply": "已完成", "actions": [{"type": "modify"}],
                "validation": {"valid": True, "errorCount": 0, "warningCount": 2, "issues": []},
                "trace": [
                    {"step": 1, "tool": "edit_page", "execution": [], "autoFixes": []},
                    {"type": "correction", "step": 2, "error": "unresolved_component_ref", "unresolvedRefs": [{"ref": "大标题"}]},
                ],
            },
            duration_ms=1234, prompt="把主标题字号放大",
        )
        run = self._runs()[0]
        self.assertEqual(run.status, "success")
        self.assertEqual(run.actions_count, 1)
        self.assertEqual(run.prompt, "把主标题字号放大")
        self.assertEqual(run.validation, {"valid": True, "errorCount": 0, "warningCount": 2})
        self.assertEqual(len(run.corrections), 1)
        self.assertEqual(run.corrections[0]["type"], "unresolved_component_ref")
        self.assertEqual(run.duration_ms, 1234)

    def test_error_waiting_degraded_status(self):
        _log(source="chat", thread_id="t", stage="edit", result={"reply": "AI 处理失败: boom"}, duration_ms=10, prompt="p")
        _log(source="chat", thread_id="t", stage="edit", result={"error": "rate limited", "reply": "x"}, duration_ms=10, prompt="p")
        _log(source="chat", thread_id="t", stage="plan", result={"__interrupt__": [{"value": {"payload": {"reply": "请选择"}}}]}, duration_ms=10, prompt="p")
        _log(source="chat", thread_id="t", stage="execute", result={"reply": "已生成", "trace": [{"tool": "local_fallback", "step": 0}]}, duration_ms=10, prompt="p")

        statuses = [r.status for r in self._runs()]
        self.assertEqual(statuses, ["error", "error", "waiting", "degraded"])

    def test_explicit_error_beats_waiting(self):
        _log(source="chat", thread_id="t", stage="edit", result={"__interrupt__": [{"value": {"payload": {}}}]}, duration_ms=10, error="timeout", prompt="p")
        self.assertEqual(self._runs()[0].status, "error")

    def test_long_fields_truncated(self):
        _log(source="chat", thread_id="t" * 200, stage="edit", result={"reply": "x" * 2000}, duration_ms=1, error="e" * 2000, prompt="p" * 2000)
        run = self._runs()[0]
        self.assertEqual(len(run.prompt), 500)
        self.assertEqual(len(run.reply), 500)
        self.assertEqual(len(run.error), 500)
        self.assertEqual(len(run.thread_id), 100)

    def test_logging_failure_never_raises(self):
        class BrokenSession:
            def __enter__(self):
                raise RuntimeError("db down")

            def __exit__(self, *args):
                return False

        with patch.object(run_logger, "SessionLocal", lambda: BrokenSession()):
            # 不应抛出
            _log(source="chat", thread_id="t", stage="edit", result={"reply": "ok"}, duration_ms=10, prompt="p")

    def test_golden_suggest_reports_candidates(self):
        _log(source="chat", thread_id="t", stage="edit",
             result={"reply": "ok", "trace": [{"type": "correction", "step": 1, "error": "tool_not_allowed", "rejectedTools": ["generate_page"]}]},
             duration_ms=100, prompt="把标题改大")
        _log(source="chat", thread_id="t", stage="edit",
             result={"reply": "AI 处理失败: rpm"}, duration_ms=50, error="429", prompt="做个海报")

        import eval.golden_suggest as gs
        with patch.object(gs, "SessionLocal", TestSession):
            report = build_report(limit=10)

        self.assertIn("运行统计", report)
        self.assertIn("自省修正触发率", report)
        self.assertIn("tool_not_allowed", report)
        self.assertIn("如何固化为 golden 用例", report)


if __name__ == "__main__":
    unittest.main()

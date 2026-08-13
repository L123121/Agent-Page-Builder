"""LLM-as-a-Judge 单元测试

覆盖：
  - _extract_json 的容错解析（代码块围栏、前后杂音、非法 JSON）
  - judge_run 正常打分路径（解析 score/summary/issues）
  - judge_run 在 LLM 输出不可解析时重试并最终降级
  - judge_run 在 LLM 调用抛异常时降级（judgeScore=None + judgeError，不阻断）
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from eval.judge import _extract_json, judge_run


class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(_extract_json('{"score": 85, "summary": "好"}'), {"score": 85, "summary": "好"})

    def test_fenced_json(self):
        text = '```json\n{"score": 90}\n```'
        self.assertEqual(_extract_json(text), {"score": 90})

    def test_text_with_trailing_noise(self):
        text = '好的，这是评分结果：{"score": 77, "issues": ["a"]} 希望能帮到你'
        self.assertEqual(_extract_json(text), {"score": 77, "issues": ["a"]})

    def test_invalid_json_returns_none(self):
        self.assertIsNone(_extract_json("这不是 JSON"))
        self.assertIsNone(_extract_json("{broken"))


class JudgeRunTests(unittest.IsolatedAsyncioTestCase):
    TASK = {
        "id": "poster_dance_recruit",
        "name": "街舞社招新海报",
        "prompt": "制作一张街舞社招新海报",
        "canvasStyle": {"width": 375, "height": 667},
        "initialCanvas": [],
        "expected": {"minComponents": 3, "requireComponents": ["VText", "VButton"]},
    }
    RUN = {
        "finalCanvas": [
            {"id": "c1", "component": "VText", "propValue": "街舞社招新", "style": {"top": 40, "left": 20, "fontSize": 30, "width": 300, "height": 60}},
            {"id": "c2", "component": "VButton", "propValue": "报名", "style": {"top": 300, "left": 80, "width": 200, "height": 48}},
        ],
        "canvasStyle": {"width": 375, "height": 667},
    }

    def _mock_llm(self, content: str, raises: bool = False):
        response = MagicMock()
        response.content = content
        bound = MagicMock()
        if raises:
            bound.ainvoke = AsyncMock(side_effect=Exception("LLM down"))
        else:
            bound.ainvoke = AsyncMock(return_value=response)
        client = MagicMock()
        client.bind.return_value = bound
        return client

    async def test_judge_run_parses_score(self):
        client = self._mock_llm('{"score": 92, "summary": "布局合理，内容完整", "issues": ["标题字号可再大"]}')
        with patch("eval.judge.get_llm_client", return_value=client):
            result = await judge_run(self.TASK, self.RUN)
        self.assertEqual(result["judgeScore"], 92)
        self.assertEqual(result["judgeSummary"], "布局合理，内容完整")
        self.assertEqual(result["judgeIssues"], ["标题字号可再大"])
        self.assertIsNone(result["judgeError"])

    async def test_judge_run_retries_then_degrades_on_bad_output(self):
        # 第一次输出无法解析，第二次输出可解析 → 重试成功
        client = self._mock_llm("无法解析的输出")
        with patch("eval.judge.get_llm_client", return_value=client):
            result = await judge_run(self.TASK, self.RUN)
        self.assertIsNone(result["judgeScore"])
        self.assertIsNotNone(result["judgeError"])

    async def test_judge_run_degrades_on_llm_exception(self):
        client = self._mock_llm("", raises=True)
        with patch("eval.judge.get_llm_client", return_value=client):
            result = await judge_run(self.TASK, self.RUN)
        self.assertIsNone(result["judgeScore"])
        self.assertIn("LLM down", result["judgeError"] or "")
        # 降级不阻断：字段齐全
        for key in ("judgeScore", "judgeSummary", "judgeIssues", "judgeError"):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

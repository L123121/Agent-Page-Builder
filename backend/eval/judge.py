"""LLM-as-a-Judge 评分器

对一次 Agent 运行结果，让 LLM 作为评审专家按 rubric 打分（0~100），
与 scorer.py 的规则化检查互补：
  - scorer.py：确定性检查（组件数量/类型/文本关键字/验证器/步数等），0/1 判定
  - judge.py：质量维度评审（内容完整性/组件覆盖/布局/视觉/需求符合度），0~100 连续分

设计要点：
  - 复用 app.services.ai.llm.get_llm_client()（模块级单例，共享连接池）
  - 画布上下文复用 build_canvas_context()（单行摘要 + token 预算），
    避免大画布把 judge 请求撑爆（与 Agent 的 TPM 控制一致）
  - LLM 失败时降级：返回 judgeScore=None + judgeError，不阻断主流程
  - mock 模式不调用（不消耗 token），仅 live 模式启用
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.services.ai.component_utils import build_canvas_context
from app.services.ai.llm import get_llm_client

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """你是一位严格的低代码页面设计评审专家（LLM-as-a-Judge）。请根据「用户需求」与「画布实际产出」，按以下 rubric 打分（0~100）：

## 评分维度（总分 100）
1. 内容完整性（25 分）：用户需求中的关键内容是否全部呈现在画布上；期望文本关键字是否命中。
2. 组件覆盖（15 分）：是否包含期望的组件类型（如 VText/VButton/Picture）；是否出现禁止的组件类型。
3. 布局质量（20 分）：组件不超出画布边界；间距合理；标题水平居中；无严重重叠。
4. 视觉规范（20 分）：标题字号 24-36px、正文 14-16px；配色协调；层级 zIndex 合理。
5. 需求符合度（20 分）：画布整体是否符合用户提示词表达的全部意图与细节。

## 打分规则
- 关键内容缺失或完全偏离需求 → 大幅扣分；小瑕疵 → 酌情扣分。
- 只输出严格 JSON，不要输出任何其他文字。
- JSON 格式：{"score": 数字, "summary": "一句话总结", "issues": ["问题1", "问题2"]}"""


def _compact_expected(expected: Optional[Dict[str, Any]]) -> str:
    """将任务的期望标准压缩为简短 JSON 文本（供 judge 参考）"""
    if not expected:
        return "（无显式期望标准，请根据用户需求自行判断）"
    return json.dumps(expected, ensure_ascii=False, separators=(",", ":"))


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中稳健提取 JSON 对象（容忍 markdown 代码块与前后杂音）"""
    if not text:
        return None
    # 去掉 ```json ... ``` 围栏
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    # 取第一个 { 到最后一个 } 之间的内容
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def judge_run(task: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    """LLM-as-a-Judge：按 rubric 对一次运行结果打分。

    返回:
      {
        "judgeScore": int | None,      # 0~100；LLM 失败时为 None
        "judgeSummary": str,            # LLM 一句话总结
        "judgeIssues": List[str],       # LLM 指出的问题
        "judgeError": str | None,       # 失败原因（无失败为 None）
      }
    """
    result: Dict[str, Any] = {
        "judgeScore": None,
        "judgeSummary": "",
        "judgeIssues": [],
        "judgeError": None,
    }

    final_canvas = run.get("finalCanvas") or []
    canvas_style = run.get("canvasStyle") or task.get("canvasStyle") or {}
    width = int(canvas_style.get("width") or 375)
    height = int(canvas_style.get("height") or 667)

    canvas_context = build_canvas_context(
        final_canvas,
        width,
        height,
        canvas_style,
        project_knowledge="",
    )

    user_content = (
        f"## 用户需求\n{task.get('prompt', '')}\n\n"
        f"## 期望标准\n{_compact_expected(task.get('expected'))}\n\n"
        f"## 画布产出\n{canvas_context}"
    )
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # 低温调用，减少打分方差
    llm = get_llm_client().bind(temperature=0.2)
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = await llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            parsed = _extract_json(content)
            if parsed is None:
                raise ValueError(f"judge 输出无法解析为 JSON: {str(content)[:200]}")
            score = parsed.get("score")
            result["judgeScore"] = int(score) if isinstance(score, (int, float)) else None
            result["judgeSummary"] = str(parsed.get("summary", ""))
            issues = parsed.get("issues", [])
            result["judgeIssues"] = [str(i) for i in issues] if isinstance(issues, list) else []
            return result
        except Exception as error:  # noqa: BLE001 —— 降级不阻断主流程
            last_error = error
            logger.warning("[judge] LLM call failed (attempt %s/2): %s", attempt + 1, error)

    result["judgeError"] = str(last_error)
    return result

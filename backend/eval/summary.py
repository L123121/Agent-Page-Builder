"""Eval 报告汇总 — 把最新 mock / live 报告聚合为一张 Markdown 表格。

用法：
  python -m eval.summary            # 打印汇总表到 stdout
  python -m eval.summary --write    # 同时写入 eval/reports/summary.md

用途：README 的评测表格直接由本脚本生成，保证文档与最新报告一致；
面试/复盘时一条命令即可重放全部历史成绩。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = BACKEND_DIR / "eval" / "reports"
OUTPUT_PATH = REPORT_DIR / "summary.md"

# 任务 id 前缀 → 展示类别
CATEGORY_RULES = [
    ("adv_", "对抗性"),
    ("poster_", "生成"), ("form_", "生成"), ("page_", "生成"),
    ("edit_", "编辑"),
    ("delete_", "删除"),
    ("layout_", "布局"),
    ("empty_", "交互"),
]


def task_category(task_id: str) -> str:
    for prefix, category in CATEGORY_RULES:
        if task_id.startswith(prefix):
            return category
    return "其他"


def _latest_report(mode: str) -> Optional[Path]:
    candidates = sorted(REPORT_DIR.glob(f"eval-{mode}-*.json"))
    return candidates[-1] if candidates else None


def _load_report(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_summary() -> str:
    mock_path, mock_report = _latest_report("mock"), _load_report(_latest_report("mock"))
    live_path, live_report = _latest_report("live"), _load_report(_latest_report("live"))
    if not mock_report and not live_report:
        return "暂无评测报告。先运行 `python -m eval.runner --mode mock`。"

    def result_index(report: Optional[dict]) -> Dict[str, dict]:
        return {r.get("taskId", ""): r for r in (report or {}).get("results", [])}

    mock_by_id = result_index(mock_report)
    live_by_id = result_index(live_report)
    task_ids: List[str] = []
    for report in (mock_report, live_report):
        for r in (report or {}).get("results", []):
            if r.get("taskId") and r["taskId"] not in task_ids:
                task_ids.append(r["taskId"])

    lines: List[str] = []
    lines.append("# Agent 评测汇总")
    lines.append("")
    for label, path in (("mock", mock_path), ("live", live_path)):
        if path:
            lines.append(f"- 最新 {label} 报告：`{path.name}`")
    lines.append("")
    lines.append("| 任务 | 类别 | mock | live 规则分 | live Judge 分 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for task_id in task_ids:
        mock_r = mock_by_id.get(task_id)
        live_r = live_by_id.get(task_id)
        mock_cell = "✅" if mock_r and mock_r.get("pass") else ("❌" if mock_r else "—")
        live_score = str(live_r.get("score")) if live_r and live_r.get("score") is not None else "—"
        judge = live_r.get("judgeScore") if live_r else None
        judge_cell = str(judge) if judge is not None else "—"
        lines.append(
            f"| {task_id} | {task_category(task_id)} | {mock_cell} | {live_score} | {judge_cell} |"
        )
    lines.append("")

    for label, report in (("mock", mock_report), ("live", live_report)):
        if report:
            generated = datetime.now().strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"- **{label} 汇总**：任务 {report.get('taskCount', 0)} ｜ "
                f"通过率 {report.get('passRate', 0)}% ｜ 平均规则分 {report.get('avgScore', 0)}"
                + (f" ｜ 平均 Judge 分 {report['avgJudgeScore']}" if report.get("avgJudgeScore") is not None else "")
            )
    if mock_report or live_report:
        lines.append(f"")
        lines.append(f"（生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}，由 `python -m eval.summary --write` 产出）")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总最新 eval 报告为 Markdown 表格")
    parser.add_argument("--write", action="store_true", help="同时写入 eval/reports/summary.md")
    args = parser.parse_args()

    summary = build_summary()
    print(summary)
    if args.write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(summary + "\n", encoding="utf-8")
        print(f"\n已写入: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

"""Golden 候选挖掘 — 从 agent_runs 运行日志中沉淀「失败/修正 case」

飞轮闭环：Agent 线上运行 → 修正轮次/错误落库（run_logger）→ 本脚本扫描导出
候选清单 → 人工筛选后固化为 eval/tasks.py 的 golden 任务（mock 多轮脚本第一轮
复现错误、第二轮复现修正），进 CI 防劣化。

用法：
  python -m eval.golden_suggest                 # 打印统计 + 候选清单
  python -m eval.golden_suggest --limit 30 --write  # 同时写入 eval/reports/golden_candidates.md
"""

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List

# 允许从 backend/ 目录直接执行 python -m eval.golden_suggest
import sys
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402

OUTPUT_PATH = BACKEND_DIR / "eval" / "reports" / "golden_candidates.md"

STATUS_LABELS = {
    "success": "成功",
    "waiting": "等待用户输入",
    "degraded": "本地降级",
    "error": "错误",
}


def _correction_summary(corrections: list | None) -> str:
    if not corrections:
        return ""
    types = [c.get("type") or "?" for c in corrections]
    return "、".join(types)


def build_report(limit: int = 20) -> str:
    lines: List[str] = ["# Golden 候选清单（来自 agent_runs 运行日志）", ""]

    # 幂等建表：脚本可能在服务首次启动前独立运行
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        runs = db.query(AgentRun).order_by(AgentRun.created_at.desc()).all()

    if not runs:
        lines.append("暂无运行记录。跑一些真实请求（或 live 评测）后重试。")
        return "\n".join(lines)

    # ==================== 运行统计 ====================
    total = len(runs)
    by_status: Dict[str, int] = {}
    corrected = 0
    error_count = 0
    durations = [r.duration_ms for r in runs if r.duration_ms]
    for run in runs:
        by_status[run.status] = by_status.get(run.status, 0) + 1
        if run.corrections:
            corrected += 1
        if run.status == "error":
            error_count += 1

    lines.append("## 运行统计")
    lines.append("")
    lines.append(f"- 总运行数：{total}")
    lines.append("- 状态分布：" + "，".join(f"{STATUS_LABELS.get(s, s)} {n}" for s, n in sorted(by_status.items())))
    if durations:
        durations_sorted = sorted(durations)
        p50 = durations_sorted[len(durations_sorted) // 2]
        p95 = durations_sorted[min(len(durations_sorted) - 1, int(len(durations_sorted) * 0.95))]
        lines.append(f"- 耗时：P50 {p50}ms / P95 {p95}ms")
    lines.append(f"- 自省修正触发率：{corrected}/{total}（{corrected / total * 100:.0f}%）")
    lines.append(f"- 错误率：{error_count}/{total}（{error_count / total * 100:.0f}%）")
    lines.append("")

    # ==================== 候选清单 ====================
    candidates = [r for r in runs if r.corrections or r.status in ("error", "degraded")][:limit]

    lines.append(f"## Golden 候选（最近 {len(candidates)} 条，共 {corrected + error_count} 条信号）")
    lines.append("")
    if not candidates:
        lines.append("没有修正/错误/降级运行——暂无新候选，这是好信号。")
        return "\n".join(lines)

    lines.append("| 时间 | 状态 | 修正类型 | prompt（截断） | 错误/验证 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for run in candidates:
        time_str = run.created_at.strftime("%m-%d %H:%M") if run.created_at else "-"
        validation = run.validation or {}
        verdict = run.error or f"errors={validation.get('errorCount', '-')}, warnings={validation.get('warningCount', '-')}"
        lines.append(
            f"| {time_str} | {STATUS_LABELS.get(run.status, run.status)} "
            f"| {_correction_summary(run.corrections) or '—'} "
            f"| {(run.prompt or '')[:60].replace('|', '\\|')} "
            f"| {verdict} |"
        )

    lines.append("")
    lines.append("## 如何固化为 golden 用例")
    lines.append("")
    lines.append("1. 在 `eval/tasks.py` 新增任务：prompt 用候选运行的真实请求，initialCanvas 复现当时的画布状态")
    lines.append("2. 在 `eval/runner.py` 的 `_MOCK_MULTI_STEP_SCRIPTS` 加多轮脚本：第一轮复现失败")
    lines.append("   （引用不存在的组件 / 调白名单外工具 / 操作锁定组件），第二轮复现修正")
    lines.append("3. expected 里设 `selfCorrected: True` 让 SELF_CORRECTED 检查项断言修正真实发生")
    lines.append("4. 跑 `python -m eval.runner --mode mock --require-pass-rate 100` 确认进 CI 门禁")
    lines.append("")
    lines.append(f"（生成时间：{time.strftime('%Y-%m-%d %H:%M')}，由 `python -m eval.golden_suggest` 产出）")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="从 agent_runs 挖掘 golden 候选")
    parser.add_argument("--limit", type=int, default=20, help="候选清单最多展示条数")
    parser.add_argument("--write", action="store_true", help="同时写入 eval/reports/golden_candidates.md")
    args = parser.parse_args()

    report = build_report(limit=args.limit)
    print(report)
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(report + "\n", encoding="utf-8")
        print(f"\n已写入: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

"""历史报告回溯打分：用 LLM-as-a-Judge 对历史 live 报告的 finalCanvas 补测 judge 分

背景：judge 是后来才实现的，历史报告里只有规则化 score，没有 judgeScore。
本脚本读取 backend/eval/reports/eval-live-*.json，对每条含画布的结果用
judge_run 补测，产出「规则分 vs 回溯 judge 分」对比表，得到 judge 基线
（解决"之前几分"没有记录的问题）。

运行（会真实调用 LLM，消耗少量 token）：
  cd backend && venv/Scripts/python.exe -m eval.judge_backfill
"""

import asyncio
import glob
import json
import logging
import sys
from pathlib import Path

from .judge import judge_run
from .tasks import get_eval_tasks

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BACKEND_DIR / "eval" / "reports"

logger = logging.getLogger("judge_backfill")


async def backfill() -> None:
    tasks_by_id = {t["id"]: t for t in get_eval_tasks()}

    print("===== 历史报告回溯 judge 打分 =====")
    print(f"{'报告时间':<18} | {'任务':<18} | {'规则分':>5} | {'回溯 judge 分':>10}")
    print("-" * 66)

    rows = []
    for report_path in sorted(glob.glob(str(REPORTS_DIR / "eval-live-*.json"))):
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        timestamp = Path(report_path).stem.replace("eval-live-", "")
        for result in report.get("results", []):
            task_id = result.get("taskId", "")
            task = tasks_by_id.get(task_id)
            if not task:
                logger.warning("跳过 %s: 找不到任务定义 %s", timestamp, task_id)
                continue
            # 已带 judgeScore 的报告（最新一次）跳过，避免重复调用
            if result.get("judgeScore") is not None:
                rows.append((timestamp, task_id, result.get("score"), result["judgeScore"], True))
                continue
            # 构造 judge_run 所需输入
            run = {
                "finalCanvas": result.get("finalCanvas") or [],
                "canvasStyle": result.get("canvasStyle") or task.get("canvasStyle") or {},
            }
            judged = await judge_run(task, run)
            jscore = judged["judgeScore"]
            rows.append((timestamp, task_id, result.get("score"), jscore, False))
            if jscore is not None:
                print(f"{timestamp:<18} | {task_id:<18} | {result.get('score', 0):>5} | {jscore:>10}")
            else:
                print(f"{timestamp:<18} | {task_id:<18} | {result.get('score', 0):>5} | {'(失败)':>10}")

    # 汇总：按任务聚合同一任务不同时刻的 judge 轨迹
    print("\n===== 按任务聚合（规则分 → 回溯 judge 分） =====")
    by_task: dict[str, list] = {}
    for timestamp, task_id, score, jscore, _ in rows:
        by_task.setdefault(task_id, []).append((timestamp, score, jscore))
    for task_id, runs in by_task.items():
        line = ", ".join(f"{ts[-11:-5]} 规则={s} judge={j}" if j is not None else f"{ts[-11:-5]} 规则={s} judge=?" for ts, s, j in runs)
        print(f"  {task_id:<24} {line}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(backfill())

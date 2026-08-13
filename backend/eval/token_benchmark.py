"""Token 成本基准：优化前后单次完整调用对比（可复跑）

度量对象：Agent 单次 LLM 调用的完整输入
  - 优化前：system prompt + 全量组件 JSON 直塞上下文
  - 优化后：system prompt + build_canvas_context（单行摘要 + token 预算截断）

数据来源：
  - 任务提示词：backend/eval/tasks.py 的 golden 任务
  - 画布组件：真实 live 评测报告中的 finalCanvas（100 分通过的那次，11 组件），
    按需复制扩展模拟不同画布规模

费用假设（命令行 --price-per-mtok / --price-out-per-mtok 覆盖；默认输入 1 元/百万 token，
输出按常见 1:3 定价默认 3 元/百万 token）：
  - 汇总同时输出两个口径：输入侧 token 降低、输入+输出总成本降低

运行：
  cd backend && venv/Scripts/python.exe -m eval.token_benchmark
"""

import argparse
import json
import sys
from pathlib import Path

from app.services.ai.component_utils import estimate_tokens, build_canvas_context
from app.services.ai.prompts import build_system_prompt

BACKEND_DIR = Path(__file__).resolve().parent.parent


def load_real_canvas() -> list:
    """从最近一次 100 分通过的 live 报告中提取真实 finalCanvas"""
    report = BACKEND_DIR / "eval" / "reports" / "eval-live-2026-08-11T17-23-51.json"
    with open(report, encoding="utf-8") as f:
        data = json.load(f)
    for result in data.get("results", []):
        if result.get("pass"):
            return result.get("finalCanvas") or []
    return []


def scale_canvas(base: list, target: int) -> list:
    """把真实画布复制扩展到目标组件数（保证样本真实、规模可控）"""
    if not base:
        return []
    out = []
    i = 0
    while len(out) < target:
        for c in base:
            cc = json.loads(json.dumps(c))
            cc["id"] = f"{cc['id']}_{len(out)}"
            out.append(cc)
            if len(out) >= target:
                break
    return out[:target]


def single_call_tokens(task, canvas, canvas_style) -> tuple[int, int]:
    """返回 (优化前 tokens, 优化后 tokens)：完整 system prompt + 用户消息"""
    width = int(canvas_style.get("width") or 375)
    height = int(canvas_style.get("height") or 667)

    # 优化前：全量组件 JSON 内联进画布上下文
    before_ctx = f"当前画布: {width}x{height}px\n画布上已有 {len(canvas)} 个组件:\n" + json.dumps(canvas, ensure_ascii=False)
    before_system = build_system_prompt("execute", before_ctx)
    before_user = task.get("prompt", "")
    before_total = estimate_tokens(before_system) + estimate_tokens(before_user)

    # 优化后：单行摘要 + token 预算
    after_ctx = build_canvas_context(canvas, width, height, canvas_style, project_knowledge="")
    after_system = build_system_prompt("execute", after_ctx)
    after_total = estimate_tokens(after_system) + estimate_tokens(before_user)

    return before_total, after_total


def main() -> None:
    parser = argparse.ArgumentParser(description="Token 成本基准（优化前后单次调用）")
    parser.add_argument("--price-per-mtok", type=float, default=1.0,
                        help="输入 token 单价（元/百万 token），默认 1.0（StepFun 输入价量级）")
    parser.add_argument("--price-out-per-mtok", type=float, default=3.0,
                        help="输出 token 单价（元/百万 token），默认 3.0（常见输入:输出 1:3 定价）")
    parser.add_argument("--scale", type=int, default=20,
                        help="典型生成流程的代表画布规模（默认 20 组件）")
    args = parser.parse_args()

    sys.path.insert(0, str(BACKEND_DIR))
    # 延迟导入，避免 argparse 阶段引入 app 依赖
    from eval.tasks import get_eval_tasks  # noqa: E402

    base = load_real_canvas()
    tasks = get_eval_tasks()
    task = tasks[0]  # poster_dance_recruit 街舞社招新海报
    canvas_style = task.get("canvasStyle") or {}

    print("===== Token 成本基准：优化前后单次完整调用 =====")
    print(f"任务: {task['name']} | 基准画布: 真实 live 报告 finalCanvas ({len(base)} 组件)")
    print(f"价格假设: 输入 {args.price_per_mtok} 元/M tok | 输出 {args.price_out_per_mtok} 元/M tok\n")

    print(f"{'画布组件数':>8} | {'优化前':>8} | {'优化后':>7} | {'降低':>6} | {'省/次(元)':>10}")
    print("-" * 58)
    for n in (11, 30, 60, 120):
        canvas = scale_canvas(base, n)
        before, after = single_call_tokens(task, canvas, canvas_style)
        reduction = (before - after) / before * 100 if before else 0
        saved = (before - after) * args.price_per_mtok / 1e6
        print(f"{n:>8} | {before:>7} tok | {after:>6} tok | {reduction:>5.1f}% | ¥{saved:>9.5f}")

    # 汇总：典型生成流程（discover→design→plan→confirm→execute 约 5 轮）
    # 输入侧：每轮都携带画布上下文
    # 输出侧：4 轮小输出（propose_options/confirm_plan 约 250 tok/轮）+ execute 的
    #         generate_page 全量组件 JSON（不受上下文截断影响）
    SMALL_OUTPUT_TOKENS = 250
    print("\n===== 典型生成流程成本估算（5 轮对话，双口径） =====")
    print(f"代表画布规模: {args.scale} 组件 | 输入价 {args.price_per_mtok} 元/M tok | 输出价 {args.price_out_per_mtok} 元/M tok")
    canvas = scale_canvas(base, args.scale)
    before_in, after_in = single_call_tokens(task, canvas, canvas_style)
    out_generate = estimate_tokens(json.dumps(canvas, ensure_ascii=False))
    out_total = 4 * SMALL_OUTPUT_TOKENS + out_generate

    # 口径 1：输入侧 token
    rounds = 5
    inp_before, inp_after = rounds * before_in, rounds * after_in
    inp_reduction = (inp_before - inp_after) / inp_before * 100

    # 口径 2：输入 + 输出总成本（按价计费）
    cost_before = inp_before * args.price_per_mtok / 1e6 + out_total * args.price_out_per_mtok / 1e6
    cost_after = inp_after * args.price_per_mtok / 1e6 + out_total * args.price_out_per_mtok / 1e6
    cost_reduction = (cost_before - cost_after) / cost_before * 100

    print(f"  输入侧 token:   {inp_before:>6} → {inp_after:>6} | 降低 {inp_reduction:.1f}%")
    print(f"  总成本(输入+输出): ¥{cost_before:.4f} → ¥{cost_after:.4f} | 降低 {cost_reduction:.1f}%")
    print(f"  （输出侧固定 {out_total} tok/流程，generate_page 全量 JSON 不受截断影响）")


if __name__ == "__main__":
    main()

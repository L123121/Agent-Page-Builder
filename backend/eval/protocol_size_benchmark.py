"""协议体积基准：扁平数组（parentId 引用） vs 嵌套结构（子组件内嵌）JSON 字节数对比

数据来源：真实 live 评测报告（100 分通过的街舞社招新海报，11 组件）的 finalCanvas，
并按项目 ComposeCommand 的语义模拟一次「组合」操作（2~4 个组件合成 Group），
生成含嵌套关系的页面后，用两种协议表达同一份页面对比体积。

协议说明（与项目实现对齐）：
  - 扁平数组：所有组件平铺在 componentData 数组中，父子关系用 parentId 引用
    （项目当前协议，README: "扁平数组 + parentId：兼顾操作效率与嵌套表达"）
  - 嵌套结构：Group 的子组件内嵌在 group.propValue 数组中，无需 parentId

运行：
  cd backend && venv/Scripts/python.exe -m eval.protocol_size_benchmark
"""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPORT = BACKEND_DIR / "eval" / "reports" / "eval-live-2026-08-11T17-23-51.json"

# 模拟组合的组件索引（前 4 个合成一个 Group，含标题/正文/按钮等）
GROUP_INDICES = (0, 1, 2, 3)


def load_real_canvas() -> list:
    with open(REPORT, encoding="utf-8") as f:
        data = json.load(f)
    for result in data.get("results", []):
        if result.get("pass"):
            return result.get("finalCanvas") or []
    raise RuntimeError("报告中未找到通过的画布")


def simulate_group(canvas: list) -> list:
    """把前 N 个组件合成一个 Group（语义同 ComposeCommand），返回扁平数组（含 Group + parentId 引用）"""
    grouped = [c for i, c in enumerate(canvas) if i in GROUP_INDICES]
    rest = [c for i, c in enumerate(canvas) if i not in GROUP_INDICES]

    group = {
        "id": "group_1",
        "component": "Group",
        "label": "组合",
        "icon": "qunzu",
        "propValue": [json.loads(json.dumps(c)) for c in grouped],
        "style": {"width": 300, "height": 200, "top": 60, "left": 37},
        "parentId": None,
        "slot": "default",
        "zIndex": 1,
        "animations": [],
        "events": {},
        "groupStyle": {},
        "isLock": False,
        "collapseName": "style",
        "linkage": {"duration": 0, "data": []},
    }
    # 扁平数组：Group 的子组件仍平铺在数组中，用 parentId 指向 group
    flat = [group] + rest
    for child in grouped:
        cc = json.loads(json.dumps(child))
        cc["parentId"] = "group_1"
        flat.append(cc)
    return flat


def to_nested(flat: list) -> list:
    """扁平数组 → 嵌套结构：子组件移入 Group.propValue，去掉 parentId/slot 冗余字段"""
    by_parent: dict[str, list] = {}
    for c in flat:
        by_parent.setdefault(c.get("parentId") or "", []).append(c)

    top = []
    for c in flat:
        if c.get("parentId"):
            continue  # 子组件已内嵌进父级 propValue
        cc = json.loads(json.dumps(c))
        children = by_parent.get(c["id"], [])
        if c.get("component") == "Group" and children:
            cc["propValue"] = children
        if "parentId" in cc:
            del cc["parentId"]  # 嵌套结构无需 parentId
        top.append(cc)
    return top


def fmt(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n/1024:.1f} KB"


def main() -> None:
    sys.path.insert(0, str(BACKEND_DIR))
    canvas = load_real_canvas()

    # 场景 1：真实画布原样（无 Group），扁平 vs 嵌套（仅差 parentId 字段）
    flat_raw = json.dumps(canvas, ensure_ascii=False, separators=(",", ":"))
    nested_raw = json.dumps(to_nested(canvas), ensure_ascii=False, separators=(",", ":"))
    raw_flat, raw_nested = len(flat_raw), len(nested_raw)

    # 场景 2：模拟组合出 Group 后，扁平（parentId 引用） vs 嵌套（子组件内嵌）
    flat_group = simulate_group(canvas)
    nested_group = to_nested(flat_group)
    g_flat = json.dumps(flat_group, ensure_ascii=False, separators=(",", ":"))
    g_nested = json.dumps(nested_group, ensure_ascii=False, separators=(",", ":"))

    print("===== 协议体积对比（真实页面数据，JSON 字节数） =====")
    print(f"数据源: 街舞社招新海报（真实 live 报告 finalCanvas，{len(canvas)} 组件）\n")

    print(f"场景 1（无 Group，仅差 parentId 冗余）:")
    print(f"  扁平数组: {fmt(raw_flat):>10}")
    print(f"  嵌套结构: {fmt(raw_nested):>10}")
    print(f"  嵌套更省: {raw_flat - raw_nested} B ({(1 - raw_nested / raw_flat) * 100:.1f}%)")

    print(f"\n场景 2（模拟组合：前 {len(GROUP_INDICES)} 个组件合成 Group）:")
    print(f"  扁平数组(+parentId): {fmt(len(g_flat)):>10}")
    print(f"  嵌套结构(内嵌子组件): {fmt(len(g_nested)):>10}")
    print(f"  嵌套更省: {len(g_flat) - len(g_nested)} B ({(1 - len(g_nested) / len(g_flat)) * 100:.1f}%)")

    print(f"\n===== 小结 =====")
    print(f"无 Group 页面：嵌套结构仅省去 parentId 字段，体积差异 {raw_flat - raw_nested} B")
    print(f"含 Group 页面：嵌套结构省去 parentId + 子组件独立条目，体积差异 {len(g_flat) - len(g_nested)} B")
    print("注：扁平数组在操作效率（增删改/图层排序）上更有优势，体积差异换取的是编辑能力")


if __name__ == "__main__":
    main()

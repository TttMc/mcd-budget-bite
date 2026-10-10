"""导出 demo 所需的候选集快照。

复用 solve.py 的候选构建逻辑（含套餐拆解与营养对齐），保证前端 demo
与命令行求解器结果完全一致。输出 demo_data.json。

用法：
    python scripts/export_demo_data.py --store 1450104 --offline
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import solve as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_NAMES = {
    "1450104": "上海黄浦悦荟广场餐厅",
    "1950526": "北京王府井餐厅",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="1450104")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    meals = S.load_meals(args.store, args.offline)
    nut = S.load_nutrition(args.offline)
    cands, dropped = S.build_candidates(meals, nut, args.store, args.offline)

    items = [{
        "n": c["name"],
        "p": c["price"],
        "k": c["kcal"],
        "pr": c["protein"],
        "f": c["fat"],
        "c": c["carb"],
        "s": c["sodium"],
        "ca": c["calcium"],
        "g": c.get("category", ""),
        "combo": S.is_combo(c["name"]),
    } for c in cands]

    tz = timezone(timedelta(hours=8))
    payload = {
        "store": args.store,
        "storeName": STORE_NAMES.get(args.store, args.store),
        "generatedAt": datetime.now(tz).strftime("%Y-%m-%d %H:%M"),
        "count": len(items),
        "dropped": len(dropped),
        "items": sorted(items, key=lambda x: (x["p"], x["k"])),
    }

    out = os.path.join(ROOT, "docs", "demo_data.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(out)
    print(f"已导出 {len(items)} 个候选 → {out}（{size/1024:.1f} KB）")
    print(f"排除 {len(dropped)} 项（营养数据缺失）")
    print(f"门店：{payload['storeName']}（{args.store}）")

    # 明细写到 stdout 便于核对
    for name, why in dropped[:10]:
        print(f"  排除：{name} — {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

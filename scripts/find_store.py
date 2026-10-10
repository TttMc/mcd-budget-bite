#!/usr/bin/env python3
"""查门店编码，供 solve.py 的 --store 使用。

用法：
    python find_store.py 上海市 南京东路
    python find_store.py 北京市 王府井 --limit 5

说明：query-nearby-stores 的 searchType=2 必须同时传 city 和 keyword，
只传一个会报 600058「城市名或者关键词不能为空」。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import call_tool  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="查询麦当劳门店编码")
    ap.add_argument("city", help="城市名，如 上海市")
    ap.add_argument("keyword", help="关键词，如 南京东路 / 人民广场")
    ap.add_argument("--limit", type=int, default=8, help="最多显示几条")
    args = ap.parse_args()

    res = call_tool("query-nearby-stores", {
        "beType": 1, "searchType": 2,
        "city": args.city, "keyword": args.keyword,
    })
    if not res.get("success"):
        print(f"查询失败：{res.get('message')}", file=sys.stderr)
        return 1

    stores = res.get("data") or []
    if not stores:
        print("没查到门店，换个关键词试试。", file=sys.stderr)
        return 1

    print(f"{'storeCode':<12}{'门店名称':<28}{'营业时间':<14}{'营业中'}")
    print("-" * 70)
    for s in stores[:args.limit]:
        code = s.get("storeCode", "")
        name = s.get("storeName", "")
        hours = f"{s.get('businessStartTime', '')}-{s.get('businessEndTime', '')}"
        open_flag = "是" if s.get("businessStatus") else "否"
        print(f"{code:<12}{name:<28}{hours:<14}{open_flag}")

    print()
    print(f"用法示例：python solve.py --store {stores[0].get('storeCode')} "
          f"--budget 30 --kcal 800")
    return 0


if __name__ == "__main__":
    sys.exit(main())

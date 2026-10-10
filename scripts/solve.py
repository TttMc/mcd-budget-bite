#!/usr/bin/env python3
"""麦麦预算餐盘 · 双约束求解器

在「预算上限」与「热量上限」双重约束下，枚举麦当劳在售餐品的组合，
输出三套方案 + 性价比天梯榜。

用法：
    export MCD_MCP_TOKEN=<token>
    python solve.py --store 1450104 --budget 30 --kcal 800
    python solve.py --budget 25 --kcal 700 --offline   # 只用本地缓存，不联网

数据完整性原则：匹配不到营养数据的餐品一律标注「营养数据缺失」并排除，
绝不猜测或套用近似值。
"""

import argparse
import json
import os
import sys
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import call_tool  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
MEALS_CACHE = os.path.join(DATA, "raw_meals.json")
NUT_CACHE = os.path.join(DATA, "raw_nutrition.json")
DETAIL_CACHE = os.path.join(DATA, "meal_details.json")

# 非食品（周边玩具 / 包装物等），直接从候选池剔除
NON_FOOD_KEYWORDS = ("按摩捶", "痒痒挠", "贴纸", "周边", "玩具", "徽章", "公仔",
                     "手提袋", "棒球帽", "雨伞", "袜子", "T恤")

# 套餐类命名特征：需要拆解子项才能算准营养
COMBO_KEYWORDS = ("件套", "套餐", "分享", "随心配", "乐园餐", "双拼", "全家桶",
                  "盒", "小食盘", "拼盘", "多人餐")

# 主食特征：一顿正餐至少得有一件咸食主食，否则会选出「新地 + 冰淇淋」这种甜品组合
STAPLE_KEYWORDS = ("堡", "汉堡", "卷", "麦满分", "粥", "饭", "鸡")

DAILY_SODIUM_REF = 2000  # 成人日均钠推荐上限（mg），用于贴士文案


# --------------------------------------------------------------------------
# 数据加载
# --------------------------------------------------------------------------

def load_meals(store: str, offline: bool) -> dict:
    """返回 {code: {name, price, originalPrice, category}}"""
    if offline and os.path.exists(MEALS_CACHE):
        raw = json.load(open(MEALS_CACHE, encoding="utf-8"))
    else:
        raw = call_tool("query-meals", {"storeCode": store, "orderType": 1, "beType": 1})
        if not raw.get("success"):
            raise SystemExit(f"拉取菜单失败: {raw.get('message')}")
        json.dump(raw, open(MEALS_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    data = raw["data"]
    meals = {}
    for cat in data.get("categories", []):
        cname = cat["name"].replace("\n", "")
        for m in cat["meals"]:
            code = m["code"]
            if code in meals:
                meals[code]["category"] += "/" + cname
                continue
            meals[code] = {"category": cname}
    for code, info in data.get("meals", {}).items():
        if code not in meals:
            meals[code] = {"category": "其他"}
        meals[code].update({
            "name": info.get("name", ""),
            "price": float(info.get("currentPrice") or 0),
            "originalPrice": float(info.get("originalPrice") or 0),
        })
    return {k: v for k, v in meals.items() if v.get("name")}


def load_nutrition(offline: bool) -> dict:
    """解析 list-nutrition-foods 的自定义分隔格式，返回 {品名: 营养dict}"""
    if offline and os.path.exists(NUT_CACHE):
        raw = json.load(open(NUT_CACHE, encoding="utf-8"))
    else:
        raw = call_tool("list-nutrition-foods", {})
        json.dump(raw, open(NUT_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    body = raw["data"].split(":\n", 1)[1]
    out = {}
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 9:
            continue
        name = ",".join(parts[: len(parts) - 8]).strip()
        v = parts[len(parts) - 8:]
        try:
            out[name] = {
                "energyKj": int(v[1]),
                "kcal": int(v[2]),
                "protein": float(v[3]),
                "fat": float(v[4]),
                "carb": float(v[5]),
                "sodium": int(v[6]),
                "calcium": int(v[7]),
            }
        except (ValueError, IndexError):
            continue
    return out


def load_details() -> dict:
    if os.path.exists(DETAIL_CACHE):
        return json.load(open(DETAIL_CACHE, encoding="utf-8"))
    return {}


def save_details(d: dict) -> None:
    json.dump(d, open(DETAIL_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------
# 营养匹配
# --------------------------------------------------------------------------

def match_nutrition(name: str, nut: dict):
    """严格匹配：只认完全相等（忽略空格与常见符号）。

    刻意不做模糊匹配——实测模糊匹配会把「巨无霸三件套」错配到「巨无霸」，
    而三件套还含薯条和可乐，热量差一倍以上。宁可标注缺失，也不能算错。
    """
    key = name.replace(" ", "").replace("　", "")
    if key in nut:
        return nut[key]
    for k, v in nut.items():
        if k.replace(" ", "") == key:
            return v
    return None


def is_combo(name: str) -> bool:
    return any(k in name for k in COMBO_KEYWORDS)


def is_non_food(name: str) -> bool:
    return any(k in name for k in NON_FOOD_KEYWORDS)


def _sum_nut(items: list) -> dict:
    tot = {"kcal": 0, "protein": 0.0, "fat": 0.0, "carb": 0.0, "sodium": 0, "calcium": 0}
    for n in items:
        for k in tot:
            tot[k] += n[k]
    return tot


def combo_nutrition(code: str, store: str, nut: dict, cache: dict, offline: bool):
    """拆解套餐 → 按默认子项累加营养。

    套餐本体在营养库里没有记录（营养库只收录单品），必须拆开累加。
    任一子项缺失营养数据则整个套餐判为缺失，避免低估。
    """
    if code in cache:
        detail = cache[code]
    elif offline:
        return None, None
    else:
        detail = call_tool("query-meal-detail", {
            "storeCode": store, "orderType": 1, "beType": 1, "code": code,
        })
        if not detail.get("success"):
            return None, None
        detail = detail.get("data") or {}
        cache[code] = detail

    rounds = detail.get("rounds") or []
    if not rounds:
        return None, None

    parts, missing = [], []
    for rd in rounds:
        qty_rd = rd.get("quantity") or 1
        for ch in rd.get("choices", []):
            if ch.get("isDefault") != 1:
                continue
            qty = (ch.get("quantity") or 0) * qty_rd
            if qty <= 0:
                continue
            n = match_nutrition(ch.get("name", ""), nut)
            if n is None:
                missing.append(ch.get("name", ""))
                continue
            parts.append({k: n[k] * qty for k in
                          ("kcal", "protein", "fat", "carb", "sodium", "calcium")})
    if missing:
        return None, missing
    if not parts:
        return None, None
    return _sum_nut(parts), []


# --------------------------------------------------------------------------
# 候选池构建
# --------------------------------------------------------------------------

def build_candidates(meals: dict, nut: dict, store: str, offline: bool,
                     include_combos: bool = True) -> tuple:
    """构建候选池。

    营养取值优先级：
      1. 单品名与营养库严格相等 —— 直接用
      2. 否则调用 query-meal-detail 拆解（套餐取各轮默认子项累加；
         杯型未指定的单品如「可乐」也走这条，自动解析出「可乐小杯」）
      3. 仍取不到 —— 记为缺失并排除，不做估算
    """
    cache = load_details()
    cands, dropped = [], []
    for code, m in meals.items():
        name = m["name"]
        if is_non_food(name):
            continue
        if is_combo(name) and not include_combos:
            continue

        n = match_nutrition(name, nut)
        source = "直接匹配"
        if n is None:
            n, _missing = combo_nutrition(code, store, nut, cache, offline)
            source = "拆解累加"
        if n is None:
            dropped.append((name, "营养数据缺失"))
            continue
        cands.append({"code": code, "name": name, "price": m["price"],
                      "category": m.get("category", ""), "source": source, **n})
    if not offline:
        save_details(cache)
    return cands, dropped


# --------------------------------------------------------------------------
# 求解
# --------------------------------------------------------------------------

def has_staple(items) -> bool:
    return any(any(k in c["name"] for k in STAPLE_KEYWORDS) for c in items)


def solve(cands: list, budget: float, kcal_limit: int, max_items: int = 3,
          require_staple: bool = True) -> list:
    """枚举 1..max_items 件组合，返回落在预算与热量双约束内的全部可行解。"""
    feasible = []
    for size in range(1, max_items + 1):
        for combo in combinations(cands, size):
            price = round(sum(c["price"] for c in combo), 2)
            if price > budget:
                continue
            kcal = sum(c["kcal"] for c in combo)
            if kcal > kcal_limit:
                continue
            if require_staple and not has_staple(combo):
                continue
            feasible.append({
                "items": combo,
                "price": price,
                "kcal": kcal,
                "protein": round(sum(c["protein"] for c in combo), 1),
                "fat": round(sum(c["fat"] for c in combo), 1),
                "carb": round(sum(c["carb"] for c in combo), 1),
                "sodium": sum(c["sodium"] for c in combo),
                "calcium": sum(c["calcium"] for c in combo),
            })
    return feasible


def pick_plans(feasible: list, min_kcal: int = 350) -> dict:
    """从可行解里挑三套：最饱 / 最省 / 最均衡。"""
    if not feasible:
        return {}
    meal_like = [f for f in feasible if f["kcal"] >= min_kcal] or feasible

    fullest = max(meal_like, key=lambda f: (f["kcal"], -f["price"]))
    cheapest = min(meal_like, key=lambda f: (f["price"], -f["kcal"]))

    def balance_score(f):
        # 蛋白质优先，钠超标按每 100mg 扣 1 分
        return f["protein"] - max(0, f["sodium"] - 1000) / 100.0
    balanced = max(meal_like, key=balance_score)

    return {"最饱型": fullest, "最省型": cheapest, "最均衡型": balanced}


def value_ladder(cands: list, top: int = 10, min_price: float = 3.0) -> list:
    """性价比天梯榜：每元热量 kcal/¥。

    只统计单品——套餐与多人份拼盘（如十翅拼盘）份量口径不同，混排没有可比性。
    """
    single = [c for c in cands
              if c["price"] >= min_price and not is_combo(c["name"])]
    ranked = sorted(single, key=lambda c: c["kcal"] / c["price"], reverse=True)
    return ranked[:top]


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

def tips(plan: dict) -> list:
    out = []
    if plan["sodium"] > 1200:
        out.append(f"本组合钠 {plan['sodium']}mg，约占日均参考值的 "
                   f"{round(plan['sodium'] / DAILY_SODIUM_REF * 100)}%，当天其余餐次建议清淡")
    if plan["fat"] > 35:
        out.append(f"脂肪 {plan['fat']}g 偏高，去掉酱料可省约 40～90 kcal")
    if plan["protein"] < 15:
        out.append("蛋白质偏低，加一份麦乐鸡或换板烧鸡腿堡可显著提升饱腹时长")
    if not out:
        out.append("本组合热量与钠均在合理区间，可放心作为一餐")
    return out


def render(plans: dict, ladder: list, budget: float, kcal_limit: int,
           n_cands: int, dropped: list) -> str:
    L = []
    L.append(f"预算 ¥{budget:g} ｜ 热量上限 {kcal_limit} kcal ｜ 候选 {n_cands} 项")
    L.append("")
    for label in ("最饱型", "最省型", "最均衡型"):
        p = plans.get(label)
        if not p:
            continue
        L.append(f"【{label}】 ¥{p['price']:g} ｜ {p['kcal']} kcal ｜ "
                 f"蛋白质 {p['protein']:g}g ｜ 钠 {p['sodium']}mg")
        for it in p["items"]:
            L.append(f"   · {it['name']}  ¥{it['price']:g} / {it['kcal']} kcal")
        kpy = p["kcal"] / p["price"] if p["price"] else 0
        ppy = p["protein"] / p["price"] if p["price"] else 0
        L.append(f"   每元热量 {kpy:.1f} kcal ｜ 每元蛋白质 {ppy:.2f} g")
        L.append("")
    if plans:
        main = plans.get("最均衡型") or plans.get("最饱型")
        L.append("💡 热量贴士")
        for t in tips(main):
            L.append(f"   · {t}")
        L.append("")
    L.append("📊 性价比天梯榜（每元热量 kcal/¥，仅统计单品）")
    L.append("   注：甜品常居榜首——每元热量高，但蛋白质和饱腹感都不划算")
    for i, c in enumerate(ladder, 1):
        L.append(f"  {i:2d}. {c['name']}  ¥{c['price']:g}  {c['kcal']} kcal  "
                 f"{c['kcal'] / c['price']:.1f} kcal/¥")
    if dropped:
        L.append("")
        L.append(f"（已排除 {len(dropped)} 项营养数据缺失的餐品，不做估算）")
    return "\n".join(L)


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="麦麦预算餐盘 · 双约束求解器")
    ap.add_argument("--store", default="1450104", help="门店编码")
    ap.add_argument("--budget", type=float, default=30.0, help="预算上限（元）")
    ap.add_argument("--kcal", type=int, default=800, help="热量上限（kcal）")
    ap.add_argument("--max-items", type=int, default=3, help="组合最多件数")
    ap.add_argument("--no-combos", action="store_true", help="排除套餐，只组合单品")
    ap.add_argument("--offline", action="store_true", help="只用本地缓存，不联网")
    args = ap.parse_args()

    meals = load_meals(args.store, args.offline)
    nut = load_nutrition(args.offline)
    cands, dropped = build_candidates(meals, nut, args.store, args.offline,
                                      not args.no_combos)
    if not cands:
        print("候选池为空，请检查门店编码或网络。", file=sys.stderr)
        return 1

    feasible = solve(cands, args.budget, args.kcal, args.max_items)
    if not feasible:
        print(f"在 ¥{args.budget:g} / {args.kcal} kcal 双约束下无可行组合，"
              f"请放宽预算或热量上限。", file=sys.stderr)
        return 1

    plans = pick_plans(feasible)
    ladder = value_ladder(cands)
    print(render(plans, ladder, args.budget, args.kcal, len(cands), dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())

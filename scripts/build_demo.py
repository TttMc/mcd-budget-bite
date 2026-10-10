"""把 demo 数据注入模板，产出单文件可离线运行的 demo/index.html。

用法：
    python scripts/build_demo.py

输入：demo/template.html + demo/demo_data.json
输出：demo/index.html（数据内联，双击即可打开，无需起服务）
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "docs", "template.html")
DATA = os.path.join(ROOT, "docs", "demo_data.json")
OUT = os.path.join(ROOT, "docs", "index.html")
PLACEHOLDER = "/*__DATA__*/{}"


def main() -> int:
    with open(TPL, encoding="utf-8") as f:
        html = f.read()
    with open(DATA, encoding="utf-8") as f:
        payload = f.read()

    if PLACEHOLDER not in html:
        raise SystemExit(f"模板缺少占位符：{PLACEHOLDER}")

    html = html.replace(PLACEHOLDER, payload)

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    print(f"已生成 {OUT}")
    print(f"  {os.path.getsize(OUT)/1024:.1f} KB · 内联 {len(json.loads(payload)['items'])} 个候选")
    print("  双击即可打开，无需联网或起本地服务")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""麦当劳 MCP 客户端（Streamable HTTP / JSON-RPC 2.0）

用法：
    export MCD_MCP_TOKEN=<你的 token>
    python mcp_client.py tools
    python mcp_client.py call now-time-info '{}'
    python mcp_client.py call query-nearby-stores '{"beType":1,"city":"上海市"}'

Token 只从环境变量读取，绝不写入仓库文件。
"""

import json
import os
import sys
import urllib.request
import urllib.error

ENDPOINT = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"


class McpError(Exception):
    pass


def _read_env_file() -> str | None:
    """从 .env 文件读取 Token，避免每次手动 export。

    查找顺序：脚本同级目录 → 项目根目录 → 用户主目录。
    .env 已加入 .gitignore，不会被提交到仓库。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(here, "..", ".env"),
        os.path.join(os.path.expanduser("~"), ".mcd_mcp_token"),
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("MCD_MCP_TOKEN="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except OSError:
            continue
    return None


def _token() -> str:
    tok = os.environ.get("MCD_MCP_TOKEN") or _read_env_file()
    if not tok:
        raise McpError(
            "未找到 MCP Token。二选一：\n"
            "  1) 环境变量：export MCD_MCP_TOKEN=<token>\n"
            "  2) 在 scripts/.env 写入一行：MCD_MCP_TOKEN=<token>\n"
            "Token 申请入口：https://open.mcd.cn/mcp"
        )
    return tok


def _post(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise McpError(f"HTTP {e.code}: {detail[:400]}") from e
    except urllib.error.URLError as e:
        raise McpError(f"网络错误: {e.reason}") from e

    text = raw.strip()
    # 部分响应以 SSE 形式返回，取最后一条 data: 事件
    if text.startswith("event:") or text.startswith("data:"):
        events = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = events[-1] if events else ""
    if not text:
        raise McpError(f"空响应: {raw[:200]}")
    return json.loads(text)


def initialize() -> dict:
    return _post({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcd-budget-bite", "version": "1.0.0"},
        },
    })


def list_tools() -> list:
    res = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    if "error" in res:
        raise McpError(json.dumps(res["error"], ensure_ascii=False))
    return res["result"]["tools"]


def _extract_json(text: str):
    """麦当劳 MCP 的返回是 markdown 说明 + 一段 '## Original Response' 下的原始 JSON，
    这里尽量把真正的业务 JSON 挖出来。"""
    marker = "## Original Response"
    idx = text.find(marker)
    if idx != -1:
        tail = text[idx + len(marker):]
    else:
        tail = text
    start = tail.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(tail)):
        ch = tail[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(tail[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def call_tool(name: str, arguments: dict | None = None) -> dict:
    """调用工具，返回解析后的业务数据（自动剥掉 MCP 的 content 文本外壳）。"""
    initialize()
    res = _post({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })
    if "error" in res:
        raise McpError(json.dumps(res["error"], ensure_ascii=False))
    result = res.get("result", {})
    if result.get("isError"):
        raise McpError(f"工具返回错误: {result}")

    content = result.get("content") or []
    parts = []
    for c in content:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
    text = "\n".join(parts).strip()
    if not text:
        return result
    parsed = _extract_json(text)
    if parsed is None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
    return parsed


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    try:
        if cmd == "tools":
            for t in list_tools():
                print(t["name"])
        elif cmd == "call":
            name = sys.argv[2]
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
            print(json.dumps(call_tool(name, args), ensure_ascii=False, indent=2))
        else:
            print(__doc__)
            return 1
    except McpError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""端到端自检：走真实 stdio 传输，把四个工具、两个资源、一个提示都跑一遍。

分两段：
  A. 用 SDK 的高层 Client（mode="2026-07-28"）验证功能；
  B. 用裸 subprocess + 手写 JSON-RPC 验证 stdout 里**只有**协议报文。

为什么要 B 段：功能全对但混进一行 print，客户端会整条连接报废，
而这种问题在单元测试里完全看不出来。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult, ReadResourceResult, TextContent, TextResourceContents

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTES_ROOT = PROJECT_ROOT / "sample_notes"

# 让 verify.py 能直接读项目代码来算期望值（样本断言不能再写死数字）。
sys.path.insert(0, str(PROJECT_ROOT))

from notes_mcp.notes.store import FilesystemNoteStore  # noqa: E402

# 恶意输入：三个都必须被拒绝，且返回可读说明
MALICIOUS = [
    "../../etc/passwd",
    "/etc/passwd",
    "C:\\Windows\\win.ini",
]

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "verify-script", "version": "0.1.0"},
}

_ok = 0
_fail = 0


def _sample_notes() -> list:
    """示例笔记的实际内容：断言的期望值都从这里算，不再写死"4 篇"这类数字，
    否则样本一变（加一篇笔记、换一个标签）自检就假失败。"""
    return FilesystemNoteStore(NOTES_ROOT.resolve()).load_all()


def _tool_text(result: CallToolResult) -> str:
    """工具返回的第一块内容必须是文本：mypy 层面 content 是联合类型，
    直接 .text 会漏掉非文本分支；这里显式断言，顺带防住未来的类型漂移。"""
    block = result.content[0]
    assert isinstance(block, TextContent), f"工具返回了非文本内容：{type(block)}"
    return block.text


def _text(block: object) -> str:
    """任意内容块必须是文本：mypy 层面 content 是联合类型。"""
    assert isinstance(block, TextContent), f"返回了非文本内容：{type(block)}"
    return block.text


def _resource_text(result: ReadResourceResult) -> str:
    """资源内容必须是文本：BlobResourceContents 没有 .text。"""
    item = result.contents[0]
    assert isinstance(item, TextResourceContents), f"资源返回了非文本内容：{type(item)}"
    return item.text


def check(label: str, condition: bool, detail: str = "") -> None:
    global _ok, _fail
    if condition:
        _ok += 1
        print(f"  [PASS] {label}")
    else:
        _fail += 1
        print(f"  [FAIL] {label}  {detail}")


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "notes_mcp", "--root", str(NOTES_ROOT)],
        cwd=str(PROJECT_ROOT),
    )


# --------------------------------------------------------------------------- #
# A. 功能验证
# --------------------------------------------------------------------------- #


async def part_a() -> None:
    print("\n=== A. 功能（SDK Client, mode=2026-07-28）===")
    async with Client(_server_params(), mode="2026-07-28") as client:
        print(f"  协议版本: {client.protocol_version}")

        tools = await client.list_tools()
        names = sorted(t.name for t in tools.tools)
        print(f"  工具列表: {names}")
        check(
            "四个工具都在",
            names == ["list_recent", "notes_stats", "read_note", "search_notes"],
            str(names),
        )

        # --- search_notes ---
        result = await client.call_tool("search_notes", {"query": "MCP", "limit": 3})
        text = _tool_text(result)
        print(f"\n  --- search_notes(query=MCP) 返回 {len(text)} 字符 ---")
        print("  " + text[:600].replace("\n", "\n  "))
        check("search 未报错", not result.is_error)
        check("search 返回片段（含行号）", "第 " in text and "行]" in text)
        check("search 未超预算", len(text) <= 8000, f"{len(text)} 字符")
        check("search 未返回整篇（不含笔记末尾标签行）", len(text) < 4000, f"{len(text)} 字符")

        # --- read_note ---
        result = await client.call_tool("read_note", {"path": "daily/2026-10-25.md"})
        text = _tool_text(result)
        print(f"\n  --- read_note(daily/2026-10-25.md) 返回 {len(text)} 字符 ---")
        print("  " + text[:300].replace("\n", "\n  "))
        check("read_note 成功", not result.is_error and "2026-10-25" in text)

        # --- list_recent ---
        result = await client.call_tool("list_recent", {"days": 7})
        text = _tool_text(result)
        print("\n  --- list_recent(days=7) ---\n  " + text[:500].replace("\n", "\n  "))
        check("list_recent 成功", not result.is_error)
        expected_recent = sum(
            1 for note in _sample_notes() if note.mtime >= time.time() - 7 * 86_400
        )
        check(
            f"list_recent 只返回 7 天内的 {expected_recent} 篇",
            f"{expected_recent} 篇" in text,
            text[:80],
        )

        # --- notes_stats ---
        result = await client.call_tool("notes_stats", {})
        text = _tool_text(result)
        print("\n  --- notes_stats ---\n  " + text.replace("\n", "\n  "))
        check("stats 成功", not result.is_error)
        expected_tags = len({tag for note in _sample_notes() for tag in note.tags})
        check("stats 解析出标签", f"标签数：{expected_tags}" in text, text[:200])

        # --- 恶意路径：三个用例全部拒绝 ---
        print("\n  --- 恶意路径（必须全部被拒绝且给出可读说明）---")
        for bad in MALICIOUS:
            result = await client.call_tool("read_note", {"path": bad})
            msg = _tool_text(result)
            print(f"    {bad!r:28} -> is_error={result.is_error}  {msg[:90]}")
            check(f"拒绝 {bad}", result.is_error)
            check(f"错误可读（非堆栈） {bad}", "Traceback" not in msg and len(msg) > 10)

        # --- 资源 ---
        print("\n  --- Resources ---")
        index = await client.read_resource("notes://index")
        payload = json.loads(_resource_text(index))
        print(
            f"    notes://index -> count={payload['count']} "
            f"returned={payload['returned']} truncated={payload['truncated']}"
        )
        expected_count = len(_sample_notes())
        check(
            "index 是合法 JSON 且条目数正确",
            payload["count"] == expected_count,
            str(payload["count"]),
        )

        note = await client.read_resource("notes://note/daily/2026-10-26.md")
        body = _resource_text(note)
        print(
            f"    notes://note/daily/2026-10-26.md -> {len(body)} 字符, "
            f"mime={note.contents[0].mime_type}"
        )
        check("单篇资源可读", "2026-10-26" in body)

        # --- Prompt ---
        print("\n  --- Prompt ---")
        prompt = await client.get_prompt("weekly-review", {"topic": "MCP"})
        message = _text(prompt.messages[0].content)
        print("  " + message[:400].replace("\n", "\n  "))
        check("prompt 含 topic", "MCP" in message)
        check("prompt 指定了工具", "list_recent" in message and "search_notes" in message)


# --------------------------------------------------------------------------- #
# B. stdout 纯净度
# --------------------------------------------------------------------------- #


def part_b() -> None:
    print("\n=== B. stdout 纯净度（裸 JSON-RPC）===")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": META}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"_meta": META, "name": "notes_stats", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/read",
         "params": {"_meta": META, "uri": "notes://index"}},
    ]

    proc = subprocess.Popen(
        [sys.executable, "-m", "notes_mcp", "--root", str(NOTES_ROOT), "--log-level", "WARNING"],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    captured: list[str] = []

    def drain_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            captured.append(line)

    reader = threading.Thread(target=drain_stdout, daemon=True)
    reader.start()

    assert proc.stdin is not None
    for request in requests:
        proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    deadline = time.time() + 20
    while len(captured) < len(requests) and time.time() < deadline:
        time.sleep(0.05)

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    reader.join(timeout=5)

    bad_lines = []
    for line in captured:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            bad_lines.append(stripped)

    stdout_lines = [line for line in captured if line.strip()]
    print(f"  stdout 行数: {len(stdout_lines)}，非 JSON 行数: {len(bad_lines)}")
    for line in bad_lines[:5]:
        print(f"    非协议输出: {line[:120]}")

    check("stdout 每行都是合法 JSON-RPC", not bad_lines)
    check("四条请求都收到响应", len(stdout_lines) >= len(requests),
          f"收到 {len(captured)} 行")

    if proc.stderr is not None:
        err = proc.stderr.read()
        if err.strip():
            print("  stderr（应只有日志，不能有 traceback）:")
            for line in err.strip().splitlines()[:8]:
                print("    " + line)
            check("stderr 无 traceback", "Traceback" not in err)


def main() -> int:
    if not NOTES_ROOT.is_dir():
        print(f"找不到示例笔记目录：{NOTES_ROOT}")
        return 2
    anyio.run(part_a)
    part_b()
    print(f"\n=== 汇总：{_ok} 项通过，{_fail} 项失败 ===")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

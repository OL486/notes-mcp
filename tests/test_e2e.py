"""端到端：真的起一个子进程，走 stdio + JSON-RPC。

这层测试的价值在于覆盖"协议翻译"这一段：纯逻辑单测证明不了
`ToolError` 会不会变成 isError、资源模板会不会匹配、stdout 会不会被污染。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import anyio
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import TextContent, TextResourceContents

MODERN = "2026-07-28"


def _text(block: object) -> str:
    """内容块必须是文本：mypy 层面 content 是联合类型，直接 .text 会漏掉分支。"""
    assert isinstance(block, TextContent), f"返回了非文本内容：{type(block)}"
    return block.text


def _resource_text(contents: Sequence[object]) -> str:
    item = contents[0]
    assert isinstance(item, TextResourceContents), f"资源返回了非文本内容：{type(item)}"
    return item.text

META = {
    "io.modelcontextprotocol/protocolVersion": MODERN,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "0.1.0"},
}


def _params(root: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "notes_mcp", "--root", str(root)]
    )


def test_modern_client_sees_all_primitives(notes_root: Path) -> None:
    async def scenario() -> None:
        async with Client(_params(notes_root), mode=MODERN) as client:
            assert client.protocol_version == MODERN

            tools = sorted(t.name for t in (await client.list_tools()).tools)
            assert tools == ["list_recent", "notes_stats", "read_note", "search_notes"]

            resources = [r.uri for r in (await client.list_resources()).resources]
            assert "notes://index" in resources

            templates = [
                t.uri_template
                for t in (await client.list_resource_templates()).resource_templates
            ]
            assert "notes://note/{+path}" in templates

            prompts = [p.name for p in (await client.list_prompts()).prompts]
            assert "weekly-review" in prompts

    anyio.run(scenario)


def test_tool_errors_are_structured(notes_root: Path) -> None:
    """恶意路径 → isError=True + 可读文本，而不是 JSON-RPC 层报错或进程崩掉。"""

    async def scenario() -> None:
        async with Client(_params(notes_root), mode=MODERN) as client:
            for bad in ("../../secret.md", "/etc/passwd", "daily/nope.md"):
                result = await client.call_tool("read_note", {"path": bad})
                assert result.is_error is True, bad
                message = _text(result.content[0])
                assert "Traceback" not in message
                assert len(message) > 10

    anyio.run(scenario)


def test_resources_and_prompt_roundtrip(notes_root: Path) -> None:
    async def scenario() -> None:
        async with Client(_params(notes_root), mode=MODERN) as client:
            payload = json.loads(_resource_text((await client.read_resource("notes://index")).contents))
            assert payload["count"] == 3

            body = _resource_text((await client.read_resource("notes://note/daily/2026-10-25.md")).contents)
            assert "tools/call" in body

            prompt = await client.get_prompt("weekly-review", {"topic": "MCP"})
            text = _text(prompt.messages[0].content)
            assert "MCP" in text and "search_notes" in text

    anyio.run(scenario)


def test_legacy_client_still_works(notes_root: Path) -> None:
    """2025 时代走 initialize 握手的客户端也必须能用——SDK 负责兼容，这里只验证结论。"""

    async def scenario() -> None:
        async with Client(_params(notes_root), mode="legacy") as client:
            assert client.protocol_version != MODERN
            tools = [t.name for t in (await client.list_tools()).tools]
            assert "search_notes" in tools

    anyio.run(scenario)


def test_stdout_contains_only_jsonrpc(notes_root: Path) -> None:
    """stdio 的铁律：stdout 只能有协议报文，一行杂音都不行。"""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": META}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"_meta": META, "name": "notes_stats", "arguments": {}}},
    ]

    proc = subprocess.Popen(
        [sys.executable, "-m", "notes_mcp", "--root", str(notes_root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    captured: list[str] = []

    def drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            captured.append(line)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()

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
    thread.join(timeout=5)

    lines = [line for line in captured if line.strip()]
    assert len(lines) >= len(requests)
    for line in lines:
        json.loads(line)  # 任何非 JSON 行都会在这里炸掉


@pytest.mark.parametrize("days", [1, 7, 30])
def test_list_recent_filters_by_days(notes_root: Path, days: int) -> None:
    async def scenario() -> None:
        async with Client(_params(notes_root), mode=MODERN) as client:
            result = await client.call_tool("list_recent", {"days": days})
            assert not result.is_error
            assert "最近" in _text(result.content[0])

    anyio.run(scenario)

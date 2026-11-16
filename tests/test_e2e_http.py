"""端到端：streamable-http 传输。

stdio 的 e2e（test_e2e.py）只覆盖"协议翻译"这一段，HTTP 这边一直是裸奔的：
`--transport`/`--host`/`--port`/`--stateless-http` 的接线只在 test_main.py
里用假对象 mock 过一次，真实请求从来没跑过。一旦 SDK 升级改了会话行为
（`mcp` 锁定 2.3.0，`pyproject` 允许 `<3`），第一个发现的人会是真实用户。

这里真的起子进程、真的走 HTTP：

- 有会话模式：initialize 会发 `Mcp-Session-Id`，之后不带 session 的请求
  必须被 400 拒绝（SDK 的 `Bad Request: Missing session ID`）。
- 无状态模式（`--stateless-http`）：不带 session 的请求必须能通。

只测默认 127.0.0.1，不测 0.0.0.0 绑定（本服务无认证，README 已警告勿绑）。
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.types import TextContent, TextResourceContents

MODERN = "2026-07-28"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(block: object) -> str:
    """内容块必须是文本：mypy 层面 content 是联合类型，直接 .text 会漏掉分支。"""
    assert isinstance(block, TextContent), f"返回了非文本内容：{type(block)}"
    return block.text


def _resource_text(contents: object) -> str:
    assert isinstance(contents, list) and contents, "资源返回为空"
    item = contents[0]
    assert isinstance(item, TextResourceContents), f"资源返回了非文本内容：{type(item)}"
    return item.text


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_log_tail(log_path: Path, lines: int = 20) -> str:
    if not log_path.exists():
        return "<no server log>"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


@contextmanager
def _http_server(
    root: Path, log_path: Path, *, stateless: bool
) -> Iterator[tuple[subprocess.Popen[bytes], int]]:
    """起一个真实的 streamable-http 子进程，退出时关掉它。

    端口用 bind(0) 拿到的空闲端口，避免与本机其他服务冲突；
    就绪用 TCP 轮询判断（uvicorn 监听即就绪），而不是固定 sleep。
    """
    port = _free_port()
    args = [
        sys.executable, "-m", "notes_mcp",
        "--root", str(root),
        "--transport", "streamable-http",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    if stateless:
        args.append("--stateless-http")

    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            args, cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=log
        )
        try:
            deadline = time.time() + 20
            while time.time() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(
                        "HTTP 服务器启动即退出：\n" + _server_log_tail(log_path)
                    )
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError(
                    "HTTP 服务器 20s 内未监听：\n" + _server_log_tail(log_path)
                )
            yield proc, port
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


def _raw_post(
    port: int, payload: dict[str, object], session_id: str | None
) -> tuple[int, bytes, http.client.HTTPMessage | None]:
    """不带 SDK 的裸 JSON-RPC POST：专门用来测会话头行为。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("POST", "/mcp", body=json.dumps(payload), headers=headers)
        response = conn.getresponse()
        return response.status, response.read(), response.msg
    finally:
        conn.close()


def _initialize(port: int) -> str:
    """裸 initialize：有会话模式下拿回 session id；无状态模式下返回空串。"""
    status, _, headers = _raw_post(port, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": MODERN, "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0.1.0"},
        },
    }, None)
    assert status == 200, f"initialize 应 200，实际 {status}"
    if headers is None:
        return ""
    session_id = headers.get("Mcp-Session-Id")
    return session_id if isinstance(session_id, str) else ""


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def test_http_lists_tools_and_searches(notes_root: Path, tmp_path: Path) -> None:
    """有会话模式下走一遍正常路径：tools/list + search_notes + 资源。"""

    async def scenario() -> None:
        async with Client(_url(port), mode=MODERN) as client:
            assert client.protocol_version == MODERN

            tools = sorted(t.name for t in (await client.list_tools()).tools)
            assert tools == [
                "list_notes",
                "list_recent",
                "notes_stats",
                "read_note",
                "search_notes",
            ]

            result = await client.call_tool("search_notes", {"query": "MCP"})
            assert not result.is_error
            assert "MCP" in _text(result.content[0])

            payload = json.loads(
                _resource_text((await client.read_resource("notes://index")).contents)
            )
            assert payload["count"] == 3

    with _http_server(notes_root, tmp_path / "server.log", stateless=False) as (_, port):
        anyio.run(scenario)


def test_http_tool_errors_are_structured(notes_root: Path, tmp_path: Path) -> None:
    """HTTP 下的错误映射：恶意路径 → isError=True + 可读文本，不泄漏 Traceback。"""

    async def scenario() -> None:
        async with Client(_url(port), mode=MODERN) as client:
            result = await client.call_tool("read_note", {"path": "../../secret.md"})
            assert result.is_error is True
            message = _text(result.content[0])
            assert "Traceback" not in message
            assert len(message) > 10

    with _http_server(notes_root, tmp_path / "server.log", stateless=False) as (_, port):
        anyio.run(scenario)


def test_http_requires_session_id(notes_root: Path, tmp_path: Path) -> None:
    """有会话模式：initialize 发 session id，之后不带它的请求必须 400。"""
    with _http_server(notes_root, tmp_path / "server.log", stateless=False) as (_, port):
        session_id = _initialize(port)
        assert session_id, "有会话模式下 initialize 必须返回 Mcp-Session-Id"

        status, body, _ = _raw_post(port, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }, None)
        assert status == 400, f"不带 session 的请求应 400，实际 {status}：{body[:200]!r}"
        assert b"Missing session ID" in body

        status, body, _ = _raw_post(port, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {},
        }, session_id)
        assert status == 200, f"带 session 的请求应 200，实际 {status}：{body[:200]!r}"


def test_stateless_http_works_without_session(notes_root: Path, tmp_path: Path) -> None:
    """无状态模式：不带 session 的请求必须能通，SDK 客户端也能正常走完流程。"""
    with _http_server(notes_root, tmp_path / "server.log", stateless=True) as (_, port):
        status, body, _ = _raw_post(port, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        }, None)
        assert status == 200, f"无状态模式下不带 session 应 200，实际 {status}：{body[:200]!r}"

        async def scenario() -> None:
            async with Client(_url(port), mode=MODERN) as client:
                tools = [t.name for t in (await client.list_tools()).tools]
                assert "search_notes" in tools
                result = await client.call_tool("search_notes", {"query": "MCP"})
                assert not result.is_error
                assert "MCP" in _text(result.content[0])

        anyio.run(scenario)

"""__main__.py 的直接单测：参数解析与启动前置检查。

原来入口完全没有单测：根目录不存在返回 2、--version、--transport
非法值这些分支只靠手测。真正起 server 的部分用假对象替掉，
只验证 main() 把参数翻译成正确的 run() 调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from notes_mcp.__main__ import main


def test_missing_root_returns_2(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path / "不存在")]) == 2


def test_missing_root_via_env_returns_2(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("NOTES_MCP_ROOT", str(tmp_path / "不存在"))
    assert main([]) == 2


def test_version_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


def test_invalid_transport_exits_with_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--transport", "grpc"])
    assert excinfo.value.code != 0


def test_invalid_port_exits_with_error() -> None:
    """H2：--port 超出 1-65535 时 argparse 就拒绝，不要等到运行时才炸。"""
    for bad_port in ("0", "65536", "99999", "abc"):
        with pytest.raises(SystemExit) as excinfo:
            main(["--port", bad_port])
        assert excinfo.value.code != 0


def test_stdio_run_is_called(notes_root: Path, monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeServer:
        def run(self, transport: str, **kwargs: object) -> None:
            calls.append((transport, kwargs))

    monkeypatch.setattr(
        "notes_mcp.__main__.create_server", lambda settings: FakeServer()
    )
    assert main(["--root", str(notes_root)]) == 0
    assert calls == [("stdio", {})]


def test_streamable_http_passes_host_port_and_stateless(
    notes_root: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeServer:
        def run(self, transport: str, **kwargs: object) -> None:
            calls.append((transport, kwargs))

    monkeypatch.setattr(
        "notes_mcp.__main__.create_server", lambda settings: FakeServer()
    )
    assert main([
        "--root", str(notes_root),
        "--transport", "streamable-http",
        "--host", "127.0.0.1",
        "--port", "8123",
        "--stateless-http",
    ]) == 0
    assert calls == [
        ("streamable-http", {"host": "127.0.0.1", "port": 8123, "stateless_http": True})
    ]


def test_root_from_env_is_used(notes_root: Path, monkeypatch: MonkeyPatch) -> None:
    """--root 省略时走 NOTES_MCP_ROOT，能正常启动即说明解析对了。"""
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeServer:
        def run(self, transport: str, **kwargs: object) -> None:
            calls.append((transport, kwargs))

    monkeypatch.setenv("NOTES_MCP_ROOT", str(notes_root))
    monkeypatch.setattr(
        "notes_mcp.__main__.create_server", lambda settings: FakeServer()
    )
    assert main([]) == 0
    assert calls == [("stdio", {})]

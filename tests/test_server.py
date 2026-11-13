"""server.py 的直接单测：注册清单与异常翻译。

原来 server 层完全没有单测：工具/资源/提示的注册靠 test_e2e 的
子进程往返间接覆盖，list_recent / notes_stats / build_index 的
异常翻译更是没有任何覆盖——裸 OSError 会直接漏成堆栈。

这里用 MCPServer 的进程内调用（await server.call_tool / read_resource），
不走 stdio 子进程：快，而且能用 monkeypatch 精确触发各路异常。
"""

from __future__ import annotations

# 注意：notes_mcp.services 包的 __init__ 把同名函数 read_note 导到了包属性上，
# `import notes_mcp.services.read_note as x` 会拿到函数而不是模块；
# 用 import_module 拿 sys.modules 里的真正模块对象。
import importlib

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.types import TextContent

from notes_mcp.config import Settings
from notes_mcp.safety import PathRejected
from notes_mcp.server import create_server

read_note_service = importlib.import_module("notes_mcp.services.read_note")


def _server(settings: Settings):
    return create_server(settings)


def _text(block: object) -> str:
    """内容块必须是文本：mypy 层面 content 是联合类型，直接 .text 会漏掉分支。"""
    assert isinstance(block, TextContent), f"返回了非文本内容：{type(block)}"
    return block.text


# --------------------------------------------------------------------------- #
# 注册清单
# --------------------------------------------------------------------------- #


def test_registration_lists_all_primitives(settings: Settings) -> None:
    async def scenario() -> None:
        server = _server(settings)
        tools = sorted(t.name for t in await server.list_tools())
        assert tools == ["list_recent", "notes_stats", "read_note", "search_notes"]

        resources = [r.uri for r in await server.list_resources()]
        assert resources == ["notes://index"]

        templates = [t.uri_template for t in await server.list_resource_templates()]
        assert templates == ["notes://note/{+path}"]

        prompts = [p.name for p in await server.list_prompts()]
        assert prompts == ["weekly-review"]

    anyio.run(scenario)


# --------------------------------------------------------------------------- #
# 工具成功路径（进程内调用）
# --------------------------------------------------------------------------- #


def test_call_tool_success(settings: Settings) -> None:
    async def scenario() -> None:
        server = _server(settings)
        result = await server.call_tool("search_notes", {"query": "MCP", "limit": 3})
        assert "MCP" in _text(result.content[0])

        result = await server.call_tool("read_note", {"path": "daily/2026-10-25.md"})
        assert "tools/call" in _text(result.content[0])

        result = await server.call_tool("list_recent", {"days": 7})
        assert "最近" in _text(result.content[0])

        result = await server.call_tool("notes_stats", {})
        assert "笔记总数" in _text(result.content[0])

    anyio.run(scenario)


def test_read_resource_and_prompt_success(settings: Settings) -> None:
    async def scenario() -> None:
        server = _server(settings)
        contents = await server.read_resource("notes://index")
        assert '"count": 3' in contents[0].content

        contents = await server.read_resource("notes://note/daily/2026-10-25.md")
        assert "tools/call" in contents[0].content

        prompt = await server.get_prompt("weekly-review", {"topic": "MCP"})
        assert "MCP" in prompt.messages[0].content.text

    anyio.run(scenario)


# --------------------------------------------------------------------------- #
# 异常翻译：工具
# --------------------------------------------------------------------------- #


def test_search_notes_rejects_empty_query(settings: Settings) -> None:
    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ToolError, match="query 不能为空"):
            await server.call_tool("search_notes", {"query": "   "})

    anyio.run(scenario)


def test_read_note_path_rejected_becomes_tool_error(settings: Settings) -> None:
    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ToolError):
            await server.call_tool("read_note", {"path": "../../secret.md"})

    anyio.run(scenario)


def test_read_note_oserror_race_becomes_tool_error(settings: Settings, monkeypatch) -> None:
    """校验与读盘之间的竞态：文件被删，OSError 要翻译成可读错误。"""

    class BoomStore:
        def __init__(self, root):
            pass

        def load_note(self, target):
            raise OSError("文件被删除")

    monkeypatch.setattr(
        read_note_service, "make_store", lambda settings: BoomStore(settings.root)
    )

    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ToolError, match="读取失败"):
            await server.call_tool("read_note", {"path": "daily/2026-10-25.md"})

    anyio.run(scenario)


def test_list_recent_oserror_becomes_tool_error(settings: Settings, monkeypatch) -> None:
    import notes_mcp.server as server_module

    def boom(settings, days=7):
        raise OSError("磁盘读失败")

    monkeypatch.setattr(server_module.tool_impl, "run_list_recent", boom)

    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ToolError, match="磁盘读失败"):
            await server.call_tool("list_recent", {"days": 7})

    anyio.run(scenario)


def test_notes_stats_oserror_becomes_tool_error(settings: Settings, monkeypatch) -> None:
    import notes_mcp.server as server_module

    def boom(settings):
        raise OSError("磁盘读失败")

    monkeypatch.setattr(server_module.tool_impl, "run_stats", boom)

    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ToolError, match="磁盘读失败"):
            await server.call_tool("notes_stats", {})

    anyio.run(scenario)


def test_notes_stats_value_error_becomes_tool_error(settings: Settings, monkeypatch) -> None:
    import notes_mcp.server as server_module

    def boom(settings):
        raise ValueError("预算非法")

    monkeypatch.setattr(server_module.tool_impl, "run_stats", boom)

    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ToolError, match="预算非法"):
            await server.call_tool("notes_stats", {})

    anyio.run(scenario)


# --------------------------------------------------------------------------- #
# 异常翻译：资源
# --------------------------------------------------------------------------- #


def test_build_index_oserror_becomes_resource_not_found(settings: Settings, monkeypatch) -> None:
    import notes_mcp.server as server_module

    def boom(settings):
        raise OSError("索引读失败")

    monkeypatch.setattr(server_module, "build_index", boom)

    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ResourceNotFoundError, match="索引读失败"):
            await server.read_resource("notes://index")

    anyio.run(scenario)


def test_note_resource_path_rejected_becomes_resource_not_found(settings: Settings) -> None:
    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ResourceNotFoundError):
            await server.read_resource("notes://note/../../secret.md")

    anyio.run(scenario)


def test_note_resource_oserror_becomes_resource_not_found(settings: Settings, monkeypatch) -> None:
    import notes_mcp.server as server_module

    def boom(settings, path):
        raise OSError("文件被删除")

    monkeypatch.setattr(server_module, "read_note_resource", boom)

    async def scenario() -> None:
        server = _server(settings)
        with pytest.raises(ResourceNotFoundError, match="读取失败"):
            await server.read_resource("notes://note/daily/2026-10-25.md")

    anyio.run(scenario)


# --------------------------------------------------------------------------- #
# services 层：OSError 竞态转 PathRejected
# --------------------------------------------------------------------------- #


def test_read_note_service_converts_oserror_to_path_rejected(
    settings: Settings, monkeypatch
) -> None:
    """services.read_note 直接调 load_note 抛 OSError 时，应转 PathRejected
    而不是让裸 OSError 漏出去。"""

    class BoomStore:
        def __init__(self, root):
            pass

        def load_note(self, target):
            raise OSError("文件被删除")

    monkeypatch.setattr(read_note_service, "make_store", lambda settings: BoomStore(settings.root))

    with pytest.raises(PathRejected, match="读取失败"):
        read_note_service.read_note(settings, "daily/2026-10-25.md", advice="重试。")

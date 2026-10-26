"""把工具、资源、提示注册到一个 MCPServer 实例上。

为什么写成 create_server(settings) 工厂函数而不是模块级单例：
1. 测试可以反复创建互不干扰的实例（不同根目录、不同预算）；
2. 和 TS 侧 `serveStdio(createServer, ...)` 的工厂约定保持一致，
   两套实现的心智模型不打架；
3. 未来若要在 Streamable HTTP 下做"每客户端一个实例"，直接复用这个函数即可。
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError

from . import __version__
from . import prompts as prompt_impl
from . import tools as tool_impl
from .config import Settings
from .resources import INDEX_URI, NOTE_URI_TEMPLATE, build_index, read_note_resource
from .safety import PathRejected
from .tools import QueryRejected

SERVER_NAME = "notes-mcp"

INSTRUCTIONS = """\
这是一个只读的本地 Markdown 笔记服务，不会写入、修改或删除任何文件。

使用顺序建议：
1. 不确定有哪些笔记时，先读 `notes://index` 或调用 `list_recent`；
2. 需要找内容时调用 `search_notes`，它返回的是命中行附近的**片段**，不是整篇；
3. 片段不够用时，再用 `read_note` 精确读取某一篇。

所有返回都有字符预算上限。看到"[已截断]"字样时，说明还有内容没返回，
请缩小 query / limit / days 再试，不要假设自己已经看到了全部内容。
"""


def create_server(settings: Settings) -> MCPServer:
    """组装并返回一个可直接 run() 的 MCPServer。"""
    server = MCPServer(
        name=SERVER_NAME,
        version=__version__,
        title="本地笔记（只读）",
        instructions=INSTRUCTIONS,
        # 只在真的出问题时才打日志：stdio 下 stderr 会被客户端收进日志面板，
        # INFO 级别的流水账会淹没真正的错误。
        log_level="WARNING",
    )

    _register_tools(server, settings)
    _register_resources(server, settings)
    _register_prompts(server)
    return server


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


def _register_tools(server: MCPServer, settings: Settings) -> None:
    """四个工具。

    description 是写给**模型**看的，不是写给用户看的：说清"什么时候该用我"、
    "我返回什么形态"、"我的上限是多少"，模型的调用正确率会明显不同。
    structured_output=False：这些工具的产出本来就是给人/模型读的文本，
    再包一层 {"result": "..."} 的 structuredContent 只会让报文变大。
    """

    @server.tool(
        name="search_notes",
        description=(
            "按关键词全文检索本地笔记，返回命中行前后各若干行的**片段**（每篇最多 3 段），"
            f"总长度不超过 {settings.search_budget} 字符。"
            "适合先定位再精读；不要用它读整篇笔记，那是 read_note 的职责。"
        ),
        structured_output=False,
    )
    def search_notes(query: str, limit: int = 5) -> str:
        """query: 关键词（中英文子串匹配，大小写不敏感）；limit: 最多返回几篇笔记的片段。"""
        try:
            return tool_impl.run_search(settings, query, limit).text
        except QueryRejected as exc:
            # 参数错误是"可预期的失败"，用 ToolError 让客户端收到 isError=true +
            # 可读文本，模型能据此改写参数重试；抛裸异常只会得到一句
            # "Error executing tool search_notes"，模型学不到任何东西。
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="read_note",
        description=(
            "读取单篇笔记的完整正文。path 必须是相对笔记根目录的路径（如 daily/2026-10-01.md），"
            f"超过 {settings.max_note_chars} 字符会截断并在末尾标注。"
            "绝对路径、.. 和指向根目录外的符号链接都会被拒绝。"
        ),
        structured_output=False,
    )
    def read_note(path: str) -> str:
        """path: 相对笔记根目录的 Markdown 路径。"""
        try:
            return tool_impl.run_read_note(settings, path).text
        except PathRejected as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="list_recent",
        description=(
            "列出最近 N 天内修改过的笔记（相对路径 + 修改时间 + 首行标题），"
            "按修改时间倒序。适合回答'上周我写了什么'这类问题。"
        ),
        structured_output=False,
    )
    def list_recent(days: int = 7) -> str:
        """days: 回溯天数，1-3650，默认 7。"""
        return tool_impl.run_list_recent(settings, days).text

    @server.tool(
        name="notes_stats",
        description="返回笔记总数、总字数、标签分布（解析正文里的 #tag）和最近修改时间。用于先摸清语料规模。",
        structured_output=False,
    )
    def notes_stats() -> str:
        return tool_impl.run_stats(settings)


# --------------------------------------------------------------------------- #
# Resources
# --------------------------------------------------------------------------- #


def _register_resources(server: MCPServer, settings: Settings) -> None:
    """一个静态资源 + 一个资源模板。

    `notes://index` 是静态 URI，客户端可以直接列出来；
    `notes://note/{+path}` 是 RFC 6570 模板，`{+path}` 里的 `+` 表示"保留斜杠"，
    否则 `daily/2026-10-01.md` 里的 `/` 会被当成 URI 路径分隔符而不是参数内容。
    """

    @server.resource(
        INDEX_URI,
        name="notes-index",
        title="笔记索引",
        description="全部笔记的清单（URI、路径、标题、修改时间、字数、标签），JSON 格式。",
        mime_type="application/json",
    )
    def notes_index() -> str:
        return build_index(settings)

    @server.resource(
        NOTE_URI_TEMPLATE,
        name="note",
        title="单篇笔记",
        description="按相对路径读取单篇笔记正文，例如 notes://note/daily/2026-10-01.md。",
        mime_type="text/markdown",
    )
    def note_by_path(path: str) -> str:
        try:
            return read_note_resource(settings, path)
        except PathRejected as exc:
            # 资源读取失败没有 isError 通道，只能走 JSON-RPC error。
            # ResourceNotFoundError 会映射成 -32602（invalid params），
            # 比笼统的 -32603 更能让客户端判断"是路径错了"而不是"服务器炸了"。
            raise ResourceNotFoundError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #


def _register_prompts(server: MCPServer) -> None:
    @server.prompt(
        name=prompt_impl.WEEKLY_REVIEW,
        title="本周回顾",
        description="总结本周关于某个主题的所有笔记，输出 3 条带出处的要点。",
    )
    def weekly_review(topic: str) -> str:
        """topic: 要回顾的主题关键词。"""
        return prompt_impl.weekly_review(topic)

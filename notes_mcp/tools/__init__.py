"""四个 Tool 的实现（原 notes_mcp/tools.py 的拆分）。

这一层是**纯逻辑**：只依赖 Settings 和文件系统，不认识 MCP。
好处是可以在 pytest 里直接调用，不需要起 server、不需要走 JSON-RPC；
server.py 只负责把异常翻译成协议层面的错误。

分层：
    search.py   search_notes 的纯逻辑
    read.py     read_note 的薄包装（唯一实现在 services.read_note）
    recent.py   list_recent 的纯逻辑
    stats.py    notes_stats 的纯逻辑
    common.py   _clamp / _fmt_time 等共用小工具
"""

from __future__ import annotations

from .read import ReadOutcome, run_read_note
from .recent import RecentOutcome, run_list_recent
from .search import QueryRejected, SearchOutcome, run_search
from .stats import run_stats

__all__ = [
    "QueryRejected",
    "ReadOutcome",
    "RecentOutcome",
    "SearchOutcome",
    "run_list_recent",
    "run_read_note",
    "run_search",
    "run_stats",
]

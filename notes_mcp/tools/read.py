"""read_note：读单篇全文。

唯一实现在 notes_mcp.services.read_note；这里只是薄包装，
传入 Tool 侧的截断提示文案。
"""

from __future__ import annotations

from ..config import Settings
from ..services.read_note import ReadOutcome, read_note


def run_read_note(settings: Settings, path: str) -> ReadOutcome:
    """读单篇全文，超过 max_note_chars 截断并标注。"""
    return read_note(
        settings,
        path,
        advice="请用 search_notes 定位关键段落，或读取这篇笔记对应的 notes:// URI 分段查看。",
    )


__all__ = ["ReadOutcome", "run_read_note"]

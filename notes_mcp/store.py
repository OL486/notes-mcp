"""兼容层（已废弃）。

原 `store.py` 已拆分为 `notes_mcp.notes` 包：
models / scan / parse / search / store。
本模块只做 re-export，新代码请直接从 `notes_mcp.notes` 导入。
一个版本后删除。
"""

from __future__ import annotations

import warnings

from .notes import (
    ALLOWED_SUFFIXES,
    SKIP_DIRS,
    TAG_RE,
    FilesystemNoteStore,
    Fragment,
    Note,
    NoteHit,
    NoteStore,
    count_units,
    decode_bytes,
    extract_tags,
    extract_title,
    iter_note_files,
    make_store,
    render_hit,
    search_notes,
)

warnings.warn(
    "notes_mcp.store 已废弃，请从 notes_mcp.notes 导入",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ALLOWED_SUFFIXES",
    "SKIP_DIRS",
    "TAG_RE",
    "FilesystemNoteStore",
    "Fragment",
    "Note",
    "NoteHit",
    "NoteStore",
    "count_units",
    "decode_bytes",
    "extract_tags",
    "extract_title",
    "iter_note_files",
    "make_store",
    "render_hit",
    "search_notes",
]

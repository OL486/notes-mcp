"""笔记的扫描、解析、检索与存储（原 notes_mcp/store.py 的拆分）。

分层：
    models.py   Note / Fragment / NoteHit 数据模型
    scan.py     扫描候选笔记文件 + 后缀白名单
    parse.py    标题 / 标签 / 字数等纯文本解析
    search.py   子串检索 + 片段合并 + 渲染
    store.py    NoteStore 协议 + 朴素文件系统实现
"""

from __future__ import annotations

from .models import Fragment, Note, NoteHit
from .parse import TAG_RE, count_units, decode_bytes, extract_tags, extract_title
from .scan import ALLOWED_SUFFIXES, SKIP_DIRS, iter_note_files
from .search import render_hit, search_notes
from .store import FilesystemNoteStore, NoteStore, load_all, load_note

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
    "load_all",
    "load_note",
    "render_hit",
    "search_notes",
]

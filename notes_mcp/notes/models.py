"""笔记的数据模型：Note / Fragment / NoteHit。

只放数据，不放扫描、解析、检索逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Note:
    path: Path
    rel: str
    """相对根目录的 posix 风格路径，例如 `daily/2026-10-01.md`。对外一律用它。"""
    title: str
    mtime: float
    text: str
    tags: tuple[str, ...]
    units: int
    """字数：CJK 字符数 + 拉丁词数。比 len(text) 更接近真实"内容量"。"""


@dataclass(frozen=True, slots=True)
class Fragment:
    start: int
    """0-based 起始行号。"""
    end: int
    """0-based 结束行号（含）。"""
    lines: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"第 {self.start + 1}-{self.end + 1} 行"


@dataclass(frozen=True, slots=True)
class NoteHit:
    note: Note
    fragments: tuple[Fragment, ...]
    hit_lines: int
    """命中行数，用来排序：命中多的笔记更可能是模型要的。"""

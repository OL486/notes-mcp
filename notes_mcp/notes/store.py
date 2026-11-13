"""笔记存储：读盘的抽象与朴素的文件系统实现。

这里刻意用**朴素实现**：每次调用都重新 rglob 一遍目录、把文件全读进内存。
理由：几百到几千篇笔记时它足够快（毫秒级），而且没有索引失效、增量更新、
缓存一致性这些额外状态。S1 文档里给了 10 万篇时的改造方向。

调用方只依赖 `NoteStore` 协议，不直接碰文件系统：后续换成缓存或
倒排索引（例如 SQLite FTS5）时，只需新增一个实现类，不用改 tools / resources。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config import Settings
from ..errors import PathRejected
from .models import Note
from .parse import count_units, decode_bytes, extract_tags, extract_title
from .scan import iter_note_files


def make_store(settings: Settings) -> FilesystemNoteStore:
    """按 Settings 建一个文件系统存储。调用方统一走这里，不要直接
    `FilesystemNoteStore(settings.root)`——以后换实现时只改这一处。"""
    return FilesystemNoteStore(settings.root)


class NoteStore(Protocol):
    """笔记存储的最小接口：全量加载与单篇加载。"""

    def load_all(self) -> list[Note]:
        """全量加载。朴素实现的核心：一次调用 = 一次全目录读盘。"""
        ...

    def load_note(self, path: Path) -> Note:
        """读盘 + 解析成 Note。path 必须是根目录内的绝对路径。"""
        ...


class FilesystemNoteStore:
    """朴素的文件系统实现：每次调用都重新扫描并读盘。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load_note(self, path: Path) -> Note:
        # 二次校验：直接调 load_note 的调用方可能绕过 resolve_note_path，
        # 这里再确认一次解析后的真实路径仍在根目录内（符号链接逃逸）。
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self.root.resolve()):
            raise PathRejected(
                f"路径越界：{path} 解析后落在笔记根目录之外",
                "只允许笔记根目录内的相对路径（符号链接指向外部同样会被拒绝）",
            )
        text = decode_bytes(path.read_bytes())
        rel = path.relative_to(self.root).as_posix()
        return Note(
            path=path,
            rel=rel,
            title=extract_title(text, path.stem),
            mtime=path.stat().st_mtime,
            text=text,
            tags=extract_tags(text),
            units=count_units(text),
        )

    def load_all(self) -> list[Note]:
        notes: list[Note] = []
        for path in iter_note_files(self.root):
            try:
                notes.append(self.load_note(path))
            except (OSError, PathRejected):
                # 单篇读失败（权限、文件被占用）不该让整个检索失败。
                # PathRejected 在这里只可能来自扫描与读取之间的竞态
                # （符号链接目标被换成根外文件），同样跳过该篇即可。
                continue
        return notes

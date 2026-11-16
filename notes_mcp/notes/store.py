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
from ..errors import NoteTooLargeError, PathRejected
from .models import Note
from .parse import _split_frontmatter, count_units, decode_bytes, extract_tags, extract_title
from .scan import iter_note_files

MAX_NOTE_BYTES = 10 * 1024 * 1024
"""单篇笔记大小上限（10 MiB）：超过的不读进内存，直接跳过。

截断只发生在返回时（max_note_chars），读盘本身原来没有上限：
一篇几百 MB 的 .md 误入根目录，每次 search / list_recent 都要全量读它。
上限是"跳过"而不是"截断读前 10MB"——半篇笔记的标题/标签/字数全是错的，
还不如不进索引，stats 里会报告跳过了几篇。"""


def make_store(settings: Settings) -> FilesystemNoteStore:
    """按 Settings 建一个文件系统存储。调用方统一走这里，不要直接
    `FilesystemNoteStore(settings.root)`——以后换实现时只改这一处。

    根目录不存在时直接报错，而不是静默返回空库：search 会说"已扫描 0 篇"、
    stats 会说"笔记根目录为空"，用户会误以为笔记是空的而非路径配错了。
    用 FileNotFoundError（OSError 子类）：server 层六个 handler
    （search/read_note/recent/stats/index/note）都接 OSError，
    PathRejected 反而只有 read_note 与 note 资源两处接——
    用它这里会在四个工具上漏成裸堆栈。
    """
    if not settings.root.is_dir():
        raise FileNotFoundError(
            f"笔记根目录不存在：{settings.root}。"
            "请检查 --root / NOTES_MCP_ROOT 是否配对。"
        )
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
        # 最近一次 load_all() 里因超大而跳过的文件数；每次 load_all 开始时清零。
        # run_stats 读它来报告"超大文件已跳过 N 篇"。
        self.skipped_oversized = 0
        # 根目录在一次调用内是不变的，但 load_note 每篇都要 resolve() 一次
        # （系统调用 + 路径规范化）。这里缓存一次复用。
        # 注意不能直接把 self.root 换成 resolved：load_note 里
        # path.relative_to(self.root) 依赖的正是调用方传进来的原始根路径
        # （根本身是符号链接时，扫描返回的路径仍以原始根为前缀）。
        self._resolved_root = root.resolve()

    def load_note(self, path: Path, *, light: bool = False) -> Note:
        """读盘 + 解析成 Note。path 必须是根目录内的绝对路径。

        light=True 时跳过 `tags` / `units` 解析（返回空标签与 0 字数）：
        search / list_recent 只用标题与正文，全量解析每篇要多花约一半时间。
        轻量 Note 的 rel / title / mtime / text 与全量完全一致。
        """
        # 二次校验：直接调 load_note 的调用方可能绕过 resolve_note_path，
        # 这里再确认一次解析后的真实路径仍在根目录内（符号链接逃逸）。
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self._resolved_root):
            raise PathRejected(
                f"路径越界：{path} 解析后落在笔记根目录之外",
                "只允许笔记根目录内的相对路径（符号链接指向外部同样会被拒绝）",
            )
        rel = path.relative_to(self.root).as_posix()
        st = path.stat()
        if st.st_size > MAX_NOTE_BYTES:
            # 先 stat 再读：超大文件不读进内存。NoteTooLargeError 是 OSError 子类，
            # load_all 会单独捕获计数，read_note 服务会转成友好报错。
            raise NoteTooLargeError(rel, st.st_size, MAX_NOTE_BYTES)
        text = decode_bytes(path.read_bytes())
        return Note(
            path=path,
            rel=rel,
            title=extract_title(text, path.stem),
            mtime=st.st_mtime,
            text=text,
            tags=() if light else extract_tags(text),
            # 字数只算剥离 frontmatter 后的正文：块里的 title/tags 是元数据，
            # 算进"总字数"会让 stats 虚高（长标题尤其明显）。
            units=0 if light else count_units(_split_frontmatter(text).body),
        )

    def load_all(self, *, light: bool = False) -> list[Note]:
        self.skipped_oversized = 0
        notes: list[Note] = []
        for path in iter_note_files(self.root):
            try:
                notes.append(self.load_note(path, light=light))
            except NoteTooLargeError:
                # 超大文件跳过该篇并计数（在 stats 里报告），不让整次检索失败。
                self.skipped_oversized += 1
                continue
            except (OSError, PathRejected):
                # 单篇读失败（权限、文件被占用）不该让整个检索失败。
                # PathRejected 在这里只可能来自扫描与读取之间的竞态
                # （符号链接目标被换成根外文件），同样跳过该篇即可。
                continue
        return notes

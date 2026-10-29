"""笔记的扫描、解析与检索。

这里刻意用**朴素实现**：每次调用都重新 rglob 一遍目录、把文件全读进内存。
理由：几百到几千篇笔记时它足够快（毫秒级），而且没有索引失效、增量更新、
缓存一致性这些额外状态。S1 文档里给了 10 万篇时的改造方向。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .safety import ALLOWED_SUFFIXES

SKIP_DIRS = frozenset({".git", ".obsidian", ".trash", "node_modules", "__pycache__", ".venv"})
"""这些目录里的文件不是"笔记"，扫进来只会污染统计和检索结果。"""

TAG_RE = re.compile(r"(?<![\w#])#([\w\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)")
r"""匹配正文里的 `#tag` / `#中文标签` / `#a/b`。

`(?<![\w#])` 这个前向断言是关键：Markdown 标题 `# 标题` 里 `#` 后面跟空格，
不会命中；但 `##二级标题` 这类漏写空格的写法会命中，所以解析前先把标题行剔掉。
"""

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
"""判定"这是标题行"的严格规则：`#` 后面必须跟空白。

不能用 `line.startswith("#")`——那会把整行标签 `#mcp #protocol` 当成标题剔掉，
标签统计会直接归零（这个 bug 第一版就踩了）。
"""

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


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


# --------------------------------------------------------------------------- #
# 扫描与解析
# --------------------------------------------------------------------------- #


def iter_note_files(root: Path) -> list[Path]:
    """列出根目录下所有候选笔记文件，按路径排序保证输出稳定。

    排序很重要：不稳定顺序会让同一查询两次返回不同结果，模型会以为数据变了。
    """
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        # 只看父级目录：文件名以 . 开头也算隐藏文件，一并跳过。
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if rel_parts[-1].startswith("."):
            continue
        found.append(path)
    found.sort(key=lambda p: p.relative_to(root).as_posix())
    return found


def decode_bytes(data: bytes) -> str:
    """按 utf-8 → gb18030 → 有损 utf-8 的顺序解码。

    中文 Windows 上老笔记常是 GBK/GB18030；直接用 Path.read_text() 会抛
    UnicodeDecodeError 让整个工具调用失败，为了一篇乱码笔记赔上整次检索不值得。
    """
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_title(text: str, fallback: str) -> str:
    """取首行标题：第一个 `#` 标题行；没有标题就用第一行非空内容。"""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            return title or fallback
        return stripped[:80]
    return fallback


def extract_tags(text: str) -> tuple[str, ...]:
    """解析正文里的 #tag，剔除代码块与标题行后再匹配。

    不去掉代码块的话，笔记里贴一段 `# 注释` 或 shell 的 `# TODO` 都会被算成标签。
    """
    cleaned = _strip_fenced_code(text)
    tags: set[str] = set()
    for line in cleaned.splitlines():
        if _HEADING_RE.match(line):
            continue
        for match in TAG_RE.finditer(line):
            tag = match.group(1).rstrip("/-")
            if tag:
                tags.add(tag)
    return tuple(sorted(tags))


def _strip_fenced_code(text: str) -> str:
    """把 ``` / ~~~ 围起来的代码块替换成空行，保留行数以便行号仍然对得上。

    如果文件结束时代码块未闭合（例如 ``` 开头但没有结尾），
    将未闭合代码块起始行及之后的所有内容保留为普通文本，
    避免标签提取因格式瑕疵而完全失效。
    """
    lines = text.splitlines()
    out: list[str] = []
    fence: str | None = None
    fence_start = -1

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                fence_start = i
                out.append("")
                continue
            out.append(line)
        else:
            if stripped.startswith(fence):
                fence = None
            out.append("")

    # 文件结束时代码块未闭合：恢复从最后一个未闭合代码块开始的所有内容
    if fence is not None and fence_start >= 0:
        for i in range(fence_start, len(lines)):
            out[i] = lines[i]

    return "\n".join(out)


def count_units(text: str) -> int:
    """CJK 字符按字算，拉丁文本按词算。中英混排笔记用 len() 会严重失真。"""
    return len(_CJK_RE.findall(text)) + len(_WORD_RE.findall(text))


def load_note(root: Path, path: Path) -> Note:
    """读盘 + 解析成 Note。root 只用来算相对路径。"""
    text = decode_bytes(path.read_bytes())
    rel = path.relative_to(root).as_posix()
    return Note(
        path=path,
        rel=rel,
        title=extract_title(text, path.stem),
        mtime=path.stat().st_mtime,
        text=text,
        tags=extract_tags(text),
        units=count_units(text),
    )


def load_all(root: Path) -> list[Note]:
    """全量加载。朴素实现的核心：一次调用 = 一次全目录读盘。"""
    notes: list[Note] = []
    for path in iter_note_files(root):
        try:
            notes.append(load_note(root, path))
        except OSError:
            # 单篇读失败（权限、文件被占用）不该让整个检索失败。
            continue
    return notes


# --------------------------------------------------------------------------- #
# 片段化检索
# --------------------------------------------------------------------------- #


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


def search_notes(
    notes: list[Note],
    query: str,
    *,
    fragments_per_note: int,
    context_lines: int,
    max_fragment_lines: int = 15,
) -> list[NoteHit]:
    """子串检索（大小写不敏感），把命中行合并成带上下文的片段。

    朴素实现就是逐行 `in` 判断。不引入分词/倒排索引的原因：笔记量小的时候
    子串匹配的召回率反而更高（中文没有空格，子串比"分词"更不容易漏），
    而且零依赖、零状态。
    """
    needle = query.strip().lower()
    if not needle:
        return []

    hits: list[NoteHit] = []
    for note in notes:
        lines = note.text.splitlines()
        matched = [i for i, line in enumerate(lines) if needle in line.lower()]
        if not matched:
            continue

        windows = _merge_windows(matched, len(lines), context_lines, max_fragment_lines)
        fragments = tuple(
            Fragment(start=start, end=end, lines=tuple(lines[start : end + 1]))
            for start, end in windows[:fragments_per_note]
        )
        hits.append(NoteHit(note=note, fragments=fragments, hit_lines=len(matched)))

    # 命中行多优先；同分时最近修改的优先。
    hits.sort(key=lambda h: (-h.hit_lines, -h.note.mtime, h.note.rel))
    return hits


def _merge_windows(
    matched: list[int],
    total_lines: int,
    context: int,
    max_lines: int,
) -> list[tuple[int, int]]:
    """把命中行扩展成 ±context 行的窗口，合并重叠窗口，并限制单个窗口的行数。

    两条规则都是为了不让"片段"退化成"整篇"：

    - 不合并重叠窗口的话，一段连续 5 行都命中的笔记会返回 5 个几乎一样的片段，
      白白吃掉三份预算。
    - 不限行长的话，一篇 200 行全命中的笔记会合成一个 200 行的巨型片段，
      它既塞不进预算（最后返回 0 个片段），也不符合"片段"的语义。
    """
    windows: list[tuple[int, int]] = []
    for index in matched:
        start = max(0, index - context)
        end = min(total_lines - 1, index + context)
        if windows:
            prev_start, prev_end = windows[-1]
            merged_end = max(prev_end, end)
            if start <= prev_end + 1 and merged_end - prev_start + 1 <= max_lines:
                windows[-1] = (prev_start, merged_end)
                continue
        windows.append((start, end))
    return windows


def render_hit(hit: NoteHit) -> str:
    """把一个 NoteHit 渲染成模型友好的文本块。

    行号是刻意的：模型看到 `第 42-46 行` 之后，如果需要更多上下文，
    可以自己判断该不该再 read_note，而不是盲猜。
    """
    head = f"### {hit.note.rel}  ·  {hit.note.title}\n"
    body = []
    for fragment in hit.fragments:
        body.append(f"[{fragment.label}]\n")
        for offset, line in enumerate(fragment.lines):
            body.append(f"{fragment.start + offset + 1:>5} | {line}\n")
    return head + "".join(body) + "\n"

"""片段化检索：子串检索 + 命中行合并成带上下文的片段 + 渲染。"""

from __future__ import annotations

from .models import Fragment, Note, NoteHit


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

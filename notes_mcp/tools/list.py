"""list_notes：按修改时间倒序翻页列出全部笔记。"""

from __future__ import annotations

from dataclasses import dataclass

from ..budget import fit_blocks
from ..config import Settings
from ..notes.store import make_store
from ..safety import resolve_note_dir
from .common import _clamp, _fmt_time


@dataclass(frozen=True, slots=True)
class ListOutcome:
    text: str
    count: int
    """本页实际返回的条目数（可能因预算截断少于本页条目数）。"""
    total: int
    """dir 过滤后的笔记总数。"""
    offset: int
    """实际使用的 offset（负数会被夹到 0）。"""
    has_more: bool
    """本页之后是否还有笔记。"""
    truncated: bool


def run_list_notes(
    settings: Settings, offset: int = 0, limit: int = 20, dir: str = ""
) -> ListOutcome:
    """按修改时间倒序翻页列出笔记：路径 + 修改时间 + 首行标题。

    notes://index 是唯一的清单入口，但它按预算裁剪、没有翻页——
    200 篇笔记只返回 37 条，剩下的没有任何办法拿到。这个工具就是
    补那条路的：offset/limit 翻页，dir 按目录过滤。

    参数语义与 read_note 分页的 offset/limit 保持同一套名字；
    排序与 notes://index 一致，按 mtime 倒序。
    """
    prefix = resolve_note_dir(settings.root, dir)

    # 轻量加载：清单只用路径、mtime 与标题，tags / units 解析跳过。
    notes = make_store(settings).load_all(light=True)
    notes.sort(key=lambda n: n.mtime, reverse=True)
    if prefix:
        notes = [n for n in notes if n.rel.startswith(prefix + "/")]

    total = len(notes)
    limit = _clamp(limit, 1, settings.max_limit, default=20)
    offset = _clamp(offset, 0, total, default=0)

    if total == 0:
        scope = f"目录 {prefix} 下" if prefix else "笔记根目录"
        return ListOutcome(
            text=(
                f"{scope}没有笔记。\n"
                "建议：检查 dir 是否写对，或先用 notes_stats 确认笔记总数。"
            ),
            count=0,
            total=0,
            offset=0,
            has_more=False,
            truncated=False,
        )

    if offset >= total:
        return ListOutcome(
            text=(
                f"已到末尾：共 {total} 篇笔记，"
                f"从第 {offset + 1} 篇起没有更多笔记。\n"
                "建议：把 offset 调小，例如 0。"
            ),
            count=0,
            total=total,
            offset=offset,
            has_more=False,
            truncated=False,
        )

    page = notes[offset : offset + limit]
    has_more = offset + len(page) < total
    next_offset = offset + len(page)
    footer = (
        f"\n还有 {total - next_offset} 篇未列出，"
        f"调用 list_notes(offset={next_offset}, limit={limit}) 继续翻页。"
        if has_more
        else ""
    )

    blocks = [
        f"- {note.rel}\n  {_fmt_time(note.mtime)}  ·  {note.title}\n" for note in page
    ]
    header = f"笔记清单：第 {offset + 1}–{next_offset} 篇（共 {total} 篇）\n\n"
    # 翻页提示本身也算预算：先给它留出长度，否则提示会把输出顶出预算；
    # 预算截断时不追加 footer——被截掉的条目还没返回，footer 里的
    # next_offset 会跳过它们，宁可让模型按截断提示减小 limit 重试。
    text, returned, truncated = fit_blocks(
        blocks,
        settings.list_budget - len(footer) if has_more else settings.list_budget,
        header=header,
        overflow_advice="请减小 limit 后重试，或改用更大的 offset 翻页。",
    )
    if has_more and not truncated:
        text += footer
    return ListOutcome(
        text=text,
        count=returned,
        total=total,
        offset=offset,
        has_more=has_more,
        truncated=truncated,
    )

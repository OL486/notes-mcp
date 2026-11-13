"""notes_stats：笔记总数、总字数、标签分布。"""

from __future__ import annotations

from collections import Counter

from ..budget import clip_with_notice
from ..config import Settings
from ..notes.store import make_store
from .common import _fmt_time


def run_stats(settings: Settings) -> str:
    """笔记总数、总字数、标签分布。用于让模型先摸清语料规模再决定检索策略。"""
    notes = make_store(settings).load_all()
    if not notes:
        return "笔记根目录为空。\n请检查目录是否正确，或先放入 .md 文件。"

    total_units = sum(n.units for n in notes)
    tag_counter: Counter[str] = Counter()
    untagged = 0
    for note in notes:
        if note.tags:
            tag_counter.update(note.tags)
        else:
            untagged += 1

    newest = max(notes, key=lambda n: n.mtime)
    lines = [
        f"笔记总数：{len(notes)} 篇",
        f"总字数：{total_units:,}（CJK 按字、拉丁按词）",
        f"标签数：{len(tag_counter)}",
    ]
    if tag_counter:
        lines.append("标签分布（前 20）：")
        for tag, count in tag_counter.most_common(20):
            lines.append(f"  #{tag}  {count} 篇")
        if len(tag_counter) > 20:
            lines.append(f"  …另有 {len(tag_counter) - 20} 个标签未显示")
    lines.append(f"未打标签：{untagged} 篇")
    lines.append(f"最近修改：{newest.rel}（{_fmt_time(newest.mtime)}）")

    text, _ = clip_with_notice(
        "\n".join(lines),
        settings.stats_budget,
        "标签过多，建议改用 search_notes 按具体标签检索。",
    )
    return text

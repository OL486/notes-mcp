"""list_recent：列出最近 N 天修改过的笔记。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..budget import fit_blocks
from ..config import Settings
from ..notes.store import make_store
from .common import _clamp, _fmt_time


@dataclass(frozen=True, slots=True)
class RecentOutcome:
    text: str
    count: int
    truncated: bool


def run_list_recent(settings: Settings, days: int = 7) -> RecentOutcome:
    """列出最近 N 天修改过的笔记。文件名 + 修改时间 + 首行标题。"""
    days = _clamp(days, 1, 3650, default=7)
    cutoff = time.time() - days * 86_400

    notes = make_store(settings).load_all()
    recent = [n for n in notes if n.mtime >= cutoff]
    recent.sort(key=lambda n: n.mtime, reverse=True)

    if not recent:
        return RecentOutcome(
            text=(
                f"最近 {days} 天内没有笔记被修改（共 {len(notes)} 篇）。\n"
                "建议：把 days 调大，例如 30 或 365。"
            ),
            count=0,
            truncated=False,
        )

    blocks = [
        f"- {note.rel}\n  {_fmt_time(note.mtime)}  ·  {note.title}\n" for note in recent
    ]
    header = f"最近 {days} 天内修改的笔记：{len(recent)} 篇（全部 {len(notes)} 篇）\n\n"
    text, returned, truncated = fit_blocks(
        blocks,
        settings.recent_budget,
        header=header,
        overflow_advice="请缩小 days 范围。",
    )
    return RecentOutcome(text=text, count=returned, truncated=truncated)

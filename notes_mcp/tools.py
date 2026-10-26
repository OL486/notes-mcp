"""四个 Tool 的实现。

这一层是**纯逻辑**：只依赖 Settings 和文件系统，不认识 MCP。
好处是可以在 pytest 里直接调用，不需要起 server、不需要走 JSON-RPC；
server.py 只负责把异常翻译成协议层面的错误。
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from .budget import clip_with_notice, fit_blocks
from .config import Settings
from .safety import resolve_note_path
from .store import load_all, load_note, render_hit, search_notes


class QueryRejected(ValueError):
    """参数不合法（空 query、越界 limit）。和 PathRejected 一样，消息要可读可纠正。"""


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    text: str
    notes_matched: int
    notes_returned: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    text: str
    total_chars: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class RecentOutcome:
    text: str
    count: int
    truncated: bool


# --------------------------------------------------------------------------- #
# search_notes
# --------------------------------------------------------------------------- #


def run_search(settings: Settings, query: str, limit: int = 5) -> SearchOutcome:
    """全文检索，返回**片段**而不是整篇。

    返回整篇是最省事也最有害的实现：3 篇 5KB 的笔记就是 15K 字符，
    而模型真正需要的往往只有命中那几行。
    """
    needle = (query or "").strip()
    if not needle:
        raise QueryRejected("query 不能为空，请给出要检索的关键词（支持中英文子串）。")

    limit = _clamp(limit, 1, settings.max_limit, default=5)

    notes = load_all(settings.root)
    hits = search_notes(
        notes,
        needle,
        fragments_per_note=settings.fragments_per_note,
        context_lines=settings.context_lines,
        max_fragment_lines=settings.max_fragment_lines,
    )

    if not hits:
        return SearchOutcome(
            text=(
                f"未找到包含 “{needle}” 的笔记（已扫描 {len(notes)} 篇）。\n"
                "建议：换一个更短的词、换英文/中文同义词，或先用 list_recent 看看最近写过什么。"
            ),
            notes_matched=0,
            notes_returned=0,
            truncated=False,
        )

    selected = hits[:limit]
    blocks = [render_hit(hit) for hit in selected]
    header = (
        f"检索 “{needle}”：命中 {len(hits)} 篇笔记，"
        f"返回前 {len(selected)} 篇的片段（每篇最多 {settings.fragments_per_note} 段，"
        f"每段前后 {settings.context_lines} 行）。\n\n"
    )
    text, returned, truncated = fit_blocks(
        blocks,
        settings.search_budget,
        header=header,
        overflow_advice="请缩小 query、降低 limit，或改用 read_note 精确读取某一篇。",
    )
    return SearchOutcome(
        text=text,
        notes_matched=len(hits),
        notes_returned=returned,
        truncated=truncated,
    )


# --------------------------------------------------------------------------- #
# read_note
# --------------------------------------------------------------------------- #


def run_read_note(settings: Settings, path: str) -> ReadOutcome:
    """读单篇全文，超过 max_note_chars 截断并标注。

    路径校验放在这里而不是 server 层：资源和工具都要用同一套规则，
    放在纯逻辑层才能保证两边不会漂移。
    """
    target = resolve_note_path(settings.root, path)  # 越界/不存在/类型不符都会抛 PathRejected
    note = load_note(settings.root, target)

    text, truncated = clip_with_notice(
        note.text,
        settings.max_note_chars,
        "请用 search_notes 定位关键段落，或读取这篇笔记对应的 notes:// URI 分段查看。",
    )
    return ReadOutcome(text=text, total_chars=len(note.text), truncated=truncated)


# --------------------------------------------------------------------------- #
# list_recent
# --------------------------------------------------------------------------- #


def run_list_recent(settings: Settings, days: int = 7) -> RecentOutcome:
    """列出最近 N 天修改过的笔记。文件名 + 修改时间 + 首行标题。"""
    days = _clamp(days, 1, 3650, default=7)
    cutoff = time.time() - days * 86_400

    notes = load_all(settings.root)
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


# --------------------------------------------------------------------------- #
# notes_stats
# --------------------------------------------------------------------------- #


def run_stats(settings: Settings) -> str:
    """笔记总数、总字数、标签分布。用于让模型先摸清语料规模再决定检索策略。"""
    notes = load_all(settings.root)
    if not notes:
        return f"笔记根目录为空：{settings.root}\n请检查目录是否正确，或先放入 .md 文件。"

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
        f"笔记根目录：{settings.root}",
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


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def _clamp(value: int, low: int, high: int, *, default: int) -> int:
    """参数夹取而不是报错：模型传了超范围的 limit 时，给最接近的合法值比拒绝更有用。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _fmt_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")

"""search_notes：全文检索，返回**片段**而不是整篇。"""

from __future__ import annotations

from dataclasses import dataclass

from ..budget import fit_blocks
from ..config import Settings
from ..notes.search import render_hit, search_notes
from ..notes.store import make_store
from .common import _clamp


class QueryRejected(ValueError):
    """参数不合法（空 query、越界 limit）。和 PathRejected 一样，消息要可读可纠正。"""


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    text: str
    notes_matched: int
    notes_returned: int
    truncated: bool


def run_search(settings: Settings, query: str, limit: int = 5) -> SearchOutcome:
    """全文检索，返回**片段**而不是整篇。

    返回整篇是最省事也最有害的实现：3 篇 5KB 的笔记就是 15K 字符，
    而模型真正需要的往往只有命中那几行。
    """
    needle = (query or "").strip()
    if not needle:
        raise QueryRejected("query 不能为空，请给出要检索的关键词（支持中英文子串）。")

    limit = _clamp(limit, 1, settings.max_limit, default=5)

    # 轻量加载：search 只用标题与正文，tags / units 解析跳过（约省一半耗时）。
    notes = make_store(settings).load_all(light=True)
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

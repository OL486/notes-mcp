"""search_notes：片段化、合并窗口、预算。"""

from __future__ import annotations

import pytest

from notes_mcp.config import Settings
from notes_mcp.tools import QueryRejected, run_search


def test_returns_fragments_not_full_text(settings: Settings) -> None:
    outcome = run_search(settings, "MCP", limit=5)
    assert outcome.notes_matched >= 2
    # 片段必须带行号标签
    assert "第 " in outcome.text
    # 无关笔记不能出现
    assert "购物清单" not in outcome.text


def test_fragment_has_two_lines_of_context(settings: Settings) -> None:
    """命中行是第 5 行（1-based），片段应当是第 3-7 行。"""
    outcome = run_search(settings, "tools/call", limit=5)
    assert "[第 3-7 行]" in outcome.text
    # 上下文里必须包含命中行前后各 2 行
    assert "第二段，还是无关。" in outcome.text  # 第 4 行
    assert "这里也是无关内容。" in outcome.text  # 第 7 行


def test_max_three_fragments_per_note(tmp_path) -> None:
    """一篇笔记里有 10 处互不相邻的命中，也只能返回 3 段。"""
    from notes_mcp.config import Settings as S

    root = tmp_path / "notes"
    root.mkdir()
    lines = []
    for index in range(10):
        lines.append(f"命中行 {index}：MCP")
        lines.extend(["无关内容"] * 5)  # 间隔足够大，窗口不会合并
    (root / "many.md").write_text("\n".join(lines), encoding="utf-8")

    outcome = run_search(S(root=root.resolve()), "MCP", limit=5)
    assert outcome.text.count("### ") == 1          # 只有一篇笔记
    assert outcome.text.count("[第 ") == 3          # 只返回 3 个片段


def test_respects_character_budget(settings: Settings) -> None:
    outcome = run_search(settings, "MCP", limit=5)
    assert len(outcome.text) <= settings.search_budget + 250  # 250 给截断提示留余量


def test_truncates_and_says_so_when_budget_tight(tmp_path) -> None:
    """预算被压到很小时，必须明确告知"已截断"，不能假装看全了。"""
    from notes_mcp.config import Settings as S

    root = tmp_path / "notes"
    root.mkdir()
    for index in range(6):
        (root / f"note{index}.md").write_text(
            "# 笔记\n" + "".join(f"第 {i} 行提到 MCP 协议的内容\n" for i in range(30)),
            encoding="utf-8",
        )

    tight = S(root=root.resolve(), search_budget=600)
    outcome = run_search(tight, "MCP", limit=6)
    assert outcome.truncated is True
    assert "已截断" in outcome.text
    assert len(outcome.text) <= 600 + 250


def test_no_match_gives_actionable_hint(settings: Settings) -> None:
    outcome = run_search(settings, "绝不存在的关键词xyzzy", limit=5)
    assert outcome.notes_matched == 0
    assert "建议" in outcome.text
    assert "list_recent" in outcome.text


def test_empty_query_rejected(settings: Settings) -> None:
    with pytest.raises(QueryRejected):
        run_search(settings, "   ", limit=5)


def test_limit_is_clamped(settings: Settings) -> None:
    """模型传 limit=999 时夹到 max_limit，而不是把整个库都吐回来。"""
    outcome = run_search(settings, "MCP", limit=999)
    assert outcome.notes_returned <= settings.max_limit


def test_case_insensitive(settings: Settings) -> None:
    lower = run_search(settings, "mcp", limit=5)
    upper = run_search(settings, "MCP", limit=5)
    assert lower.notes_matched == upper.notes_matched
    assert lower.notes_matched > 0

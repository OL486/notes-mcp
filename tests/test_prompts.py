"""prompts.py 的直接单测：模板内容与默认值。

原来 weekly_review 只有一个 e2e 断言（仅检查文本含 MCP 和 search_notes），
模板里的调用序列、输出格式和空 topic 的默认值都没有直接测试。
"""

from __future__ import annotations

from notes_mcp.prompts import WEEKLY_REVIEW, weekly_review


def test_weekly_review_name() -> None:
    assert WEEKLY_REVIEW == "weekly-review"


def test_weekly_review_contains_topic() -> None:
    text = weekly_review("MCP")
    assert "MCP" in text


def test_weekly_review_spells_out_the_tool_sequence() -> None:
    text = weekly_review("MCP")
    assert "list_recent" in text
    assert "search_notes" in text
    assert "read_note" in text
    # 先 list_recent 再 search_notes：顺序本身就是模板的价值
    assert text.index("list_recent") < text.index("search_notes")


def test_weekly_review_specifies_output_format() -> None:
    text = weekly_review("MCP")
    assert "3 条要点" in text
    assert "来源笔记路径" in text
    assert "笔记中没有提到" in text


def test_weekly_review_blank_topic_uses_fallback() -> None:
    assert "（未指定主题）" in weekly_review("")
    assert "（未指定主题）" in weekly_review("   ")
    assert "（未指定主题）" in weekly_review(None)  # type: ignore[arg-type]


def test_weekly_review_strips_topic() -> None:
    text = weekly_review("  MCP  ")
    assert "「MCP」" in text

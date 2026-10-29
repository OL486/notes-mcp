"""budget：截断、预算拼装与"截断提示本身也算预算"这三条规则。"""

from __future__ import annotations

from notes_mcp.budget import clip_text, clip_with_notice, fit_blocks


def test_clip_text_prefers_line_boundary() -> None:
    """能切在行边界就切，别把一行 Markdown 从中间劈开。"""
    body, truncated = clip_text("aaaa\nbbbb\ncccc", 10)
    assert truncated is True
    assert body == "aaaa\nbbbb"


def test_clip_text_hard_cuts_when_no_newline() -> None:
    """整篇没有换行时只能硬切，但必须如实报告截断。"""
    body, truncated = clip_text("x" * 100, 10)
    assert truncated is True
    assert body == "x" * 10


def test_clip_text_no_truncation_when_short_enough() -> None:
    body, truncated = clip_text("short", 100)
    assert (body, truncated) == ("short", False)


def test_clip_with_notice_stays_within_budget() -> None:
    """含提示在内不能超过预算 —— 否则"20000 上限"会吐出 20100。"""
    text = "内容" * 20_000
    body, truncated = clip_with_notice(text, 1_000, "请缩小范围。")
    assert truncated is True
    assert len(body) <= 1_000
    assert "已截断" in body


def test_fit_blocks_first_block_is_clipped_not_dropped() -> None:
    """第一块放不下时必须裁，不能直接丢。

    丢掉的话模型会看到"命中 N 篇、返回 0 篇"，完全没法行动。
    """
    text, count, truncated = fit_blocks(["x" * 5_000], 800, header="")
    assert count == 1
    assert truncated is True
    assert "本片段已截断" in text
    assert len(text) <= 800


def test_fit_blocks_returns_zero_when_remainder_is_useless() -> None:
    """剩余预算不够塞一段有用的内容时，返回 0 块并明说"未返回任何内容"。"""
    text, count, truncated = fit_blocks(["x" * 5_000], 300, header="")
    assert count == 0
    assert truncated is True
    assert "未返回任何内容" in text
    assert "前 0 个" not in text


def test_fit_blocks_notice_counts_against_budget() -> None:
    """截断提示本身必须算进预算。"""
    blocks = ["a" * 300 for _ in range(10)]
    text, count, truncated = fit_blocks(blocks, 1_000, header="")
    assert truncated is True
    assert count < len(blocks)
    assert len(text) <= 1_000


def test_fit_blocks_all_fit() -> None:
    text, count, truncated = fit_blocks(["abc", "def"], 1_000, header="头部\n")
    assert (count, truncated) == (2, False)
    assert text == "头部\nabcdef"

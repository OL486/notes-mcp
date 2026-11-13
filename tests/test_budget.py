"""budget.py 的直接单测：截断必须在行边界、含提示在内不超过预算。

原来这些函数只被其他测试间接覆盖，且断言是宽松的 `<= budget + 250`，
与 budget.py"含提示在内不超过 budget"的承诺自相矛盾。
"""

from __future__ import annotations

from notes_mcp.budget import (
    clip_text,
    clip_with_notice,
    fit_blocks,
    truncation_notice,
)

# --------------------------------------------------------------------------- #
# clip_text
# --------------------------------------------------------------------------- #


def test_clip_text_short_text_is_unchanged() -> None:
    text, truncated = clip_text("hello", 100)
    assert text == "hello"
    assert truncated is False


def test_clip_text_at_exact_limit_is_not_truncated() -> None:
    text, truncated = clip_text("x" * 50, 50)
    assert text == "x" * 50
    assert truncated is False


def test_clip_text_prefers_line_boundary() -> None:
    lines = ["a" * 10] * 20
    text = "\n".join(lines)
    clipped, truncated = clip_text(text, 100)
    assert truncated is True
    assert len(clipped) <= 100
    # 切在行边界上：不能把某一行切成半截
    assert clipped.endswith("a")
    assert "\n" in clipped


def test_clip_text_hard_cuts_when_no_newline_near_limit() -> None:
    text = "x" * 1000  # 整篇没有换行
    clipped, truncated = clip_text(text, 100)
    assert truncated is True
    assert clipped == "x" * 100


def test_clip_text_crlf_does_not_leave_a_lone_cr() -> None:
    text = "\r\n".join("x" * 40 for _ in range(20))
    clipped, truncated = clip_text(text, 100)
    assert truncated is True
    assert not clipped.endswith("\r")
    assert len(clipped) <= 100


def test_clip_text_non_positive_limit() -> None:
    text, truncated = clip_text("hello", 0)
    assert text == ""
    assert truncated is True

    text, truncated = clip_text("", 0)
    assert text == ""
    assert truncated is False


# --------------------------------------------------------------------------- #
# truncation_notice / clip_with_notice
# --------------------------------------------------------------------------- #


def test_truncation_notice_states_returned_total_and_advice() -> None:
    notice = truncation_notice(100, 1000, 500, "请缩小范围。")
    assert "100" in notice
    assert "1000" in notice
    assert "500" in notice
    assert "请缩小范围。" in notice


def test_clip_with_notice_short_text_is_unchanged() -> None:
    text, truncated = clip_with_notice("hello", 500, "advice")
    assert text == "hello"
    assert truncated is False
    assert "已截断" not in text


def test_clip_with_notice_total_including_notice_is_within_budget() -> None:
    text = "x" * 5000
    clipped, truncated = clip_with_notice(text, 500, "请缩小范围。")
    assert truncated is True
    assert "已截断" in clipped
    # 关键承诺：含提示在内不超过 budget，而不是 budget + 提示长度
    assert len(clipped) <= 500


def test_clip_with_notice_reports_returned_and_total() -> None:
    text = "y" * 2000
    clipped, truncated = clip_with_notice(text, 300, "advice")
    assert truncated is True
    assert "全文 2000 字符" in clipped
    assert "300 字符预算" in clipped


def test_clip_with_notice_long_advice_is_within_budget() -> None:
    """提示文案本身很长时也不能溢出：旧实现按固定 240 预留，300 字符的
    advice 会让含提示的总长度超过 budget。"""
    clipped, truncated = clip_with_notice("y" * 5000, 500, "x" * 300)
    assert truncated is True
    assert "已截断" in clipped
    assert len(clipped) <= 500


def test_clip_with_notice_tiny_budget_is_within_budget() -> None:
    """预算连提示都快装不下时，仍保证不超预算。"""
    clipped, truncated = clip_with_notice("y" * 5000, 50, "x" * 300)
    assert truncated is True
    assert len(clipped) <= 50


# --------------------------------------------------------------------------- #
# fit_blocks
# --------------------------------------------------------------------------- #


def test_fit_blocks_returns_all_when_they_fit() -> None:
    text, returned, truncated = fit_blocks(["aaa", "bbb"], 100, header="H\n")
    assert text == "H\naaabbb"
    assert returned == 2
    assert truncated is False


def test_fit_blocks_clips_first_block_instead_of_dropping_it() -> None:
    """第一块放不下时必须裁而不是丢，否则会返回 0 个结果。"""
    big = "z" * 2000
    text, returned, truncated = fit_blocks([big], 800, header="")
    assert truncated is True
    assert returned == 1
    assert "已截断" in text
    assert len(text) <= 800


def test_fit_blocks_drops_whole_blocks_after_the_first() -> None:
    blocks = ["a" * 100, "b" * 100, "c" * 100]
    text, returned, truncated = fit_blocks(blocks, 250, header="")
    assert truncated is True
    assert returned < len(blocks)
    assert len(text) <= 250


def test_fit_blocks_total_including_notice_is_within_budget() -> None:
    blocks = ["n" * 500 for _ in range(6)]
    text, returned, truncated = fit_blocks(blocks, 600, header="header\n")
    assert truncated is True
    assert len(text) <= 600


def test_fit_blocks_empty_list_returns_header_only() -> None:
    text, returned, truncated = fit_blocks([], 100, header="H")
    assert text == "H"
    assert returned == 0
    assert truncated is False


def test_fit_blocks_min_useful_remainder_is_respected() -> None:
    """整块放不下、且剩余预算不足以塞一个有用的残片时，宁可不塞。"""
    # header 占 500，预算 700：整块 300 字符放不下，剩余只有 200 < 400，
    # 所以不裁剪、直接丢弃整块，只留 header + 截断提示。
    header = "h" * 500
    text, returned, truncated = fit_blocks(["x" * 300], 700, header=header)
    assert truncated is True
    assert returned == 0
    assert "x" * 10 not in text
    assert len(text) <= 700


def test_fit_blocks_header_alone_over_budget_is_within_budget() -> None:
    """header 本身（150 字符）就超过预算（100）时，仍保证输出不超预算，
    且必须带截断提示。"""
    text, returned, truncated = fit_blocks(["a" * 10], 100, header="h" * 150)
    assert truncated is True
    assert returned == 0
    assert "已截断" in text
    assert len(text) <= 100


def test_fit_blocks_header_only_over_budget_is_within_budget() -> None:
    text, returned, truncated = fit_blocks([], 100, header="h" * 150)
    assert truncated is True
    assert returned == 0
    assert len(text) <= 100

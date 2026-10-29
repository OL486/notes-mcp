"""store 层的解析细节：标题、标签、字数、目录过滤。"""

from __future__ import annotations

from pathlib import Path

from notes_mcp.store import (
    count_units,
    decode_bytes,
    extract_tags,
    extract_title,
    iter_note_files,
    load_all,
)


def test_title_from_first_heading() -> None:
    assert extract_title("# 我的标题\n\n正文", "fallback") == "我的标题"


def test_title_falls_back_to_first_line() -> None:
    assert extract_title("没有标题的笔记\n第二行", "stem") == "没有标题的笔记"


def test_title_falls_back_to_filename() -> None:
    assert extract_title("   \n\n", "2026-10-01") == "2026-10-01"


def test_tags_are_parsed() -> None:
    text = "# 标题\n\n正文 #mcp #中文标签\n\n#a/b\n"
    assert extract_tags(text) == ("a/b", "mcp", "中文标签")


def test_tag_only_line_is_not_a_heading() -> None:
    """整行标签 `#mcp #protocol` 不能被当成标题剔掉——第一版就在这里归零了。"""
    assert extract_tags("#mcp #protocol\n") == ("mcp", "protocol")


def test_heading_is_not_a_tag() -> None:
    assert extract_tags("# 这是一个标题\n## 二级标题\n") == ()


def test_fenced_code_is_ignored() -> None:
    text = "# 标题\n\n```python\n# 这是注释不是标签\n```\n\n正文 #real\n"
    assert extract_tags(text) == ("real",)


def test_count_units_mixes_cjk_and_latin() -> None:
    # 4 个汉字 + 2 个英文词
    assert count_units("中文四个 words here") == 4 + 2


def test_decode_gbk_fallback() -> None:
    raw = "中文内容".encode("gb18030")
    assert decode_bytes(raw) == "中文内容"


def test_decode_invalid_bytes_does_not_raise() -> None:
    assert isinstance(decode_bytes(b"\xff\xfe\x00bad"), str)


def test_skips_hidden_and_non_markdown(notes_root: Path) -> None:
    rels = {p.relative_to(notes_root).as_posix() for p in iter_note_files(notes_root)}
    assert "projects/notes.txt" not in rels
    assert not any(".obsidian" in rel for rel in rels)
    assert "daily/2026-10-25.md" in rels


def test_load_all_is_sorted_and_stable(notes_root: Path) -> None:
    first = [n.rel for n in load_all(notes_root)]
    second = [n.rel for n in load_all(notes_root)]
    assert first == second == sorted(first)


def test_unclosed_fence_does_not_swallow_rest_of_file() -> None:
    """未闭合代码块是格式瑕疵，不该让后面所有标签消失。

    旧实现遇到 ``` 就一直把后续行替换成空行，直到文件结束都没有闭合标记，
    于是整篇笔记的标签统计直接归零。这里断言标签仍然能被解析出来。
    """
    text = "# 标题\n\n```python\n# 这是注释不是标签\n\n正文 #real-tag\n"
    assert extract_tags(text) == ("real-tag",)


def test_closed_fence_still_hides_code_tags() -> None:
    """修复未闭合场景时不能把已闭合代码块的过滤能力弄丢。"""
    text = "# 标题\n\n```python\n# 注释不是标签\nx = 1\n```\n\n正文 #real\n"
    assert extract_tags(text) == ("real",)


def test_multiple_fences_last_unclosed() -> None:
    """前面闭合、最后一个未闭合时，只恢复最后一个代码块之后的内容。"""
    text = (
        "# 标题\n\n"
        "```sh\n# 第一个代码块里的注释\n```\n\n"
        "#first\n\n"
        "```sh\n# 第二个代码块未闭合\n\n"
        "#second\n"
    )
    tags = extract_tags(text)
    assert "first" in tags
    assert "second" in tags

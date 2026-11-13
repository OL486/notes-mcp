"""store 层的解析细节：标题、标签、字数、目录过滤。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from notes_mcp.notes import (
    count_units,
    decode_bytes,
    extract_tags,
    extract_title,
    iter_note_files,
)
from notes_mcp.notes.store import FilesystemNoteStore
from notes_mcp.safety import PathRejected


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
    store = FilesystemNoteStore(notes_root)
    first = [n.rel for n in store.load_all()]
    second = [n.rel for n in store.load_all()]
    assert first == second == sorted(first)


def test_scan_skips_symlink_pointing_outside_root(notes_root: Path, tmp_path: Path) -> None:
    """SEC-A：根内 linkfile.md -> 根外 secret.md，扫描必须跳过，
    load_all / search 不能因此泄漏根外文件的内容。"""
    link = notes_root / "linkfile.md"
    try:
        os.symlink(tmp_path / "secret.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    rels = {p.relative_to(notes_root).as_posix() for p in iter_note_files(notes_root)}
    assert "linkfile.md" not in rels

    notes = FilesystemNoteStore(notes_root).load_all()
    assert all("不该被读到" not in note.text for note in notes)


def test_scan_keeps_symlink_inside_root(notes_root: Path) -> None:
    """指向根目录内部的软链接仍会被扫描（与 resolve_note_path 的行为一致）。"""
    link = notes_root / "alias.md"
    try:
        os.symlink(notes_root / "projects" / "design.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    rels = {p.relative_to(notes_root).as_posix() for p in iter_note_files(notes_root)}
    assert "alias.md" in rels


def test_load_note_rejects_symlink_outside_root(notes_root: Path, tmp_path: Path) -> None:
    """load_note 的二次校验：直接调用也不允许读根外文件。"""
    link = notes_root / "linkfile.md"
    try:
        os.symlink(tmp_path / "secret.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    with pytest.raises(PathRejected):
        FilesystemNoteStore(notes_root).load_note(link)

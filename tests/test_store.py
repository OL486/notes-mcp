"""store 层的解析细节：标题、标签、字数、目录过滤。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from notes_mcp.config import Settings
from notes_mcp.notes import (
    count_units,
    decode_bytes,
    extract_tags,
    extract_title,
    iter_note_files,
)
from notes_mcp.notes.store import FilesystemNoteStore, make_store
from notes_mcp.safety import PathRejected


def test_title_from_first_heading() -> None:
    assert extract_title("# 我的标题\n\n正文", "fallback") == "我的标题"


def test_title_falls_back_to_first_line() -> None:
    assert extract_title("没有标题的笔记\n第二行", "stem") == "没有标题的笔记"


def test_title_skips_tag_only_line() -> None:
    """B1：首行是纯标签行时不能当标题，要继续往下找。"""
    assert extract_title("#mcp #design\n# 真标题\n正文", "fallback") == "真标题"
    assert extract_title("#mcp #design\n正文第一行", "fallback") == "正文第一行"


def test_title_skips_fenced_code_block() -> None:
    """B6：笔记以代码围栏开头时，标题不能变成 ```。"""
    assert extract_title("```python\n# 注释\n```\n# 真标题\n", "fallback") == "真标题"
    assert extract_title("```\ncode\n```\n正文第一行", "fallback") == "正文第一行"


def test_title_no_space_heading_is_not_a_heading() -> None:
    """`#标题` 没空格，在 Markdown 里不是标题，按标签行跳过。"""
    assert extract_title("#标题\n第二行", "fallback") == "第二行"


def test_title_falls_back_to_filename() -> None:
    assert extract_title("   \n\n", "2026-10-01") == "2026-10-01"


def test_title_skips_frontmatter_block() -> None:
    """frontmatter 的 `---` 块不是标题，块里的内容也不参与标题判定。"""
    text = "---\ntitle: 我的笔记\ntags: [mcp, 设计]\n---\n\n# 真实标题\n\n正文"
    assert extract_title(text, "fallback") == "真实标题"


def test_title_uses_frontmatter_title_without_heading() -> None:
    """没有 `#` 标题时，frontmatter 的 `title:` 优先于第一行非空内容。"""
    text = "---\ntitle: 我的笔记\ntags: [mcp]\n---\n\n正文第一行\n第二行"
    assert extract_title(text, "fallback") == "我的笔记"
    quoted = '---\ntitle: "带引号的标题"\n---\n\n正文'
    assert extract_title(quoted, "fallback") == "带引号的标题"


def test_title_heading_beats_frontmatter_title() -> None:
    """有 `#` 标题时它优先，frontmatter 的 `title:` 只是 fallback。"""
    text = "---\ntitle: 元数据标题\n---\n\n# 正文标题\n"
    assert extract_title(text, "fallback") == "正文标题"


def test_title_frontmatter_dotdotdot_terminator() -> None:
    """frontmatter 也可以用 `...` 结束。"""
    text = "---\ntitle: 元数据标题\ntags: [mcp]\n...\n\n# 正文标题\n"
    assert extract_title(text, "fallback") == "正文标题"
    assert extract_tags(text) == ("mcp",)


def test_tags_from_frontmatter_flow_list() -> None:
    """`tags: [a, b]` 列表写法与正文标签合并。"""
    text = "---\ntags: [mcp, 设计]\n---\n\n正文 #正文标签\n"
    assert extract_tags(text) == ("mcp", "正文标签", "设计")
    single = "---\ntags: mcp\n---\n\n正文\n"
    assert extract_tags(single) == ("mcp",)


def test_tags_from_frontmatter_block_list() -> None:
    """`tags:` 下 `- a` 块列表写法，值可带引号。"""
    text = '---\ntags:\n  - mcp\n  - "设计"\n  - a/b\n---\n\n正文\n'
    assert extract_tags(text) == ("a/b", "mcp", "设计")


def test_frontmatter_hash_lines_are_not_tags() -> None:
    """frontmatter 块里的 `#`（标题值、注释行）不算标签。"""
    text = '---\ntitle: "#notatag"\n# 这行是注释\ntags: [mcp]\n---\n\n正文 #real\n'
    assert extract_tags(text) == ("mcp", "real")
    assert extract_title(text, "fallback") == "#notatag"


def test_unclosed_frontmatter_is_not_stripped() -> None:
    """没有结束行的 `---` 块不是 frontmatter，整篇按正文处理。"""
    text = "---\ntitle: 元数据标题\n\n# 真标题\n"
    assert extract_title(text, "fallback") == "---"
    assert extract_tags(text) == ()


def test_store_loads_frontmatter_note(tmp_path: Path) -> None:
    """端到端：带 frontmatter 的笔记进 store，标题与标签都正确。"""
    note = tmp_path / "fm.md"
    note.write_text(
        "---\ntitle: FM 标题\ntags: [mcp]\n---\n\n# 正文标题\n\n内容 #body\n",
        encoding="utf-8",
    )
    loaded = FilesystemNoteStore(tmp_path).load_note(note)
    assert loaded.title == "正文标题"
    assert loaded.tags == ("body", "mcp")


def test_tags_are_parsed() -> None:
    text = "# 标题\n\n正文 #mcp #中文标签\n\n#a/b\n"
    assert extract_tags(text) == ("a/b", "mcp", "中文标签")


def test_inline_code_tag_is_ignored() -> None:
    """B3：行内代码里的 `#tag` 不是标签。"""
    assert extract_tags("`#foo` 和 #real\n") == ("real",)
    assert extract_tags("`` `#foo` `` 和 #real\n") == ("real",)


def test_tags_without_backticks_are_parsed() -> None:
    """N1：反引号守卫——无反引号的行跳过两次 sub，标签结果必须不变。"""
    lines = ["#t0 #t1"] + [f"正文第 {i} 行 #tag{i % 5}" for i in range(2000)]
    text = "# 标题\n\n" + "\n".join(lines) + "\n"
    assert extract_tags(text) == ("t0", "t1", "tag0", "tag1", "tag2", "tag3", "tag4")


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


def test_decode_utf16_bom() -> None:
    """B4：带 BOM 的 UTF-16 笔记要按 UTF-16 解，不能走 gb18030 兜底成乱码。"""
    assert decode_bytes("中文内容".encode("utf-16")) == "中文内容"
    assert decode_bytes("hello".encode("utf-16")) == "hello"


def test_count_units_single_regex_matches_old_counts() -> None:
    assert count_units("abc_123 中文") == 1 + 2
    assert count_units("one two three") == 3
    assert count_units("") == 0


def test_decode_invalid_bytes_does_not_raise() -> None:
    assert isinstance(decode_bytes(b"\xff\xfe\x00bad"), str)


def test_skips_hidden_and_non_markdown(notes_root: Path) -> None:
    rels = {p.relative_to(notes_root).as_posix() for p in iter_note_files(notes_root)}
    assert "projects/notes.txt" not in rels
    assert not any(".obsidian" in rel for rel in rels)
    assert "daily/2026-10-25.md" in rels


def test_light_load_matches_full_load(notes_root: Path) -> None:
    """A2：轻量加载的 rel / title / mtime / text 必须与全量一致，
    只是 tags 为空、units 为 0。"""
    store = FilesystemNoteStore(notes_root)
    full = {n.rel: n for n in store.load_all()}
    light = {n.rel: n for n in store.load_all(light=True)}
    assert set(light) == set(full)
    for rel, note in light.items():
        assert note.title == full[rel].title
        assert note.mtime == full[rel].mtime
        assert note.text == full[rel].text
        assert note.tags == ()
        assert note.units == 0
    assert any(full[rel].tags for rel in full)


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


def test_store_works_when_root_is_a_symlink(tmp_path: Path) -> None:
    """N2：根目录本身是符号链接时，缓存的 resolved 根不能破坏 relative_to。

    扫描返回的路径仍以调用方传进来的原始根为前缀，load_note 的越界校验
    用缓存的 resolved 根比，rel 仍按原始根算——三者必须同时成立。
    """
    real = tmp_path / "real"
    (real / "daily").mkdir(parents=True)
    (real / "daily" / "a.md").write_text("# A\n", encoding="utf-8")
    link = tmp_path / "link"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    notes = FilesystemNoteStore(link).load_all()
    assert [n.rel for n in notes] == ["daily/a.md"]


def test_make_store_rejects_missing_root(tmp_path: Path) -> None:
    """N6：根目录不存在时 make_store 直接报错，而不是静默返回空库。"""
    with pytest.raises(FileNotFoundError, match="根目录不存在"):
        make_store(Settings(root=tmp_path / "no-such-dir"))


def test_compat_store_module_reexports_with_deprecation_warning() -> None:
    """P2-1：兼容层 import 时发 DeprecationWarning，re-export 与新位置一致。

    0.2.0 删除它时，这个测试要跟着删；删除前，它锁住 re-export 列表
    （列表错了、warning 没发，都会在这里炸掉）。
    """
    import importlib
    import sys

    from notes_mcp.notes import make_store as new_make_store

    with pytest.warns(DeprecationWarning, match="已废弃"):
        if "notes_mcp.store" in sys.modules:
            importlib.reload(sys.modules["notes_mcp.store"])
        else:
            import notes_mcp.store  # noqa: F401 — 这里就是要触发它发 warning
    import notes_mcp.store as compat
    assert compat.make_store is new_make_store
    assert compat.FilesystemNoteStore is not None
    assert set(compat.__all__) == {
        "ALLOWED_SUFFIXES",
        "SKIP_DIRS",
        "TAG_RE",
        "FilesystemNoteStore",
        "Fragment",
        "Note",
        "NoteHit",
        "NoteStore",
        "count_units",
        "decode_bytes",
        "extract_tags",
        "extract_title",
        "iter_note_files",
        "make_store",
        "render_hit",
        "search_notes",
    }


def _sample_notes_root() -> Path:
    return Path(__file__).resolve().parent.parent / "sample_notes"


def test_sample_frontmatter_note() -> None:
    """P2-2：带 frontmatter 的样本能被正常索引：标题取正文标题，标签合并。"""
    store = FilesystemNoteStore(_sample_notes_root())
    note = store.load_note(_sample_notes_root() / "daily" / "2026-10-27-frontmatter.md")
    assert note.title == "十月最后一周复盘"
    assert note.tags == ("周报", "复盘", "手账")


def test_sample_code_block_tags_are_not_tags() -> None:
    """P2-2：代码块里的 `#注释` 与行内代码里的 `#tag` 不能进标签。"""
    store = FilesystemNoteStore(_sample_notes_root())
    note = store.load_note(_sample_notes_root() / "projects" / "code-tag-note.md")
    assert note.title == "正则表达式备忘"
    assert note.tags == ("python", "regex")


def test_sample_long_note_triggers_truncation() -> None:
    """P2-2：长样本（> 20,000 字符）读出来应当触发截断提示。"""
    from notes_mcp.tools import run_read_note

    settings = Settings(root=_sample_notes_root())
    outcome = run_read_note(settings, "reading/long-form-notes.md")
    assert outcome.total_chars > 20_000
    assert outcome.truncated is True
    assert "[已截断" in outcome.text


def test_sample_notes_are_searchable() -> None:
    """P2-2：新样本进索引后能被搜到（frontmatter 标签与长文正文都能命中）。"""
    from notes_mcp.tools import run_search

    settings = Settings(root=_sample_notes_root())
    assert run_search(settings, "复盘", limit=5).notes_matched >= 1
    assert run_search(settings, "设计模式", limit=5).notes_matched >= 1

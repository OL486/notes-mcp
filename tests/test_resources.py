"""Resources：索引 JSON 与单篇读取。"""

from __future__ import annotations

import json

import pytest

from notes_mcp.config import Settings
from notes_mcp.resources import build_index, read_note_resource
from notes_mcp.safety import PathRejected


def test_index_is_valid_json(settings: Settings) -> None:
    payload = json.loads(build_index(settings))
    assert payload["count"] == 3  # daily + 2 篇 projects
    assert payload["returned"] == 3
    assert payload["truncated"] is False


def test_index_entries_have_uri_and_metadata(settings: Settings) -> None:
    payload = json.loads(build_index(settings))
    entry = next(e for e in payload["notes"] if e["path"] == "daily/2026-10-25.md")
    assert entry["uri"] == "notes://note/daily/2026-10-25.md"
    assert entry["title"] == "十月二十五日"
    assert entry["tags"] == ["daily", "mcp"]
    assert entry["units"] > 0


def test_index_respects_budget(tmp_path) -> None:
    """笔记很多时索引必须裁剪，并在 JSON 里明说裁了。"""
    root = tmp_path / "notes"
    root.mkdir()
    for index in range(200):
        (root / f"n{index:03d}.md").write_text(f"# 笔记 {index}\n正文\n", encoding="utf-8")

    payload = json.loads(build_index(Settings(root=root.resolve(), index_budget=2000)))
    assert payload["truncated"] is True
    assert payload["returned"] < payload["count"]
    assert "hint" in payload


def test_read_note_resource(settings: Settings) -> None:
    text = read_note_resource(settings, "projects/design.md")
    assert "Resource 与 Tool 的区别" in text


def test_read_note_resource_rejects_traversal(settings: Settings) -> None:
    with pytest.raises(PathRejected):
        read_note_resource(settings, "../../secret.md")


def test_read_note_resource_truncates(tmp_path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "big.md").write_text("# 大文件\n" + "内容\n" * 5000, encoding="utf-8")

    text = read_note_resource(Settings(root=root.resolve(), max_note_chars=1000), "big.md")
    assert "已截断" in text
    assert len(text) < 1000 + 250

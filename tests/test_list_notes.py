"""list_notes：翻页、目录过滤、参数夹取、预算截断。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from notes_mcp.config import Settings
from notes_mcp.safety import PathRejected
from notes_mcp.tools import run_list_notes


def _make_notes(root: Path, count: int, subdir: str = "") -> Path:
    """造 count 篇笔记，mtime 各差 1 小时：序号越大、mtime 越新。"""
    target = root / subdir if subdir else root
    target.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for index in range(count):
        path = target / f"n{index:03d}.md"
        path.write_text(f"# 笔记 {index}\n正文\n", encoding="utf-8")
        stamp = now - (count - index) * 3600
        os.utime(path, (stamp, stamp))
    return root


def test_pagination_covers_all_notes(tmp_path: Path) -> None:
    """45 篇、每页 20：三页合起来必须正好是全部，且按 mtime 倒序。"""
    root = _make_notes(tmp_path / "notes", 45)
    settings = Settings(root=root.resolve())

    seen: list[str] = []
    offset = 0
    pages = 0
    while True:
        outcome = run_list_notes(settings, offset=offset, limit=20)
        assert outcome.total == 45
        assert outcome.offset == offset
        pages += 1
        for index in range(outcome.count):
            rel = f"n{44 - (offset + index):03d}.md"
            assert rel in outcome.text
            seen.append(rel)
        if not outcome.has_more:
            break
        assert outcome.has_more is True
        offset += outcome.count
        assert offset < 45

    assert pages == 3
    assert sorted(seen) == [f"n{index:03d}.md" for index in range(45)]
    last = run_list_notes(settings, offset=40, limit=20)
    assert last.count == 5
    assert last.has_more is False
    assert "第 41–45 篇" in last.text


def test_offset_beyond_total(tmp_path: Path) -> None:
    root = _make_notes(tmp_path / "notes", 3)
    outcome = run_list_notes(Settings(root=root.resolve()), offset=100)
    assert outcome.count == 0
    assert outcome.total == 3
    assert outcome.has_more is False
    assert "已到末尾" in outcome.text


def test_dir_filter(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    _make_notes(root, 2, subdir="daily")
    _make_notes(root, 1, subdir="projects")
    settings = Settings(root=root.resolve())

    daily = run_list_notes(settings, dir="daily")
    assert daily.total == 2
    assert daily.count == 2
    assert "daily/n000.md" in daily.text
    assert "projects/" not in daily.text

    # 尾部斜杠不影响结果
    assert run_list_notes(settings, dir="daily/").total == 2
    assert run_list_notes(settings, dir="projects").total == 1
    assert run_list_notes(settings, dir="").total == 3

    missing = run_list_notes(settings, dir="nope")
    assert missing.count == 0
    assert "没有笔记" in missing.text


def test_offset_and_limit_are_clamped(tmp_path: Path) -> None:
    root = _make_notes(tmp_path / "notes", 3)
    settings = Settings(root=root.resolve())

    # limit=0 夹到 1；limit=999 夹到 max_limit（默认 20），只有 3 篇
    assert run_list_notes(settings, limit=0).count == 1
    assert run_list_notes(settings, limit=999).count == 3
    # 负 offset 夹到 0，从第一篇开始
    first = run_list_notes(settings, offset=-5)
    assert first.offset == 0
    assert "n002.md" in first.text


def test_dir_rejects_traversal(tmp_path: Path) -> None:
    root = _make_notes(tmp_path / "notes", 1)
    settings = Settings(root=root.resolve())
    for bad in ("../secret", "/etc", "a\x00b"):
        with pytest.raises(PathRejected):
            run_list_notes(settings, dir=bad)


def test_budget_truncation(tmp_path: Path) -> None:
    """预算很小时必须截断、不超预算，且翻页提示不能给出会跳号的 offset。"""
    root = _make_notes(tmp_path / "notes", 300)
    settings = Settings(root=root.resolve(), list_budget=800)
    outcome = run_list_notes(settings, limit=20)
    assert outcome.truncated is True
    assert len(outcome.text) <= 800
    assert "已截断" in outcome.text
    assert outcome.count < 20
    # 截断时 footer 不追加：它的 next_offset 会跳过本页没返回的条目
    assert "调用 list_notes(offset=" not in outcome.text

"""list_recent / notes_stats 的行为。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from notes_mcp.config import Settings
from notes_mcp.tools import run_list_recent, run_stats


def test_list_recent_filters_by_mtime(settings: Settings) -> None:
    outcome = run_list_recent(settings, days=7)
    # daily(1h) + design(3d) 在范围内，unrelated(30d) 不在
    assert "daily/2026-10-25.md" in outcome.text
    assert "projects/design.md" in outcome.text
    assert "projects/unrelated.md" not in outcome.text


def test_list_recent_sorted_desc(settings: Settings) -> None:
    outcome = run_list_recent(settings, days=7)
    daily_at = outcome.text.index("daily/2026-10-25.md")
    design_at = outcome.text.index("projects/design.md")
    assert daily_at < design_at  # 更近修改的排在前面


def test_list_recent_empty_window(settings: Settings) -> None:
    outcome = run_list_recent(settings, days=1)
    # 1 天窗口内只有 1 小时前的那篇
    assert "daily/2026-10-25.md" in outcome.text
    assert "projects/design.md" not in outcome.text


def test_list_recent_nothing_matches(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "old.md").write_text("# 旧笔记\n", encoding="utf-8")
    old = time.time() - 400 * 86_400
    os.utime(root / "old.md", (old, old))

    outcome = run_list_recent(Settings(root=root.resolve()), days=7)
    assert outcome.count == 0
    assert "建议" in outcome.text


def test_days_is_clamped(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "a.md").write_text("# A\n", encoding="utf-8")
    # days=0 会被夹到 1，不应抛异常
    outcome = run_list_recent(Settings(root=root.resolve()), days=0)
    assert "最近 1 天" in outcome.text


def test_list_recent_respects_budget(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    for index in range(300):
        (root / f"n{index:03d}.md").write_text(f"# 笔记 {index}\n", encoding="utf-8")

    settings = Settings(root=root.resolve(), recent_budget=800)
    outcome = run_list_recent(settings, days=7)
    assert outcome.truncated is True
    assert "已截断" in outcome.text
    assert len(outcome.text) <= 800 + 250


def test_stats_counts_and_tags(settings: Settings) -> None:
    text = run_stats(settings)
    assert "笔记总数：3 篇" in text
    assert "标签数：" in text
    assert "#mcp" in text
    assert "未打标签" in text


def test_stats_empty_root(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    text = run_stats(Settings(root=root.resolve()))
    assert "为空" in text

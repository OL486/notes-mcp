"""read_note：截断行为。"""

from __future__ import annotations

from pathlib import Path

from notes_mcp.config import Settings
from notes_mcp.tools import run_read_note


def test_reads_full_note(settings: Settings) -> None:
    outcome = run_read_note(settings, "daily/2026-10-25.md")
    assert "tools/call" in outcome.text
    assert outcome.truncated is False
    assert outcome.total_chars == len(outcome.text)


def test_truncates_over_limit(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    body = "\n".join(f"第 {i} 行内容" for i in range(5000))
    (root / "long.md").write_text("# 长笔记\n" + body, encoding="utf-8")

    settings = Settings(root=root.resolve(), max_note_chars=500)
    outcome = run_read_note(settings, "long.md")

    assert outcome.truncated is True
    assert outcome.total_chars > 500
    assert "已截断" in outcome.text
    # 截断后的正文（不含提示）不能超过上限
    assert len(outcome.text) < 500 + 250


def test_truncation_prefers_line_boundary(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "lines.md").write_text("\n".join("x" * 40 for _ in range(100)), encoding="utf-8")

    settings = Settings(root=root.resolve(), max_note_chars=200)
    outcome = run_read_note(settings, "lines.md")
    body = outcome.text.split("\n\n[已截断")[0]
    assert body.endswith("x")  # 没有把某一行切成半截
    assert len(body) <= 200

"""Resources：索引 JSON 与单篇读取。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from notes_mcp.config import Settings
from notes_mcp.notes.store import make_store
from notes_mcp.resources import _dump_index, build_index, read_note_resource
from notes_mcp.safety import PathRejected, to_note_uri
from notes_mcp.tools.common import _fmt_iso_time


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


def test_index_respects_budget(tmp_path: Path) -> None:
    """笔记很多时索引必须裁剪，并在 JSON 里明说裁了。"""
    root = tmp_path / "notes"
    root.mkdir()
    for index in range(200):
        (root / f"n{index:03d}.md").write_text(f"# 笔记 {index}\n正文\n", encoding="utf-8")

    payload = json.loads(build_index(Settings(root=root.resolve(), index_budget=2000)))
    assert payload["truncated"] is True
    assert payload["returned"] < payload["count"]
    assert "hint" in payload


def test_index_respects_small_budget(tmp_path: Path) -> None:
    """B2：小预算也不能超预算——index_budget=500 曾输出 917 字符。"""
    root = tmp_path / "notes"
    root.mkdir()
    for index in range(200):
        (root / f"n{index:03d}.md").write_text(f"# 笔记 {index}\n正文\n", encoding="utf-8")

    for budget in (500, 100):
        text = build_index(Settings(root=root.resolve(), index_budget=budget))
        assert len(text) <= budget, f"index_budget={budget} 时输出 {len(text)} 字符"
        payload = json.loads(text)
        assert payload["truncated"] is True
        assert payload["returned"] == 0


def test_index_incremental_accounting_matches_full_dump(tmp_path: Path) -> None:
    """N3：增量记账必须与每轮全量 dumps 的结论一致（条目数、截断标记、总长）。

    预言用旧方法逐条加、每次真实 dumps 量长度；若增量算式差一个字符，
    截断点就会在某个预算下错开。
    """
    root = tmp_path / "notes"
    root.mkdir()
    for index in range(60):
        (root / f"n{index:03d}.md").write_text(
            f"# 笔记 {index}\n正文 {'x' * index}\n#tag{index % 7}\n", encoding="utf-8"
        )

    for budget in (500, 1000, 2000, 5000, 10_000_000):
        settings = Settings(root=root.resolve(), index_budget=budget)
        text = build_index(settings)
        assert len(text) <= budget
        payload = json.loads(text)

        notes = make_store(settings).load_all()
        notes.sort(key=lambda n: n.mtime, reverse=True)
        work_budget = max(0, budget - 200)
        entries: list[dict[str, object]] = []
        for note in notes:
            entries.append(
                {
                    "uri": to_note_uri(note.rel),
                    "path": note.rel,
                    "title": note.title,
                    "mtime": _fmt_iso_time(note.mtime),
                    "units": note.units,
                    "tags": list(note.tags),
                }
            )
            if (
                len(_dump_index(settings, len(notes), entries, truncated=True))
                > work_budget
            ):
                entries.pop()
                break
        assert payload["returned"] == len(entries)
        assert payload["truncated"] == (len(entries) < len(notes))


def test_build_index_huge_budget_is_fast(tmp_path: Path) -> None:
    """N3：大预算下 build_index 必须回到毫秒级。

    旧的每轮全量 dumps 在 1000 篇、index_budget=10_000_000 时要 ~4.6 s；
    增量记账后只剩一次最终 dumps，耗时应与全量加载本身（~0.8 s）同一量级。
    3.0 s 的上限留了约 3 倍余量，只防 O(n²) 回归，不卡正常波动。
    """
    root = tmp_path / "notes"
    root.mkdir()
    for index in range(1000):
        (root / f"n{index:04d}.md").write_text(
            f"# Note {index}\n" + "body line\n" * 98, encoding="utf-8"
        )

    settings = Settings(root=root.resolve(), index_budget=10_000_000)
    start = time.perf_counter()
    text = build_index(settings)
    elapsed = time.perf_counter() - start
    payload = json.loads(text)
    assert payload["returned"] == payload["count"] == 1000
    assert elapsed < 3.0


def test_read_note_resource(settings: Settings) -> None:
    text = read_note_resource(settings, "projects/design.md")
    assert "Resource 与 Tool 的区别" in text


def test_read_note_resource_rejects_traversal(settings: Settings) -> None:
    with pytest.raises(PathRejected):
        read_note_resource(settings, "../../secret.md")


def test_read_note_resource_truncates(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "big.md").write_text("# 大文件\n" + "内容\n" * 5000, encoding="utf-8")

    text = read_note_resource(Settings(root=root.resolve(), max_note_chars=1000), "big.md")
    assert "已截断" in text
    assert len(text) <= 1000

"""生成上下文预算表：构造最坏情况，量出每个原语的返回上限。

"预算"如果是拍脑袋写的数字，等于没有预算。这个脚本用可复现的方式
把每个原语顶到天花板，然后报告实际字符数，让你知道最坏情况到底是多大。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from notes_mcp.config import Settings
from notes_mcp.resources import build_index, read_note_resource
from notes_mcp.tools import run_list_recent, run_read_note, run_search, run_stats


def _make_library(root: Path, notes: int, lines_per_note: int, line_len: int) -> None:
    """造一个"难看的"笔记库：每篇都长、每行都长、每行都命中。"""
    (root / "d").mkdir(parents=True)
    body = "\n".join("命中关键词 " + "填充" * (line_len // 2) for _ in range(lines_per_note))
    for index in range(notes):
        (root / "d" / f"n{index:03d}.md").write_text(
            f"# 笔记 {index}\n{body}\n#tag{index % 50}\n", encoding="utf-8"
        )


def measure(label: str, value: str) -> tuple[str, int]:
    return label, len(value)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        _make_library(root, notes=200, lines_per_note=600, line_len=40)

        settings = Settings(root=root.resolve())
        rows: list[tuple[str, int, str]] = []

        search = run_search(settings, "命中关键词", limit=20)
        rows.append(("search_notes(query, limit=20)", len(search.text), f"预算 {settings.search_budget}"))

        read = run_read_note(settings, "d/n000.md")
        rows.append(("read_note(超长笔记)", len(read.text), f"上限 {settings.max_note_chars}"))

        recent = run_list_recent(settings, days=3650)
        rows.append(("list_recent(days=3650, 200 篇)", len(recent.text), f"预算 {settings.recent_budget}"))

        stats = run_stats(settings)
        rows.append(("notes_stats(50 个标签)", len(stats), f"预算 {settings.stats_budget}"))

        index = build_index(settings)
        rows.append(("notes://index(200 篇)", len(index), f"预算 {settings.index_budget}"))

        resource = read_note_resource(settings, "d/n000.md")
        rows.append(("notes://note/{path}(超长笔记)", len(resource), f"上限 {settings.max_note_chars}"))

        payload = json.loads(index)
        print(f"{'原语':34} {'实测字符数':>10}  {'约束':<20} 状态")
        print("-" * 88)
        for label, size, limit in rows:
            print(f"{label:34} {size:>10,}  {limit:<20} {'OK' if size < 21000 else 'CHECK'}")

        print()
        print(f"index 条目：count={payload['count']} returned={payload['returned']} truncated={payload['truncated']}")
        print(f"search 命中笔记数：{search.notes_matched}，实际返回：{search.notes_returned}，截断：{search.truncated}")
        print()
        print("最坏情况合计（一次工具调用）：约", f"{max(len(search.text), len(read.text)):,}", "字符")
        print("参考：8000 字符 ≈ 4000-6000 个中文 token，约占 200K 上下文窗口的 2-3%。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

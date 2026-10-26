"""测试夹具：在 tmp_path 里造一个可控的笔记目录。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from notes_mcp.config import Settings


@pytest.fixture()
def notes_root(tmp_path: Path) -> Path:
    root = tmp_path / "notes"
    (root / "daily").mkdir(parents=True)
    (root / "projects").mkdir()
    (root / "hidden" / ".obsidian").mkdir(parents=True)

    # 一篇命中 "MCP" 的笔记：命中行在中间，便于验证 ±2 行上下文
    (root / "daily" / "2026-10-25.md").write_text(
        "# 十月二十五日\n"
        "\n"
        "第一段，与关键词无关。\n"
        "第二段，还是无关。\n"
        "今天研究了 MCP 的 tools/call 报文。\n"
        "发现 params 里必须带 _meta。\n"
        "这里也是无关内容。\n"
        "继续无关。\n"
        "\n"
        "#daily #mcp\n",
        encoding="utf-8",
    )

    (root / "projects" / "design.md").write_text(
        "# 设计草案\n"
        "\n"
        "MCP 的 Resource 与 Tool 的区别在于谁来触发。\n"
        "\n"
        "```python\n"
        "# 这行是代码块里的注释，不该被当成标签\n"
        "x = 1\n"
        "```\n"
        "\n"
        "#mcp #design\n",
        encoding="utf-8",
    )

    # 无关笔记：验证 search 不会误命中
    (root / "projects" / "unrelated.md").write_text(
        "# 购物清单\n\n牛奶\n鸡蛋\n#life\n",
        encoding="utf-8",
    )

    # 藏在 .obsidian 里的文件：必须被跳过
    (root / "hidden" / ".obsidian" / "workspace.md").write_text("# 配置\nMCP\n", encoding="utf-8")

    # 非 markdown：必须被跳过
    (root / "projects" / "notes.txt").write_text("MCP MCP MCP", encoding="utf-8")

    # 根目录外的"机密文件"，供路径穿越用例使用
    (tmp_path / "secret.md").write_text("# secret\n不该被读到\n", encoding="utf-8")

    _touch_offsets(root)
    return root


def _touch_offsets(root: Path) -> None:
    """把 mtime 错开，让 list_recent 的筛选有意义。"""
    now = time.time()
    offsets = {
        "daily/2026-10-25.md": 1 * 3600,
        "projects/design.md": 3 * 86_400,
        "projects/unrelated.md": 30 * 86_400,
    }
    for rel, ago in offsets.items():
        stamp = now - ago
        os.utime(root / rel, (stamp, stamp))


@pytest.fixture()
def settings(notes_root: Path) -> Settings:
    return Settings(root=notes_root.resolve())

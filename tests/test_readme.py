"""README.md 客户端配置的单测：JSON 代码块必须合法，macOS/Linux 命令必须在场。

P2-3：Claude 与 Cursor 两节只给了 Windows 的 `command`，macOS/Linux 用户
照抄会直接配错（路径根本不存在）。测试锁住：两节各有一行 `.venv/bin/python`，
且命令与 --root 都是绝对路径。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _section(readme: str, heading: str) -> str:
    """取 `### <heading>` 到下一个 `###` 之间的正文。"""
    start = readme.index(f"### {heading}")
    rest = readme[start:]
    nxt = rest.find("\n### ", 1)
    return rest if nxt == -1 else rest[:nxt]


def _json_configs(section: str) -> list[dict[str, Any]]:
    """解析一节里的全部 ```json 代码块。"""
    configs = []
    for block in re.findall(r"```json\n(.*?)```", section, re.S):
        configs.append(json.loads(block))
    return configs


def _is_absolute_command(command: str) -> bool:
    """Windows 绝对路径（盘符开头）与 POSIX 绝对路径（斜杠开头）都算。"""
    return command.startswith("/") or bool(re.match(r"^[A-Za-z]:\\", command))


def test_readme_json_blocks_are_valid() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", readme, re.S)
    assert blocks, "README 里没有任何 JSON 代码块"
    for block in blocks:
        json.loads(block)


def test_readme_client_commands_cover_macos_linux() -> None:
    """Claude 与 Cursor 两节：Windows 命令与 macOS/Linux 命令各有一行，
    且命令与 --root 都是绝对路径、`-m notes_mcp` 的调用形式。"""
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("Claude Desktop", "Cursor"):
        configs = _json_configs(_section(readme, heading))
        assert configs, f"{heading} 一节里没有 JSON 配置块"
        commands = [c["mcpServers"]["notes"]["command"] for c in configs]
        assert any(c.endswith(".venv/bin/python") for c in commands), heading
        assert any(c.endswith("python.exe") for c in commands), heading
        for config in configs:
            server = config["mcpServers"]["notes"]
            assert _is_absolute_command(server["command"]), server["command"]
            assert server["args"][0:2] == ["-m", "notes_mcp"]
            assert _is_absolute_command(server["args"][3]), server["args"][3]

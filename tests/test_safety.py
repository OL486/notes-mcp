"""路径安全：三个必测的恶意输入 + 若干边界。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from notes_mcp.safety import PathRejected, resolve_note_path, to_note_uri


def test_accepts_plain_relative_path(notes_root: Path) -> None:
    got = resolve_note_path(notes_root, "daily/2026-10-25.md")
    assert got == (notes_root / "daily" / "2026-10-25.md").resolve()


def test_accepts_backslash_separator(notes_root: Path) -> None:
    """Windows 用户/模型经常给反斜杠，归一化后应当正常。"""
    got = resolve_note_path(notes_root, "daily\\2026-10-25.md")
    assert got.name == "2026-10-25.md"


def test_rejects_parent_traversal(notes_root: Path) -> None:
    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "../../secret.md")
    assert "越界" in str(excinfo.value) or "穿越" in str(excinfo.value)


def test_rejects_backslash_traversal(notes_root: Path) -> None:
    with pytest.raises(PathRejected):
        resolve_note_path(notes_root, "..\\..\\secret.md")


def test_rejects_absolute_posix(notes_root: Path) -> None:
    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "/etc/passwd")
    assert "绝对路径" in str(excinfo.value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 盘符路径")
def test_rejects_absolute_windows(notes_root: Path) -> None:
    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "C:\\Windows\\win.ini")
    assert "绝对路径" in str(excinfo.value)


def test_rejects_nul_byte(notes_root: Path) -> None:
    with pytest.raises(PathRejected):
        resolve_note_path(notes_root, "daily/2026-10-25.md\x00.txt")


def test_rejects_non_markdown(notes_root: Path) -> None:
    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "projects/notes.txt")
    assert "不支持的文件类型" in str(excinfo.value)


def test_rejects_missing_file(notes_root: Path) -> None:
    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "daily/nope.md")
    assert "不存在" in str(excinfo.value)


def test_rejects_empty(notes_root: Path) -> None:
    with pytest.raises(PathRejected):
        resolve_note_path(notes_root, "   ")


def test_rejects_symlink_escape(notes_root: Path, tmp_path: Path) -> None:
    """符号链接逃逸：纯字符串检查完全看不出问题，只有 resolve 之后才暴露。"""
    link = notes_root / "escape.md"
    try:
        os.symlink(tmp_path / "secret.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接（Windows 需要开发者模式或管理员）")

    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "escape.md")
    assert "越界" in str(excinfo.value)


def test_allows_symlink_inside_root(notes_root: Path) -> None:
    """指向根目录内部的软链接是合法的，不该被误杀。"""
    link = notes_root / "alias.md"
    target = notes_root / "projects" / "design.md"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    assert resolve_note_path(notes_root, "alias.md") == target.resolve()


def test_error_message_is_actionable(notes_root: Path) -> None:
    """错误文本必须是给模型看的：说清错在哪 + 怎么改。"""
    with pytest.raises(PathRejected) as excinfo:
        resolve_note_path(notes_root, "../secret.md")
    message = str(excinfo.value)
    assert "。" in message  # 有第二句建议
    assert "相对路径" in message


def test_to_note_uri_keeps_slashes() -> None:
    assert to_note_uri("daily/2026-10-25.md") == "notes://note/daily/2026-10-25.md"
    assert to_note_uri("a b/c.md") == "notes://note/a%20b/c.md"

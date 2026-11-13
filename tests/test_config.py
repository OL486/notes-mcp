"""config.py 的直接单测：默认值、显式参数、环境变量回退。

原来 load_settings 只有间接覆盖；环境变量解析失败时退回默认值、
显式参数优先于环境变量这些分支都没有直接测试。
"""

from __future__ import annotations

from pathlib import Path

from notes_mcp.config import (
    ENV_MAX_NOTE_CHARS,
    ENV_ROOT,
    ENV_SEARCH_BUDGET,
    Settings,
    load_settings,
)


def test_defaults(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path)
    assert settings.max_note_chars == 20_000
    assert settings.search_budget == 8_000
    assert settings.index_budget == 8_000
    assert settings.recent_budget == 4_000
    assert settings.stats_budget == 3_000
    assert settings.fragments_per_note == 3
    assert settings.context_lines == 2
    assert settings.max_fragment_lines == 15
    assert settings.max_limit == 20


def test_explicit_parameters_override_defaults(tmp_path: Path) -> None:
    settings = load_settings(
        tmp_path, max_note_chars=1000, search_budget=2000
    )
    assert settings.root == tmp_path.resolve()
    assert settings.max_note_chars == 1000
    assert settings.search_budget == 2000


def test_root_is_resolved(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "sub" / "..")
    assert settings.root == tmp_path.resolve()
    assert settings.root.is_absolute()


def test_env_vars_are_used(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_MAX_NOTE_CHARS, "1000")
    monkeypatch.setenv(ENV_SEARCH_BUDGET, "2000")
    settings = load_settings(tmp_path)
    assert settings.max_note_chars == 1000
    assert settings.search_budget == 2000


def test_env_root_is_used(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_ROOT, str(tmp_path))
    settings = load_settings()
    assert settings.root == tmp_path.resolve()


def test_invalid_env_value_falls_back_to_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_MAX_NOTE_CHARS, "not-a-number")
    monkeypatch.setenv(ENV_SEARCH_BUDGET, "0")
    settings = load_settings(tmp_path)
    assert settings.max_note_chars == 20_000
    assert settings.search_budget == 8_000


def test_negative_env_value_falls_back_to_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_MAX_NOTE_CHARS, "-5")
    settings = load_settings(tmp_path)
    assert settings.max_note_chars == 20_000


def test_explicit_parameter_beats_env_var(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_MAX_NOTE_CHARS, "1000")
    settings = load_settings(tmp_path, max_note_chars=777)
    assert settings.max_note_chars == 777

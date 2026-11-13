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


def test_all_fields_exposed_via_explicit_parameters(tmp_path: Path) -> None:
    """其余 7 个字段也能用显式参数覆盖，不再只能改前两个。"""
    settings = load_settings(
        tmp_path,
        index_budget=100,
        recent_budget=200,
        stats_budget=300,
        fragments_per_note=2,
        context_lines=1,
        max_fragment_lines=5,
        max_limit=10,
    )
    assert settings.index_budget == 100
    assert settings.recent_budget == 200
    assert settings.stats_budget == 300
    assert settings.fragments_per_note == 2
    assert settings.context_lines == 1
    assert settings.max_fragment_lines == 5
    assert settings.max_limit == 10


def test_all_fields_exposed_via_env_vars(monkeypatch, tmp_path: Path) -> None:
    from notes_mcp.config import (
        ENV_CONTEXT_LINES,
        ENV_FRAGMENTS_PER_NOTE,
        ENV_INDEX_BUDGET,
        ENV_MAX_FRAGMENT_LINES,
        ENV_MAX_LIMIT,
        ENV_RECENT_BUDGET,
        ENV_STATS_BUDGET,
    )

    monkeypatch.setenv(ENV_INDEX_BUDGET, "100")
    monkeypatch.setenv(ENV_RECENT_BUDGET, "200")
    monkeypatch.setenv(ENV_STATS_BUDGET, "300")
    monkeypatch.setenv(ENV_FRAGMENTS_PER_NOTE, "2")
    monkeypatch.setenv(ENV_CONTEXT_LINES, "1")
    monkeypatch.setenv(ENV_MAX_FRAGMENT_LINES, "5")
    monkeypatch.setenv(ENV_MAX_LIMIT, "10")
    settings = load_settings(tmp_path)
    assert settings.index_budget == 100
    assert settings.recent_budget == 200
    assert settings.stats_budget == 300
    assert settings.fragments_per_note == 2
    assert settings.context_lines == 1
    assert settings.max_fragment_lines == 5
    assert settings.max_limit == 10


def test_non_positive_field_is_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="max_note_chars"):
        Settings(root=tmp_path, max_note_chars=0)
    with pytest.raises(ValueError, match="search_budget"):
        Settings(root=tmp_path, search_budget=-1)
    with pytest.raises(ValueError, match="max_limit"):
        load_settings(tmp_path, max_limit=0)

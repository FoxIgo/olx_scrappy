from __future__ import annotations

from pathlib import Path

import pytest

from scrappy.application.policy import PipelinePolicy
from scrappy.infrastructure.config.policy import build_pipeline_policy
from scrappy.infrastructure.config.settings import DEFAULT_LLM_MODEL, HOME, Settings, find_home
from scrappy.infrastructure.config.sources import parse_sources


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("SCRAPPY_") or key == "OPENROUTER_API_KEY":
            monkeypatch.delenv(key)


def test_defaults(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # pyright: ignore[reportCallIssue]
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert settings.database_url.endswith("/scrappy.db")
    assert settings.archive_dir == tmp_path / "raw"
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.openrouter_api_key is None
    assert settings.extraction_file == settings.config_dir / "extraction.yaml"


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPPY_LLM_MODEL", "x/y")
    monkeypatch.setenv("SCRAPPY_WORKER_BATCH_SIZE", "3")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.llm_model == "x/y"
    assert settings.worker_batch_size == 3
    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "sk-secret"
    assert "sk-secret" not in repr(settings)


def test_from_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SCRAPPY_LOG_LEVEL=DEBUG\nOPENROUTER_API_KEY=k\n", encoding="utf-8")
    settings = Settings(_env_file=env)  # pyright: ignore[reportCallIssue]
    assert settings.log_level == "DEBUG"
    assert settings.openrouter_api_key is not None


def test_policy_from_settings_and_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPPY_LLM_MAX_DESCRIPTION_CHARS", "500")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    sources = parse_sources(
        {"sources": {"olx_pl": {"health": {"max_rejected_ratio": 0.2}}}}, path=Path("s.yaml")
    )
    policy = build_pipeline_policy(settings, sources)
    assert isinstance(policy, PipelinePolicy)
    assert policy.extraction.description_max_chars == 500
    (source_id,) = sources.sources
    assert policy.health.for_source(source_id).max_rejected_ratio == 0.2


def test_relative_paths_do_not_depend_on_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, data_dir=Path("data"))  # pyright: ignore[reportCallIssue]

    assert settings.data_dir == HOME / "data"
    assert settings.config_dir == HOME / "config"
    assert settings.archive_dir == HOME / "data" / "raw"
    assert settings.database_url == f"sqlite+aiosqlite:///{(HOME / 'data').as_posix()}/scrappy.db"
    assert (HOME / "config" / "categories.yaml").is_file()  # HOME is packages/server


def test_absolute_paths_are_kept(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, config_dir=tmp_path)  # pyright: ignore[reportCallIssue]

    assert (settings.data_dir, settings.config_dir) == (tmp_path, tmp_path)


def test_scrappy_home_overrides_the_detected_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCRAPPY_HOME", str(tmp_path))

    assert find_home() == tmp_path.resolve()

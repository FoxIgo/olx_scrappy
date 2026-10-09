"""``config/extraction.yaml`` -> profiles and reconciler policy (ADR 0010 section 8)."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from scrappy.application.ports.extraction_backends import ExtractionMode, StructuredOutput
from scrappy.infrastructure.config.errors import ConfigError
from scrappy.infrastructure.config.extraction import (
    load_extraction_config,
    parse_extraction_config,
    parse_rate,
)
from scrappy.infrastructure.config.settings import Settings
from scrappy.infrastructure.extraction.openai_compatible import OpenAICompatibleExtractor
from scrappy.infrastructure.extraction.openrouter import OpenRouterAttributeExtractor
from scrappy.infrastructure.extraction.profiles import (
    UnavailableExtractor,
    build_profile,
    build_profiles,
)
from scrappy.infrastructure.extraction.prompt import PROMPT_VERSION

REPO_CONFIG = Path(__file__).resolve().parents[4] / "config" / "extraction.yaml"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("SCRAPPY_") or key.endswith("_API_KEY"):
            monkeypatch.delenv(key)


def settings(tmp_path: Path, **values: object) -> Settings:
    return Settings(_env_file=None, config_dir=tmp_path, data_dir=tmp_path, **values)  # pyright: ignore[reportCallIssue]


FULL = {
    "default_profile": "local",
    "fallback": ["remote"],
    "reconciler": {"interval_seconds": 5, "max_attempts": 3, "description_max_chars": 2000},
    "profiles": {
        "local": {
            "provider": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b-instruct",
            "concurrency": 1,
            "structured_output": "json_schema",
            "extra_body": {"options": {"num_ctx": 8192}},
            "timeout_seconds": 120,
            "probe": False,
        },
        "remote": {
            "provider": "openrouter",
            "model": "openai/gpt-4.1-nano",
            "mode": "auto",
            "concurrency": 4,
            "rate_limit": "15/min",
            "daily_limit": 1000,
            "temperature": 0.1,
            "batch": {"min_size": 10, "max_size": 100, "max_wait_minutes": 5},
        },
    },
}


def test_parse_full_file(tmp_path: Path) -> None:
    config = parse_extraction_config(FULL, path=tmp_path / "x.yaml", settings=settings(tmp_path))
    assert (config.default_profile, config.fallback) == ("local", ("remote",))
    local, remote = config.profiles["local"], config.profiles["remote"]
    assert local.extra_body == {"options": {"num_ctx": 8192}}
    assert not local.probe
    assert remote.mode is ExtractionMode.AUTO
    assert remote.rate_limit_per_minute == 15
    assert remote.daily_limit == 1000
    assert remote.batch.min_size == 10
    assert remote.batch.max_wait == timedelta(minutes=5)
    assert config.policy.reconcile_interval == timedelta(seconds=5)
    assert config.policy.retry.max_attempts == 3
    assert config.policy.description_max_chars == 2000


@pytest.mark.parametrize(
    ("value", "per_minute"), [("15/min", 15.0), ("2/s", 120.0), ("600/h", 10.0), (30, 30.0)]
)
def test_rates(value: str | float, per_minute: float) -> None:
    assert parse_rate(value) == pytest.approx(per_minute)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"default_profile": "nope"}, r"unknown profile\(s\) nope"),
        ({"fallback": ["ghost"]}, r"unknown profile\(s\) ghost"),
        ({"profiles": {"local": {"provider": "x", "model": "m", "colour": 1}}}, "colour"),
        ({"profiles": {"local": {"provider": "x", "model": "m", "rate_limit": "fast"}}}, "rate"),
        ({"profiles": {"local": {"provider": "x", "model": "m", "mode": "turbo"}}}, "mode"),
    ],
)
def test_invalid_files_name_the_problem(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    data = {**FULL, **change}
    if "profiles" in change and "default_profile" not in change:
        data["fallback"] = []
    with pytest.raises(ConfigError, match=message):
        parse_extraction_config(data, path=tmp_path / "x.yaml", settings=settings(tmp_path))


def test_missing_file_derives_the_legacy_openrouter_profile(tmp_path: Path) -> None:
    config = load_extraction_config(
        settings(tmp_path, llm_model="x/y", llm_structured_output=False)
    )
    assert config.default_profile == "openrouter"
    profile = config.profiles["openrouter"]
    assert (profile.provider, profile.model) == ("openrouter", "x/y")
    assert profile.structured_output is StructuredOutput.JSON_OBJECT
    assert profile.concurrency == 1
    assert profile.mode is ExtractionMode.SYNC
    assert "SCRAPPY_LLM_" in config.source


async def test_profiles_are_built_without_network(tmp_path: Path) -> None:
    config = parse_extraction_config(FULL, path=tmp_path / "x.yaml", settings=settings(tmp_path))
    profiles = build_profiles(config, settings(tmp_path))
    local = profiles.get("local")
    assert isinstance(local.extractor, OpenAICompatibleExtractor)
    assert local.prompt_version == PROMPT_VERSION
    assert local.capabilities.supports_batch is False  # no batch backend registered yet
    remote = profiles.get("remote")
    assert isinstance(remote.extractor, UnavailableExtractor)  # no key in the environment
    health = await remote.health.check()
    assert not health.ok
    assert "OPENROUTER_API_KEY is not set" in health.detail
    assert list(profiles.fallback) == ["local", "remote"]

    keyed = build_profiles(config, settings(tmp_path, openrouter_api_key="k"))
    assert isinstance(keyed.get("remote").extractor, OpenRouterAttributeExtractor)


def test_api_key_env_is_optional_but_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {
        "default_profile": "studio",
        "profiles": {
            "studio": {
                "provider": "openai_compatible",
                "base_url": "http://localhost:1234/v1",
                "model": "m",
                "api_key_env": "STUDIO_API_KEY",
            }
        },
    }
    config = parse_extraction_config(raw, path=tmp_path / "x.yaml", settings=settings(tmp_path))
    profile = config.profiles["studio"]
    assert isinstance(build_profile(profile, settings(tmp_path)).extractor, UnavailableExtractor)
    monkeypatch.setenv("STUDIO_API_KEY", "secret")
    assert isinstance(
        build_profile(profile, settings(tmp_path)).extractor, OpenAICompatibleExtractor
    )


def test_unknown_provider_and_missing_base_url_are_config_errors(tmp_path: Path) -> None:
    raw = {
        "default_profile": "g",
        "profiles": {"g": {"provider": "gemini", "model": "gemini-2.5-flash-lite"}},
    }
    config = parse_extraction_config(raw, path=tmp_path / "x.yaml", settings=settings(tmp_path))
    with pytest.raises(ConfigError, match="unknown provider 'gemini'"):
        build_profiles(config, settings(tmp_path))
    raw = {
        "default_profile": "l",
        "profiles": {"l": {"provider": "openai_compatible", "model": "m"}},
    }
    config = parse_extraction_config(raw, path=tmp_path / "x.yaml", settings=settings(tmp_path))
    with pytest.raises(ConfigError, match="needs base_url"):
        build_profiles(config, settings(tmp_path))


def test_the_shipped_example_file_is_valid(tmp_path: Path) -> None:
    data = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
    config = parse_extraction_config(data, path=REPO_CONFIG, settings=settings(tmp_path))
    assert config.default_profile == "gemini-lite"
    assert config.fallback == ("gemini-lite", "gemini-lite-31", "gemma-31b", "gemma-26b")
    assert config.profiles["lmstudio"].extra_body == {"reasoning_effort": "none"}
    # lmstudio (slow) and openrouter (paid) are defined but not in the chain
    assert {"lmstudio", "openrouter"} <= set(config.profiles) - set(config.fallback)
    models = {n: config.profiles[n].model for n in config.fallback}
    assert models == {
        "gemini-lite": "gemini-3.5-flash-lite",
        "gemini-lite-31": "gemini-3.1-flash-lite",
        "gemma-31b": "gemma-4-31b-it",
        "gemma-26b": "gemma-4-26b-a4b-it",
    }
    for name in config.fallback:
        profile = config.profiles[name]
        assert profile.provider == "openai_compatible"
        assert profile.api_key_env == "GOOGLE_API_KEY"
        assert profile.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert profile.structured_output is StructuredOutput.JSON_SCHEMA
        assert profile.quota_timezone == "America/Los_Angeles"
        assert profile.rate_limit_per_minute is not None
        assert profile.daily_limit is not None
        if name.startswith("gemma"):
            assert profile.extra_body == {}  # thinking cannot be switched off on Google
            assert profile.concurrency >= 6
    assert (config.profiles["gemini-lite"].daily_limit or 10**9) < 500
    assert (config.profiles["gemma-31b"].daily_limit or 10**9) < 14_400
    build_profiles(config, settings(tmp_path))


def _google_gemma(**extra: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "provider": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemma-4-31b-it",
        **extra,
    }
    return {"default_profile": "g", "profiles": {"g": profile}}


@pytest.mark.parametrize("key", ["reasoning_effort", "thinking_config"])
def test_thinking_options_are_refused_for_gemma_on_google(tmp_path: Path, key: str) -> None:
    raw = _google_gemma(extra_body={key: "none"})
    with pytest.raises(ConfigError, match="cannot be disabled"):
        parse_extraction_config(raw, path=tmp_path / "x.yaml", settings=settings(tmp_path))


def test_quota_timezone_defaults_to_utc_and_must_be_known(tmp_path: Path) -> None:
    ok = parse_extraction_config(
        _google_gemma(), path=tmp_path / "x.yaml", settings=settings(tmp_path)
    )
    assert ok.profiles["g"].quota_timezone == "UTC"
    with pytest.raises(ConfigError, match="unknown quota timezone"):
        parse_extraction_config(
            _google_gemma(quota_timezone="Mars/Olympus"),
            path=tmp_path / "x.yaml",
            settings=settings(tmp_path),
        )
    profile = build_profile(
        parse_extraction_config(
            _google_gemma(quota_timezone="America/Los_Angeles"),
            path=tmp_path / "x.yaml",
            settings=settings(tmp_path),
        ).profiles["g"],
        settings(tmp_path),
    )
    assert profile.capabilities.quota_timezone == "America/Los_Angeles"

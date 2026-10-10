"""``config/extraction.yaml`` -> extraction profiles + the reconciler policy (ADR 0010 §8).

Format::

    pool: [gemini-lite, gemma-31b]    # profiles that run IN PARALLEL (one lane each)
    quota_groups:                     # optional: profiles that share ONE daily limit
      openrouter_free: {daily_limit: 50, quota_timezone: UTC}
    reconciler:                       # all optional
      interval_seconds: 30
      poll_interval_seconds: 60
      max_attempts: 5                 # failures before an offer is parked
      backoff_base_seconds: 60
      backoff_max_minutes: 360
      quota_cooldown_minutes: 60
      sync_lease_minutes: 10
      max_items_per_tick: 200
      health_ttl_minutes: 5
      submitting_timeout_minutes: 10
      description_max_chars: 4000     # default: SCRAPPY_LLM_MAX_DESCRIPTION_CHARS
    tiering:                          # ADR 0012, all optional
      enabled: false                  # true: rules for every offer, LLM only for the ones below
      top_n: 25                       # per scoring strategy: best provisional deals -> LLM
      min_coverage: 0.5               # provisional score coverage needed to count for top_n
      escalate: ["*"]                 # rule uncertainty reasons that go to the LLM ("*" = all)
    profiles:
      local:
        provider: openai_compatible   # openai_compatible | openrouter
        base_url: http://localhost:11434/v1
        model: qwen2.5:7b-instruct    # optional: defaults to SCRAPPY_LLM_MODEL
        api_key_env: null             # optional; local servers need no key
        mode: sync                    # sync | batch | auto
        structured_output: json_schema  # json_schema | json_object | prompt_only
        concurrency: 1
        rate_limit: 15/min            # N/min, N/s, N/h or a number (per minute)
        daily_limit: 1000             # requests per day (quota_timezone midnight resets it)
        quota_timezone: UTC           # IANA name, e.g. America/Los_Angeles for Google AI Studio
        quota_group: null             # a quota_groups entry: replaces daily_limit/quota_timezone
        paid: false                   # OpenRouter only: true allows a non-":free" model in the pool
        timeout_seconds: 120
        temperature: 0
        headers: {}
        extra_body: {options: {num_ctx: 8192}}
        probe: true                   # allow a one-request structured-output probe
        batch: {min_size: 20, max_size: 200, max_open: 3, max_wait_minutes: 30, lease_hours: 26}

Secrets never live here: ``api_key_env`` names an environment variable (or ``.env`` entry).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from scrappy.application.extraction.profile_status import quota_tz
from scrappy.application.policy import ALL_REASONS, ExtractionPolicy, TieringPolicy
from scrappy.application.ports.extraction_backends import (
    BatchSettings,
    ExtractionMode,
    StructuredOutput,
)
from scrappy.domain.extraction import ExtractionRetryPolicy
from scrappy.domain.shared import InvalidValueError
from scrappy.infrastructure.config.errors import ConfigError, format_validation_error
from scrappy.infrastructure.config.settings import Settings
from scrappy.infrastructure.config.yaml_io import read_yaml

_RATE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(s|sec|second|m|min|minute|h|hour)\s*$")
_PER_MINUTE = {"s": 60.0, "sec": 60.0, "second": 60.0, "m": 1.0, "min": 1.0, "minute": 1.0}


def parse_rate(value: str | float | None) -> float | None:
    """``15/min`` -> 15.0, ``2/s`` -> 120.0, ``600/h`` -> 10.0, ``30`` -> 30.0 (per minute)."""
    if value is None:
        return None
    if isinstance(value, int | float):
        rate = float(value)
    else:
        match = _RATE.match(value)
        if match is None:
            raise ValueError(f"invalid rate {value!r}; use e.g. 15/min, 2/s or 600/h")
        rate = float(match[1]) * _PER_MINUTE.get(match[2], 1 / 60)
    if rate <= 0:
        raise ValueError("rate must be > 0")
    return rate


class _BatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_size: int = Field(default=20, ge=1)
    max_size: int = Field(default=200, ge=1)
    max_open: int = Field(default=3, ge=1)
    max_wait_minutes: float = Field(default=30, gt=0)
    lease_hours: float = Field(default=26, gt=0)


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    mode: Literal["sync", "batch", "auto"] = "sync"
    structured_output: Literal["json_schema", "json_object", "prompt_only"] = "json_schema"
    concurrency: int = Field(default=1, ge=1)
    rate_limit: str | float | None = None
    daily_limit: int | None = Field(default=None, ge=1)
    quota_timezone: str = "UTC"
    quota_group: str | None = None
    paid: bool = False
    timeout_seconds: float = Field(default=60, gt=0)
    temperature: float = Field(default=0, ge=0)
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    extra_body: dict[str, Any] = Field(default_factory=dict[str, Any])
    probe: bool = True
    batch: _BatchModel = Field(default_factory=_BatchModel)

    @field_validator("quota_timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            quota_tz(value)
        except InvalidValueError as error:
            raise ValueError(str(error)) from error
        return value

    @field_validator("rate_limit")
    @classmethod
    def _rate(cls, value: str | float | None) -> str | float | None:
        parse_rate(value)
        return value


class _QuotaGroupModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_limit: int = Field(ge=1)
    quota_timezone: str = "UTC"

    @field_validator("quota_timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            quota_tz(value)
        except InvalidValueError as error:
            raise ValueError(str(error)) from error
        return value


class _ReconcilerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: float = Field(default=30, gt=0)
    poll_interval_seconds: float = Field(default=60, gt=0)
    max_attempts: int = Field(default=5, ge=1)
    backoff_base_seconds: float = Field(default=60, gt=0)
    backoff_max_minutes: float = Field(default=360, gt=0)
    quota_cooldown_minutes: float = Field(default=60, gt=0)
    sync_lease_minutes: float = Field(default=10, gt=0)
    max_items_per_tick: int = Field(default=200, ge=1)
    health_ttl_minutes: float = Field(default=5, gt=0)
    submitting_timeout_minutes: float = Field(default=10, gt=0)
    description_max_chars: int | None = Field(default=None, ge=100)


class _TieringModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    top_n: int = Field(default=25, ge=0)
    min_coverage: float = Field(default=0.5, ge=0, le=1)
    escalate: list[str] = Field(default_factory=lambda: [ALL_REASONS])


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pool: list[str] = Field(min_length=1)
    quota_groups: dict[str, _QuotaGroupModel] = Field(default_factory=dict[str, _QuotaGroupModel])
    reconciler: _ReconcilerModel = Field(default_factory=_ReconcilerModel)
    tiering: _TieringModel = Field(default_factory=_TieringModel)
    profiles: dict[str, _ProfileModel] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    name: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    mode: ExtractionMode = ExtractionMode.SYNC
    structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA
    concurrency: int = 1
    rate_limit_per_minute: float | None = None
    daily_limit: int | None = None
    quota_timezone: str = "UTC"
    quota_group: str | None = None
    paid: bool = False
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    headers: dict[str, str] = field(default_factory=dict[str, str])
    extra_body: dict[str, Any] = field(default_factory=dict[str, Any])
    probe: bool = True
    batch: BatchSettings = field(default_factory=BatchSettings)


@dataclass(frozen=True, slots=True)
class ExtractionConfig:
    pool: tuple[str, ...]
    """Profiles that run in parallel, one lane each; the first is the "default" profile."""
    profiles: dict[str, ProfileConfig]
    policy: ExtractionPolicy
    source: str
    """Where it came from (file path, or the SCRAPPY_LLM_* fallback)."""


def _policy(
    model: _ReconcilerModel, settings: Settings, tiering: _TieringModel | None = None
) -> ExtractionPolicy:
    tiers = tiering or _TieringModel()
    return ExtractionPolicy(
        description_max_chars=model.description_max_chars or settings.llm_max_description_chars,
        retry=ExtractionRetryPolicy(
            max_attempts=model.max_attempts,
            base_delay=timedelta(seconds=model.backoff_base_seconds),
            max_delay=max(
                timedelta(minutes=model.backoff_max_minutes),
                timedelta(seconds=model.backoff_base_seconds),
            ),
        ),
        reconcile_interval=timedelta(seconds=model.interval_seconds),
        poll_interval=timedelta(seconds=model.poll_interval_seconds),
        sync_lease=timedelta(minutes=model.sync_lease_minutes),
        max_items_per_tick=model.max_items_per_tick,
        quota_cooldown=timedelta(minutes=model.quota_cooldown_minutes),
        health_ttl=timedelta(minutes=model.health_ttl_minutes),
        submitting_timeout=timedelta(minutes=model.submitting_timeout_minutes),
        tiering=TieringPolicy(
            enabled=tiers.enabled,
            top_n=tiers.top_n,
            min_coverage=tiers.min_coverage,
            escalate=frozenset(tiers.escalate),
        ),
    )


def parse_extraction_config(data: object, *, path: Path, settings: Settings) -> ExtractionConfig:
    if isinstance(data, dict) and ("default_profile" in data or "fallback" in data):
        raise ConfigError(
            f"{path.name} ({path}): 'default_profile' and 'fallback' were replaced by 'pool: "
            "[profile, ...]' (profiles run in parallel, not one after another; see ADR 0010 "
            "section 9). Example: pool: [gemini-lite, gemma-31b]"
        )
    try:
        model = _FileModel.model_validate(data)
    except ValidationError as error:
        raise ConfigError(format_validation_error(path, error)) from error
    names = set(model.profiles)
    if len(set(model.pool)) != len(model.pool):
        raise ConfigError(f"{path.name} ({path}): pool lists a profile twice")
    unknown = [n for n in model.pool if n not in names]
    if unknown:
        raise ConfigError(
            f"{path.name} ({path}): unknown profile(s) {', '.join(unknown)} "
            f"(defined: {', '.join(sorted(names))})"
        )
    profiles: dict[str, ProfileConfig] = {}
    for name, raw in model.profiles.items():
        try:
            batch = BatchSettings(
                min_size=raw.batch.min_size,
                max_size=raw.batch.max_size,
                max_open=raw.batch.max_open,
                max_wait=timedelta(minutes=raw.batch.max_wait_minutes),
                lease=timedelta(hours=raw.batch.lease_hours),
            )
        except InvalidValueError as error:
            raise ConfigError(f"{path.name} ({path}): profiles.{name}.{error}") from error
        _reject_google_thinking_options(path, name, raw)
        daily_limit, quota_timezone = raw.daily_limit, raw.quota_timezone
        if raw.quota_group is not None:
            group = model.quota_groups.get(raw.quota_group)
            if group is None:
                raise ConfigError(
                    f"{path.name} ({path}): profiles.{name}.quota_group {raw.quota_group!r} is "
                    f"not defined in quota_groups (defined: {', '.join(model.quota_groups) or '-'})"
                )
            if raw.daily_limit is not None or "quota_timezone" in raw.model_fields_set:
                raise ConfigError(
                    f"{path.name} ({path}): profiles.{name}: daily_limit/quota_timezone come "
                    f"from quota group {raw.quota_group!r}; remove them from the profile"
                )
            daily_limit, quota_timezone = group.daily_limit, group.quota_timezone
        profiles[name] = ProfileConfig(
            name=name,
            provider=raw.provider,
            model=raw.model or settings.llm_model,
            base_url=raw.base_url,
            api_key_env=raw.api_key_env,
            mode=ExtractionMode(raw.mode),
            structured_output=StructuredOutput(raw.structured_output),
            concurrency=raw.concurrency,
            rate_limit_per_minute=parse_rate(raw.rate_limit),
            daily_limit=daily_limit,
            quota_timezone=quota_timezone,
            quota_group=raw.quota_group,
            paid=raw.paid,
            timeout_seconds=raw.timeout_seconds,
            temperature=raw.temperature,
            headers=dict(raw.headers),
            extra_body=dict(raw.extra_body),
            probe=raw.probe,
            batch=batch,
        )
    _reject_paid_openrouter_in_pool(path, model.pool, profiles)
    return ExtractionConfig(
        pool=tuple(model.pool),
        profiles=profiles,
        policy=_policy(model.reconciler, settings, model.tiering),
        source=str(path),
    )


OPENROUTER_HOST = "openrouter.ai"
FREE_SUFFIX = ":free"


def is_openrouter(config: ProfileConfig) -> bool:
    return config.provider == "openrouter" or OPENROUTER_HOST in (config.base_url or "")


def _reject_paid_openrouter_in_pool(
    path: Path, pool: list[str], profiles: dict[str, ProfileConfig]
) -> None:
    """The pool runs unattended and in parallel: it must never spend money by accident.
    An OpenRouter model whose id does not end in ``:free`` is PAID, so it may join the pool
    only when its profile says ``paid: true`` explicitly."""
    for name in pool:
        config = profiles[name]
        if is_openrouter(config) and not config.model.endswith(FREE_SUFFIX) and not config.paid:
            raise ConfigError(
                f"{path.name} ({path}): pool member {name!r} uses OpenRouter model "
                f"{config.model!r}, which is not a free model (id must end with "
                f"{FREE_SUFFIX!r}). Remove it from the pool, or set 'paid: true' on the "
                "profile to accept that it costs money."
            )


_THINKING_KEYS = ("reasoning_effort", "reasoning", "thinking", "thinking_config", "thinking_budget")


def _reject_google_thinking_options(path: Path, name: str, raw: _ProfileModel) -> None:
    """Gemma on Google AI Studio answers HTTP 400 to any thinking option (it cannot be off)."""
    if "generativelanguage.googleapis.com" not in (raw.base_url or ""):
        return
    if not (raw.model or "").lower().startswith("gemma"):
        return
    bad = [key for key in _THINKING_KEYS if key in raw.extra_body]
    if bad:
        raise ConfigError(
            f"{path.name} ({path}): profiles.{name}.extra_body: {', '.join(bad)} is rejected by "
            "Gemma on Google AI Studio (thinking cannot be disabled); remove it"
        )


LEGACY_PROFILE = "openrouter"


def legacy_extraction_config(settings: Settings) -> ExtractionConfig:
    """Backward compatibility: no extraction.yaml -> one ``openrouter`` sync profile from
    the ``SCRAPPY_LLM_*`` settings (sequential, like the pre-ADR-0010 job handler)."""
    headers: dict[str, str] = {}
    if settings.llm_referer:
        headers["HTTP-Referer"] = settings.llm_referer
    if settings.llm_app_title:
        headers["X-Title"] = settings.llm_app_title
    profile = ProfileConfig(
        name=LEGACY_PROFILE,
        provider="openrouter",
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key_env="OPENROUTER_API_KEY",
        paid=True,
        structured_output=StructuredOutput.JSON_SCHEMA
        if settings.llm_structured_output
        else StructuredOutput.JSON_OBJECT,
        timeout_seconds=settings.llm_timeout,
        headers=headers,
        probe=False,
    )
    return ExtractionConfig(
        pool=(LEGACY_PROFILE,),
        profiles={LEGACY_PROFILE: profile},
        policy=_policy(_ReconcilerModel(), settings),
        source="SCRAPPY_LLM_* settings (no extraction.yaml)",
    )


def load_extraction_config(settings: Settings) -> ExtractionConfig:
    path = settings.extraction_file
    if not path.exists():
        return legacy_extraction_config(settings)
    data = read_yaml(path)
    if data is None:
        raise ConfigError(f"{path.name} ({path}) is empty")
    return parse_extraction_config(data, path=path, settings=settings)

"""Build ``ExtractionProfiles`` from ``ExtractionConfig`` (ADR 0010 section 8).

``PROVIDERS`` maps ``provider:`` names to sync adapter factories; ``BATCH_BACKENDS`` maps
them to batch backend factories. A new provider is one entry here (the Gemini adapter, the
OpenRouter batch backend). The application never sees these names except as provenance.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from scrappy.application.ports.extraction_backends import (
    BatchExtractionBackend,
    ExtractionProfile,
    ProfileCapabilities,
    ProfileHealth,
    StaticExtractionProfiles,
)
from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    RejectionKind,
)
from scrappy.infrastructure.config.errors import ConfigError
from scrappy.infrastructure.config.extraction import ExtractionConfig, ProfileConfig
from scrappy.infrastructure.config.settings import Settings
from scrappy.infrastructure.extraction.openai_compatible import OpenAICompatibleExtractor
from scrappy.infrastructure.extraction.openrouter import (
    OPENROUTER_BASE_URL,
    OPENROUTER_KEY_ENV,
    OpenRouterAttributeExtractor,
)
from scrappy.infrastructure.extraction.prompt import PROMPT_VERSION


class UnavailableExtractor:
    """Stands in for a profile that cannot work (missing API key): every call is
    UNAVAILABLE (no penalty for offers) and the health check says what to fix."""

    def __init__(self, reason: str, model: str) -> None:
        self.reason = reason
        self._model = model

    async def extract(self, request: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection(
            self.reason, retryable=False, model=self._model, kind=RejectionKind.UNAVAILABLE
        )

    async def check(self, *, probe: bool = False) -> ProfileHealth:
        return ProfileHealth(False, self.reason)


type SyncAdapter = OpenAICompatibleExtractor | UnavailableExtractor
type SyncFactory = Callable[[ProfileConfig, Settings], SyncAdapter]
type BatchFactory = Callable[[ProfileConfig, Settings, SyncAdapter], BatchExtractionBackend | None]


def _missing_key(config: ProfileConfig, env: str) -> UnavailableExtractor:
    return UnavailableExtractor(
        f"{env} is not set, so profile {config.name} cannot extract. Set it in .env (or the "
        "environment); the backlog is picked up automatically afterwards.",
        config.model,
    )


def _openai_compatible(config: ProfileConfig, settings: Settings) -> SyncAdapter:
    if not config.base_url:
        raise ConfigError(
            f"extraction profile {config.name}: provider openai_compatible needs base_url"
        )
    api_key: str | None = None
    if config.api_key_env:
        api_key = settings.secret(config.api_key_env)
        if api_key is None:
            return _missing_key(config, config.api_key_env)
    return OpenAICompatibleExtractor(
        base_url=config.base_url,
        model=config.model,
        api_key=api_key,
        structured_output=config.structured_output,
        timeout=config.timeout_seconds,
        headers=config.headers,
        temperature=config.temperature,
        extra_body=config.extra_body,
        key_hint=config.api_key_env,
        transient_retries=2,
        rate_limit_waits=2,
    )


def _openrouter(config: ProfileConfig, settings: Settings) -> SyncAdapter:
    env = config.api_key_env or OPENROUTER_KEY_ENV
    api_key = settings.secret(env)
    if api_key is None:
        return _missing_key(config, env)
    return OpenRouterAttributeExtractor(
        api_key=api_key,
        model=config.model,
        base_url=config.base_url or settings.llm_base_url or OPENROUTER_BASE_URL,
        timeout=config.timeout_seconds,
        structured_output=config.structured_output,
        temperature=config.temperature,
        headers=config.headers,
        extra_body=config.extra_body,
    )


PROVIDERS: dict[str, SyncFactory] = {
    "openai_compatible": _openai_compatible,
    "openrouter": _openrouter,
}
"""Sync adapters by ``provider:`` name. Every provider must have one."""

BATCH_BACKENDS: dict[str, BatchFactory] = {}
"""Batch backends by ``provider:`` name (none yet; the OpenRouter batch adapter registers
``openrouter`` here). A factory may return ``None`` when the profile cannot batch (e.g. the
model has no ``:batch`` endpoint); the profile then runs in sync mode."""


def build_profile(
    config: ProfileConfig,
    settings: Settings,
    *,
    providers: Mapping[str, SyncFactory] = PROVIDERS,
    batch_backends: Mapping[str, BatchFactory] = BATCH_BACKENDS,
) -> ExtractionProfile:
    factory = providers.get(config.provider)
    if factory is None:
        known = ", ".join(sorted(providers))
        raise ConfigError(
            f"extraction profile {config.name}: unknown provider {config.provider!r} "
            f"(known: {known})"
        )
    adapter = factory(config, settings)
    batch_factory = batch_backends.get(config.provider)
    backend = (
        None
        if batch_factory is None or isinstance(adapter, UnavailableExtractor)
        else batch_factory(config, settings, adapter)
    )
    return ExtractionProfile(
        name=config.name,
        provider=config.provider,
        model=config.model,
        prompt_version=PROMPT_VERSION,
        extractor=adapter,
        health=adapter,
        mode=config.mode,
        capabilities=ProfileCapabilities(
            supports_batch=backend is not None,
            structured_output=config.structured_output,
            concurrency=config.concurrency,
            rate_limit_per_minute=config.rate_limit_per_minute,
            daily_limit=config.daily_limit,
            quota_timezone=config.quota_timezone,
            quota_group=config.quota_group,
        ),
        batch=config.batch,
        batch_backend=backend,
        probe=config.probe,
    )


def build_profiles(config: ExtractionConfig, settings: Settings) -> StaticExtractionProfiles:
    return StaticExtractionProfiles(
        profiles={name: build_profile(c, settings) for name, c in config.profiles.items()},
        default_profile=config.pool[0],
        pool_names=config.pool,
    )

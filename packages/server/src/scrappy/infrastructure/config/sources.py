"""``sources.yaml`` -> typed per-source config. Fetchers are built elsewhere (engines factory).

Source-level keys: ``enabled``, ``page_size``, ``health``. Every other key is an engine key and
is passed through to ``EngineConfig.from_mapping``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scrappy.domain.run import HealthThresholds, Phase
from scrappy.domain.shared import InvalidValueError, SourceId
from scrappy.infrastructure.config.errors import ConfigError, format_validation_error
from scrappy.infrastructure.config.yaml_io import read_yaml
from scrappy.infrastructure.scraping.engines.factory import EngineConfig, parse_rate_limit


class _HealthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_rejected_ratio: float = Field(default=0.05, ge=0, le=1)
    min_sample: int = Field(default=5, ge=0)
    min_fill_rates: dict[Phase, dict[str, float]] = Field(
        default_factory=dict[Phase, dict[str, float]]
    )


class _SourceModel(BaseModel):
    model_config = ConfigDict(extra="allow")  # extras are engine keys

    enabled: bool = True
    page_size: int | None = Field(default=None, ge=1)
    health: _HealthModel | None = None


class _FileModel(BaseModel):
    sources: dict[str, _SourceModel] = Field(default_factory=dict[str, _SourceModel])


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: SourceId
    enabled: bool
    engine: EngineConfig
    page_size: int | None = None
    health: HealthThresholds | None = None


@dataclass(frozen=True, slots=True)
class SourcesConfig:
    sources: Mapping[SourceId, SourceConfig] = field(default_factory=dict[SourceId, SourceConfig])

    @property
    def enabled(self) -> list[SourceConfig]:
        return [source for source in self.sources.values() if source.enabled]

    def get(self, source: SourceId) -> SourceConfig | None:
        return self.sources.get(source)


def parse_sources(data: object, *, path: Path) -> SourcesConfig:
    """Validate parsed YAML. Raises :class:`ConfigError` naming the file and key path."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} ({path}): top level must be a mapping with 'sources'")
    try:
        parsed = _FileModel.model_validate(data)
    except ValidationError as error:
        raise ConfigError(format_validation_error(path, error)) from error

    result: dict[SourceId, SourceConfig] = {}
    for name, model in parsed.sources.items():
        where = f"{path.name} ({path}): sources.{name}"
        try:
            source_id = SourceId(name)
            engine_keys: dict[str, Any] = dict(model.model_extra or {})
            if engine_keys.get("rate_limit") is not None:
                parse_rate_limit(str(engine_keys["rate_limit"]))
            engine = EngineConfig.from_mapping(engine_keys)
        except (InvalidValueError, ValueError, TypeError) as error:
            raise ConfigError(f"{where}: {error}") from error
        health = None
        if model.health is not None:
            try:
                health = HealthThresholds(
                    max_rejected_ratio=model.health.max_rejected_ratio,
                    min_fill_rates=model.health.min_fill_rates,
                    min_sample=model.health.min_sample,
                )
            except InvalidValueError as error:
                raise ConfigError(f"{where}.health: {error}") from error
        result[source_id] = SourceConfig(
            id=source_id,
            enabled=model.enabled,
            engine=engine,
            page_size=model.page_size,
            health=health,
        )
    return SourcesConfig(result)


def load_sources(path: Path) -> SourcesConfig:
    return parse_sources(read_yaml(path), path=path)

"""``scoring.yaml`` -> domain :class:`Strategy` objects (ADR 0011 sections 5 and 6).

Format::

    strategies:
      gaming:
        description: "GPU first"
        category: laptop
        filters: ["ram_gb>=8", "condition!=for_parts"]   # same syntax as `q --where`
        terms:
          gpu.blender: {weight: 0.6, baseline: 4500}    # <cpu|gpu>.<source>[.<metric>]
          ram_gb: {weight: 0.2, baseline: 16, cap: 32, transform: log}
          storage_type: {weight: 0.1, map: {ssd: 1, hdd: 0.3, emmc: 0.2}}
          ram_upgradeable: {weight: 0.1}                              # boolean: 1 / 0

``baseline`` is required except for boolean attributes and enum ``map`` terms (default 1).
The file is validated against the category catalog: unknown facts, enums without a full map,
text attributes and filters on unknown attributes are errors that name strategy and term.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scrappy.application.errors import InvalidRequestError
from scrappy.application.filter_syntax import parse_where
from scrappy.application.ports.system import CategoryProvider
from scrappy.application.use_cases.analytics.common import PSEUDO_FIELDS
from scrappy.application.use_cases.list_offers import typed_predicates
from scrappy.domain.category import AttributeType, Category, CategoryCatalog, CategoryName
from scrappy.domain.extraction import AttributePredicate
from scrappy.domain.scoring import Strategy, Term, Transform, parse_component_fact
from scrappy.domain.scoring import validate_against_category as validate_strategy
from scrappy.domain.shared import InvalidValueError
from scrappy.infrastructure.config.errors import ConfigError, format_validation_error
from scrappy.infrastructure.config.yaml_io import read_yaml


class _TermModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: float = Field(gt=0)
    baseline: float | None = Field(default=None, gt=0)
    cap: float | None = Field(default=None, gt=0)
    transform: Literal["linear", "log"] = "linear"
    map: dict[str, float] | None = None


class _StrategyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    category: str
    filters: list[str] = Field(default_factory=list[str])
    terms: dict[str, _TermModel] = Field(min_length=1)


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategies: dict[str, _StrategyModel]


def parse_scoring(data: object, *, catalog: CategoryCatalog, path: Path) -> dict[str, Strategy]:
    """Validate parsed YAML against ``catalog``. Raises :class:`ConfigError`."""
    if data is None:
        data = {"strategies": {}}
    try:
        parsed = _FileModel.model_validate(data)
    except ValidationError as error:
        raise ConfigError(format_validation_error(path, error)) from error
    strategies: dict[str, Strategy] = {}
    for name, model in parsed.strategies.items():
        try:
            strategies[name] = _build(name, model, catalog)
        except (InvalidValueError, InvalidRequestError) as error:
            raise ConfigError(f"{path.name} ({path}): {error}") from error
    return strategies


def _build(name: str, model: _StrategyModel, catalog: CategoryCatalog) -> Strategy:
    category_name = CategoryName(model.category)
    category = catalog.get(category_name)
    if category is None:
        known = ", ".join(str(c.name) for c in catalog)
        raise InvalidValueError(
            f"strategy {name!r}: unknown category {model.category!r} (known: {known})"
        )
    terms = tuple(_term(name, key, raw, category) for key, raw in model.terms.items())
    strategy = Strategy(
        name=name,
        category=category_name,
        terms=terms,
        description=model.description,
        filters=_filters(name, model.filters, category),
    )
    validate_strategy(strategy, category)
    return strategy


def _term(strategy: str, key: str, raw: _TermModel, category: Category) -> Term:
    fact = key
    ref = parse_component_fact(key)  # raises for unknown sources / metrics
    if ref is not None:
        fact = ref.key
    baseline = raw.baseline
    if baseline is None:
        spec = None if ref is not None else category.attribute(key)
        if raw.map is not None or (
            spec is not None and spec.type in (AttributeType.BOOLEAN, AttributeType.ENUM)
        ):
            baseline = 1.0
        else:
            raise InvalidValueError(
                f"strategy {strategy!r}, term {key!r}: baseline is required "
                "(what value counts as solid for this purpose)"
            )
    return Term(
        name=key,
        fact=fact,
        weight=raw.weight,
        baseline=baseline,
        cap=raw.cap,
        transform=Transform(raw.transform),
        value_map=None if raw.map is None else tuple(raw.map.items()),
    )


def _filters(strategy: str, texts: list[str], category: Category) -> tuple[AttributePredicate, ...]:
    predicates = [parse_where(text) for text in texts]
    attributes = tuple(p for p in predicates if p.attribute not in PSEUDO_FIELDS)
    try:
        typed_predicates(category, attributes)  # unknown attribute / bad value / bad operator
    except InvalidRequestError as error:
        raise InvalidValueError(f"strategy {strategy!r}, filters: {error}") from error
    return tuple(predicates)


def load_scoring(path: Path, catalog: CategoryCatalog) -> dict[str, Strategy]:
    return parse_scoring(read_yaml(path), catalog=catalog, path=path)


class YamlScoringProvider:
    """``ScoringProvider`` over a YAML file, validated against the live category catalog.
    Re-read on every call (cheap; edits apply without a restart)."""

    def __init__(self, path: Path, categories: CategoryProvider) -> None:
        self._path = path
        self._categories = categories

    async def strategies(self) -> Mapping[str, Strategy]:
        return load_scoring(self._path, await self._categories.catalog())

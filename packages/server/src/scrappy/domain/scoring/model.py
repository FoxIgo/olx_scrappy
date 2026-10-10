"""Scoring strategy model (ADR 0011 sections 5 and 6): interpretation, never facts.

A :class:`Strategy` says how much each fact matters *for one purpose*. It is configuration
(``config/scoring.yaml``); nothing here is ever stored with the facts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from scrappy.domain.category import AttributeType, Category, CategoryName
from scrappy.domain.component import ComponentKind
from scrappy.domain.extraction import AttributePredicate
from scrappy.domain.scoring.facts import ComponentFactRef, parse_component_fact
from scrappy.domain.shared import InvalidValueError


class Transform(StrEnum):
    LINEAR = "linear"
    LOG = "log"


@dataclass(frozen=True, slots=True)
class Term:
    """One weighted fact of a strategy.

    ``points = weight * transform(min(fact, cap) / baseline)``; ``baseline`` is "what counts
    as solid" for the purpose, so a fact equal to its baseline gives ``weight * 1`` with
    either transform.
    """

    name: str
    """The fact as written in the strategy file (shown in breakdowns)."""
    fact: str
    """Canonical fact: an attribute name or ``<kind>.<source>.<metric>``."""
    weight: float
    baseline: float
    cap: float | None = None
    transform: Transform = Transform.LINEAR
    value_map: tuple[tuple[str, float], ...] | None = None
    """Enum value -> number (the fact is then the mapped number)."""

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise InvalidValueError(f"term {self.name!r}: weight must be > 0")
        if not math.isfinite(self.baseline) or self.baseline <= 0:
            raise InvalidValueError(f"term {self.name!r}: baseline must be > 0")
        if self.cap is not None and (not math.isfinite(self.cap) or self.cap <= 0):
            raise InvalidValueError(f"term {self.name!r}: cap must be > 0")
        for key, number in self.value_map or ():
            if not math.isfinite(number) or number < 0:
                raise InvalidValueError(f"term {self.name!r}: map value for {key!r} must be >= 0")

    @property
    def component(self) -> ComponentFactRef | None:
        """The benchmark this term reads, ``None`` for a plain attribute."""
        return parse_component_fact(self.fact)


@dataclass(frozen=True, slots=True)
class Strategy:
    name: str
    category: CategoryName
    terms: tuple[Term, ...]
    description: str = ""
    filters: tuple[AttributePredicate, ...] = ()
    """Hard requirements (raw values, typed against the category when applied)."""

    def __post_init__(self) -> None:
        if not self.terms:
            raise InvalidValueError(f"strategy {self.name!r} needs at least one term")
        facts = [t.fact for t in self.terms]
        if len(set(facts)) != len(facts):
            raise InvalidValueError(f"strategy {self.name!r} lists the same fact twice")

    @property
    def total_weight(self) -> float:
        return sum(t.weight for t in self.terms)


def validate_against_category(strategy: Strategy, category: Category) -> None:
    """Every fact must exist and be numeric (or mapped); raises :class:`InvalidValueError`."""
    known = ", ".join(sorted(s.name for s in category.attributes))
    for term in strategy.terms:
        where = f"strategy {strategy.name!r}, term {term.name!r}"
        ref = term.component
        if ref is not None:
            if term.value_map is not None:
                raise InvalidValueError(f"{where}: 'map' only applies to enum attributes")
            if category.attribute(ref.kind.value) is None:
                raise InvalidValueError(
                    f"{where}: category {category.name} has no {ref.kind.value!r} attribute, "
                    "so the part can never be known"
                )
            continue
        spec = category.attribute(term.fact)
        if spec is None:
            raise InvalidValueError(
                f"{where}: unknown fact {term.fact!r} (attributes of {category.name}: {known}; "
                f"or {ComponentKind.CPU.value}.<source> / {ComponentKind.GPU.value}.<source>)"
            )
        if spec.type is AttributeType.ENUM:
            _check_map(where, spec.name, spec.values, term)
        elif term.value_map is not None:
            raise InvalidValueError(f"{where}: 'map' only applies to enum attributes")
        elif spec.type is AttributeType.STRING:
            raise InvalidValueError(f"{where}: {spec.name!r} is text, not a number")
        elif spec.type is AttributeType.ENUM_LIST:
            raise InvalidValueError(
                f"{where}: {spec.name!r} is a list; use it in a filter (!~ / ~), not a term"
            )


def _check_map(where: str, attribute: str, values: tuple[str, ...], term: Term) -> None:
    if term.value_map is None:
        raise InvalidValueError(
            f"{where}: {attribute!r} is an enum; give 'map' for {', '.join(values)}"
        )
    mapped = {key for key, _ in term.value_map}
    unknown = sorted(mapped - set(values))
    missing = [v for v in values if v not in mapped]
    if unknown:
        raise InvalidValueError(f"{where}: map has values {unknown} that {attribute!r} lacks")
    if missing:
        raise InvalidValueError(f"{where}: map is missing {missing} of {attribute!r}")

"""Pure scoring maths (ADR 0011 section 5).

For every term of a strategy:

* the fact is *present* or *missing*; missing facts (null attribute, unresolved or
  unbenchmarked part, vague text like "Intel Core i5") are never estimated;
* ``x = fact`` (booleans 1/0, enums through the term's map), clamped to ``0 <= x <= cap``;
* ``t = x / baseline`` (linear) or ``log2(1 + x / baseline)`` (log: diminishing returns,
  still exactly 1 at the baseline);
* ``points = weight * t``.

``performance`` = sum of the points of present terms. It is NOT renormalised by the covered
weight: a missing term contributes 0, so missing information is never rewarded.
``coverage`` = weight of present terms / weight of all terms.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from scrappy.domain.scoring.model import Strategy, Term, Transform

type FactValue = str | int | float | Decimal | bool | None


@dataclass(frozen=True, slots=True)
class TermScore:
    term: Term
    value: float | None
    """The numeric fact after bool / map conversion (before cap); ``None`` = missing."""
    points: float | None

    @property
    def present(self) -> bool:
        return self.points is not None


@dataclass(frozen=True, slots=True)
class OfferScore:
    performance: float
    coverage: float
    terms: tuple[TermScore, ...]


def numeric_fact(term: Term, raw: FactValue) -> float | None:
    """The number a term works with, or ``None`` when the fact is missing / unusable."""
    if raw is None:
        return None
    if term.value_map is not None:
        return dict(term.value_map).get(str(raw))
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, int | float | Decimal):
        number = float(raw)
        return number if math.isfinite(number) else None
    return None


def term_points(term: Term, value: float) -> float:
    x = max(0.0, value)
    if term.cap is not None:
        x = min(x, term.cap)
    ratio = x / term.baseline
    scaled = math.log2(1.0 + ratio) if term.transform is Transform.LOG else ratio
    return term.weight * scaled


def score_term(term: Term, raw: FactValue) -> TermScore:
    value = numeric_fact(term, raw)
    return TermScore(term, value, None if value is None else term_points(term, value))


def score_offer(strategy: Strategy, facts: Mapping[str, FactValue]) -> OfferScore:
    """``facts`` is keyed by canonical fact name (attributes and ``gpu.<source>.<metric>``)."""
    scored = tuple(score_term(t, facts.get(t.fact)) for t in strategy.terms)
    present = sum(s.term.weight for s in scored if s.present)
    performance = sum(s.points for s in scored if s.points is not None)
    return OfferScore(performance, present / strategy.total_weight, scored)

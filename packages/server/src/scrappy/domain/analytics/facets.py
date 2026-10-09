"""Facet counting: which values does an attribute take, how often."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from scrappy.domain.category import AttributeValue

DEFAULT_BUCKETS = 5


@dataclass(frozen=True, slots=True)
class Bucket:
    low: Decimal
    high: Decimal
    """Inclusive for the last bucket, exclusive otherwise."""
    count: int


@dataclass(frozen=True, slots=True)
class NumericRange:
    minimum: Decimal
    maximum: Decimal
    buckets: tuple[Bucket, ...]


@dataclass(frozen=True, slots=True)
class FacetCounts:
    total: int
    null_count: int
    values: tuple[tuple[AttributeValue, int], ...]
    """Most frequent first; ties by value."""
    numeric: NumericRange | None


def _is_number(value: AttributeValue) -> bool:
    return isinstance(value, int | Decimal) and not isinstance(value, bool)


def count_facet(
    values: Sequence[AttributeValue | None], *, buckets: int = DEFAULT_BUCKETS
) -> FacetCounts:
    counts: dict[AttributeValue, int] = {}
    nulls = 0
    for value in values:
        if value is None:
            nulls += 1
        else:
            counts[value] = counts.get(value, 0) + 1
    ordered = tuple(sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))))
    numbers = [Decimal(v) for v in counts if _is_number(v)]
    numeric = None
    if numbers and len(numbers) == len(counts):
        numeric = _numeric_range(values, numbers, buckets)
    return FacetCounts(len(values), nulls, ordered, numeric)


def _numeric_range(
    values: Sequence[AttributeValue | None], numbers: list[Decimal], buckets: int
) -> NumericRange:
    low, high = min(numbers), max(numbers)
    present = [Decimal(v) for v in values if v is not None and _is_number(v)]
    if low == high or buckets < 2:
        return NumericRange(low, high, (Bucket(low, high, len(present)),))
    width = (high - low) / buckets
    edges = [low + width * i for i in range(buckets)] + [high]
    tallies = [0] * buckets
    for number in present:
        index = min(int((number - low) / width), buckets - 1)
        tallies[index] += 1
    return NumericRange(
        low, high, tuple(Bucket(edges[i], edges[i + 1], tallies[i]) for i in range(buckets))
    )

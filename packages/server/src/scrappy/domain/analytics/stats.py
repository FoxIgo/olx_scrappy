"""Summary statistics over Decimals (prices)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from scrappy.domain.shared import InvalidValueError

CENT = Decimal("0.01")


def percentile(sorted_values: Sequence[Decimal], fraction: Decimal) -> Decimal:
    """Percentile with linear interpolation between closest ranks (the "R-7" method used by
    numpy/Excel): position ``(n - 1) * fraction`` in the sorted values; a fractional position
    interpolates between its two neighbours. ``fraction`` is in ``[0, 1]``; the input must be
    sorted ascending and non-empty. The result is exact (not rounded)."""
    if not sorted_values:
        raise InvalidValueError("percentile of an empty sequence")
    if not Decimal(0) <= fraction <= Decimal(1):
        raise InvalidValueError("percentile fraction must be within [0, 1]")
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)  # floor, position >= 0
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    low, high = sorted_values[lower], sorted_values[upper]
    return low + (high - low) * weight


def median(values: Iterable[Decimal]) -> Decimal:
    return percentile(sorted(values), Decimal("0.5"))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class Summary:
    """``n``, extremes (exact) and p25/median/p75/mean rounded to 2 decimals."""

    n: int
    minimum: Decimal
    p25: Decimal
    median: Decimal
    p75: Decimal
    maximum: Decimal
    mean: Decimal


def summarize(values: Iterable[Decimal]) -> Summary | None:
    """Summary of the values, ``None`` when there are none."""
    ordered = sorted(values)
    if not ordered:
        return None
    return Summary(
        n=len(ordered),
        minimum=ordered[0],
        p25=_cents(percentile(ordered, Decimal("0.25"))),
        median=_cents(percentile(ordered, Decimal("0.5"))),
        p75=_cents(percentile(ordered, Decimal("0.75"))),
        maximum=ordered[-1],
        mean=_cents(sum(ordered, Decimal(0)) / len(ordered)),
    )

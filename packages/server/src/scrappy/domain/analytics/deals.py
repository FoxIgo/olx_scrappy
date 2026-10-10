"""Deal detection: offers priced well below the median of comparable offers.

Comparable = same values of the chosen attributes (strings case-insensitive, numbers by
value) and same currency. Offers lacking one of the attributes cannot be compared: they are
excluded and counted. Groups smaller than ``min_group`` produce no deals (a median of two
offers says nothing).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from scrappy.domain.analytics.stats import median
from scrappy.domain.category import AttributeValue
from scrappy.domain.shared import InvalidValueError

DEFAULT_MIN_GROUP = 5
DEFAULT_MAX_RATIO = Decimal("0.8")

type GroupValue = str | bool | Decimal
type GroupKey = tuple[tuple[str, GroupValue], ...]


@dataclass(frozen=True, slots=True)
class DealCandidate:
    offer_id: str
    price: Decimal
    currency: str
    attributes: Mapping[str, AttributeValue | None]
    """Values the group key is read from."""


@dataclass(frozen=True, slots=True)
class Deal:
    candidate: DealCandidate
    group: GroupKey
    group_size: int
    group_median: Decimal
    ratio: Decimal
    reason: str


@dataclass(frozen=True, slots=True)
class DealReport:
    deals: tuple[Deal, ...]
    """Cheapest ratio first."""
    compared: int
    """Offers that landed in a group large enough to be judged."""
    excluded_missing: int
    """Offers lacking a group attribute."""
    small_groups: int
    small_group_offers: int
    mixed_currency_keys: tuple[GroupKey, ...]
    """Group keys that occur in several currencies (split per currency)."""


def group_value(value: AttributeValue) -> GroupValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, tuple):
        return ", ".join(sorted(item.casefold() for item in value))
    return Decimal(value)


def group_key(
    attributes: Mapping[str, AttributeValue | None], names: Sequence[str]
) -> GroupKey | None:
    """The comparable-group key, or ``None`` when any named attribute is missing."""
    parts: list[tuple[str, GroupValue]] = []
    for name in names:
        value = attributes.get(name)
        if value is None:
            return None
        parts.append((name, group_value(value)))
    return tuple(parts)


def describe_key(key: GroupKey) -> str:
    return ", ".join(f"{name}={format(v, 'f') if isinstance(v, Decimal) else v}" for name, v in key)


def find_deals(
    candidates: Sequence[DealCandidate],
    group_by: Sequence[str],
    *,
    min_group: int = DEFAULT_MIN_GROUP,
    max_ratio: Decimal = DEFAULT_MAX_RATIO,
) -> DealReport:
    if min_group < 2:
        raise InvalidValueError("min_group must be >= 2")
    if not Decimal(0) < max_ratio <= Decimal(1):
        raise InvalidValueError("max_ratio must be within (0, 1]")

    groups: dict[tuple[GroupKey, str], list[DealCandidate]] = {}
    missing = 0
    for candidate in candidates:
        key = group_key(candidate.attributes, group_by)
        if key is None:
            missing += 1
            continue
        groups.setdefault((key, candidate.currency), []).append(candidate)

    currencies: dict[GroupKey, set[str]] = {}
    for key, currency in groups:
        currencies.setdefault(key, set()).add(currency)
    mixed = tuple(key for key, found in currencies.items() if len(found) > 1)

    deals: list[Deal] = []
    compared = small_groups = small_offers = 0
    for (key, currency), members in groups.items():
        if len(members) < min_group:
            small_groups += 1
            small_offers += len(members)
            continue
        compared += len(members)
        mid = median(m.price for m in members)
        if mid <= 0:
            continue
        for member in members:
            ratio = member.price / mid
            if ratio > max_ratio:
                continue
            reason = (
                f"{member.price} {currency} is {ratio:.0%} of the median {mid:.2f} {currency} "
                f"of {len(members)} comparable offers ({describe_key(key) or 'all offers'})"
            )
            deals.append(Deal(member, key, len(members), mid, ratio, reason))
    deals.sort(key=lambda d: (d.ratio, d.candidate.offer_id))
    return DealReport(tuple(deals), compared, missing, small_groups, small_offers, mixed)

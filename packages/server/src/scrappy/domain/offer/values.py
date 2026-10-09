"""Value objects describing an offer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from scrappy.domain.shared import InvalidValueError, Money, SourceId


@dataclass(frozen=True, slots=True)
class OfferId:
    """Global offer identity and dedup key: ``(source, external_id)`` (R4)."""

    source: SourceId
    external_id: str

    def __post_init__(self) -> None:
        if not self.external_id or self.external_id != self.external_id.strip():
            raise InvalidValueError("OfferId.external_id must be non-empty and trimmed")

    def __str__(self) -> str:
        return f"{self.source.value}:{self.external_id}"

    @classmethod
    def parse(cls, value: str) -> OfferId:
        """Inverse of ``str(offer_id)``: ``"olx_pl:123"`` -> ``OfferId(olx_pl, "123")``."""
        source, sep, external_id = value.partition(":")
        if not sep:
            raise InvalidValueError(f"invalid offer id {value!r}: expected 'source:external_id'")
        return cls(SourceId(source), external_id)


class OfferStatus(StrEnum):
    """Offer lifecycle as read from the offer page (R9). ``UNKNOWN`` means "not observed yet"."""

    ACTIVE = "active"
    REMOVED = "removed"
    SOLD = "sold"
    UNKNOWN = "unknown"


class PriceKind(StrEnum):
    FIXED = "fixed"
    """A money amount (possibly negotiable)."""
    EXCHANGE = "exchange"
    """A swap is offered instead of money (OLX "Zamienię"); there is no amount."""
    FREE = "free"
    """Given away (OLX "Za darmo"); there is no amount."""


@dataclass(frozen=True, slots=True)
class Price:
    """Asking price. Only ``FIXED`` carries an amount; ``0`` is never used as a marker."""

    kind: PriceKind
    amount: Money | None = None
    negotiable: bool = False

    def __post_init__(self) -> None:
        if self.kind is PriceKind.FIXED and self.amount is None:
            raise InvalidValueError("a FIXED price needs an amount")
        if self.kind is not PriceKind.FIXED and self.amount is not None:
            raise InvalidValueError(f"a {self.kind.value} price has no amount")
        if self.kind is not PriceKind.FIXED and self.negotiable:
            raise InvalidValueError("only FIXED prices can be negotiable")

    @classmethod
    def fixed(
        cls, amount: str | int | Money, currency: str = "PLN", *, negotiable: bool = False
    ) -> Price:
        money = amount if isinstance(amount, Money) else Money.of(amount, currency)
        return cls(PriceKind.FIXED, money, negotiable)

    @classmethod
    def exchange(cls) -> Price:
        return cls(PriceKind.EXCHANGE)

    @classmethod
    def free(cls) -> Price:
        return cls(PriceKind.FREE)

    def __str__(self) -> str:
        if self.amount is None:
            return self.kind.value
        return f"{self.amount}{' (negotiable)' if self.negotiable else ''}"


@dataclass(frozen=True, slots=True)
class Params:
    """Site parameters as key/value text pairs, sorted by key so equality is stable."""

    items: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        keys = [key for key, _ in self.items]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise InvalidValueError("Params.items must be sorted by unique key; use Params.of()")

    @classmethod
    def of(cls, values: Mapping[str, str]) -> Params:
        return cls(tuple(sorted(values.items())))

    def as_dict(self) -> dict[str, str]:
        return dict(self.items)

    def get(self, key: str) -> str | None:
        return dict(self.items).get(key)

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class SellerRef:
    """Reference to the seller as published on the site (never contact data)."""

    external_id: str | None = None
    name: str | None = None
    is_business: bool | None = None


@dataclass(frozen=True, slots=True)
class ContentHash:
    """Fingerprint of the content the LLM extracts from (R11): lowercase hex SHA-256."""

    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 64 or any(c not in "0123456789abcdef" for c in self.value):
            raise InvalidValueError("ContentHash must be a lowercase hex SHA-256 digest")

    def __str__(self) -> str:
        return self.value


def compute_content_hash(title: str | None, description: str, params: Params | None) -> ContentHash:
    """Deterministic hash over title + description + params.

    Canonical JSON (params sorted, compact separators, UTF-8) keeps the value stable across
    processes, Python versions and param insertion order. ``None`` params hash like empty
    params, ``None`` title like an empty title.
    """
    canonical = json.dumps(
        {
            "title": title or "",
            "description": description,
            "params": [list(item) for item in (params.items if params else ())],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ContentHash(hashlib.sha256(canonical.encode("utf-8")).hexdigest())

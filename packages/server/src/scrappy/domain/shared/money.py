"""Money value object. Amounts are always :class:`~decimal.Decimal`, never float."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from scrappy.domain.shared.errors import InvalidValueError

_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise InvalidValueError("Money.amount must be a Decimal (never float)")
        if not self.amount.is_finite():
            raise InvalidValueError("Money.amount must be finite")
        if self.amount < 0:
            raise InvalidValueError("Money.amount must not be negative")
        if not _CURRENCY.fullmatch(self.currency):
            raise InvalidValueError(f"invalid ISO 4217 currency code {self.currency!r}")

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> Money:
        """Build from a string/int/Decimal. Floats are rejected on purpose."""
        return cls(Decimal(amount), currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

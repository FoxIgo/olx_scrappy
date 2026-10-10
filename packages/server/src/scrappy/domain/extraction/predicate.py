"""Typed attribute filters (``ram_gb >= 16``) with reference semantics.

Query adapters translate predicates to SQL/JSON1 etc.; :meth:`AttributePredicate.matches` is
the specification they must agree with (the in-memory fake uses it directly).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from scrappy.domain.category import AttributeValue


class Comparison(StrEnum):
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    CONTAINS = "~"
    """Case-insensitive substring match on text; element membership on ``enum_list``."""
    NOT_CONTAINS = "!~"
    """Negation of ``~`` (a present value only: null never matches)."""


@dataclass(frozen=True, slots=True)
class AttributePredicate:
    attribute: str
    op: Comparison
    value: AttributeValue

    def matches(self, attributes: Mapping[str, AttributeValue | None]) -> bool:
        """Evaluate against one offer's attributes.

        Rules: a missing/null attribute never matches (not even ``!=``); strings compare
        case-insensitively; numbers (int/Decimal) compare numerically; ordering operators on
        strings or booleans, and mixed types, do not match. Lists (``enum_list``) support only
        ``~`` (has the element) and ``!~`` (lacks it).
        """
        actual = attributes.get(self.attribute)
        if actual is None:
            return False
        expected = self.value
        if isinstance(actual, tuple):
            return _matches_list(self.op, actual, expected)
        if isinstance(expected, tuple):
            return False
        if isinstance(actual, bool) or isinstance(expected, bool):
            if not (isinstance(actual, bool) and isinstance(expected, bool)):
                return False
            return _compare_equality(self.op, actual == expected)
        if isinstance(actual, str) or isinstance(expected, str):
            if not (isinstance(actual, str) and isinstance(expected, str)):
                return False
            left, right = actual.casefold(), expected.casefold()
            if self.op is Comparison.CONTAINS:
                return right in left
            if self.op is Comparison.NOT_CONTAINS:
                return right not in left
            return _compare_equality(self.op, left == right)
        return _compare_numbers(self.op, Decimal(actual), Decimal(expected))


def _matches_list(op: Comparison, actual: tuple[str, ...], expected: AttributeValue) -> bool:
    if not isinstance(expected, str) or op not in (Comparison.CONTAINS, Comparison.NOT_CONTAINS):
        return False
    present = expected.casefold() in {item.casefold() for item in actual}
    return present if op is Comparison.CONTAINS else not present


def _compare_equality(op: Comparison, equal: bool) -> bool:
    if op is Comparison.EQ:
        return equal
    if op is Comparison.NE:
        return not equal
    return False


def _compare_numbers(op: Comparison, left: Decimal, right: Decimal) -> bool:
    match op:
        case Comparison.EQ:
            return left == right
        case Comparison.NE:
            return left != right
        case Comparison.LT:
            return left < right
        case Comparison.LE:
            return left <= right
        case Comparison.GT:
            return left > right
        case Comparison.GE:
            return left >= right
        case Comparison.CONTAINS | Comparison.NOT_CONTAINS:
            return False

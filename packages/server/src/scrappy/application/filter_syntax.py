"""``--where "ram_gb>=16"`` (and a strategy's ``filters``) -> domain :class:`AttributePredicate`."""

from __future__ import annotations

import re
from collections.abc import Iterable

from scrappy.application.errors import InvalidRequestError
from scrappy.domain.extraction import AttributePredicate, Comparison

# Longest operators first so ">=" is not read as ">" followed by "=16".
_OPERATORS: tuple[tuple[str, Comparison], ...] = (
    ("<=", Comparison.LE),
    (">=", Comparison.GE),
    ("!=", Comparison.NE),
    ("==", Comparison.EQ),
    ("<", Comparison.LT),
    (">", Comparison.GT),
    ("=", Comparison.EQ),
    ("!~", Comparison.NOT_CONTAINS),
    ("~", Comparison.CONTAINS),
)
_PATTERN = re.compile(
    r"^\s*(?P<attr>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op><=|>=|!=|!~|==|<|>|=|~)\s*(?P<value>.*?)\s*$"
)
_OPS: dict[str, Comparison] = dict(_OPERATORS)


def parse_where(text: str) -> AttributePredicate:
    """Parse one filter. The value stays a string: ``ListOffers`` coerces it to the
    attribute's type (``"16"`` -> 16) and rejects unknown attributes or bad operators."""
    match = _PATTERN.match(text)
    if match is None or not match["value"]:
        raise InvalidRequestError(
            f"cannot parse filter {text!r}: expected ATTRIBUTE OP VALUE with OP one of "
            "= != < <= > >= ~ !~ (e.g. ram_gb>=16, gpu~gtx, damage!~motherboard)"
        )
    value = match["value"]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return AttributePredicate(match["attr"], _OPS[match["op"]], value)


def parse_wheres(texts: Iterable[str]) -> tuple[AttributePredicate, ...]:
    return tuple(parse_where(text) for text in texts)

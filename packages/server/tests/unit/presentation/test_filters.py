from __future__ import annotations

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.presentation.cli.filters import parse_where, parse_wheres


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ram_gb>=16", AttributePredicate("ram_gb", Comparison.GE, "16")),
        ("ram_gb<=16", AttributePredicate("ram_gb", Comparison.LE, "16")),
        ("ram_gb>16", AttributePredicate("ram_gb", Comparison.GT, "16")),
        ("ram_gb<16", AttributePredicate("ram_gb", Comparison.LT, "16")),
        ("ram_gb=16", AttributePredicate("ram_gb", Comparison.EQ, "16")),
        ("ram_gb==16", AttributePredicate("ram_gb", Comparison.EQ, "16")),
        ("storage_type!=hdd", AttributePredicate("storage_type", Comparison.NE, "hdd")),
        ("gpu~gtx", AttributePredicate("gpu", Comparison.CONTAINS, "gtx")),
        ("  screen_in >= 15.6 ", AttributePredicate("screen_in", Comparison.GE, "15.6")),
        ('gpu~"GTX 1650"', AttributePredicate("gpu", Comparison.CONTAINS, "GTX 1650")),
        ("gpu~'rtx'", AttributePredicate("gpu", Comparison.CONTAINS, "rtx")),
        ("gpu=a=b", AttributePredicate("gpu", Comparison.EQ, "a=b")),
    ],
)
def test_parse_where(text: str, expected: AttributePredicate) -> None:
    assert parse_where(text) == expected


@pytest.mark.parametrize("text", ["", "ram_gb", "ram_gb>=", ">=16", "16>=ram_gb", "ram gb>=16"])
def test_parse_where_rejects_malformed_filters(text: str) -> None:
    with pytest.raises(InvalidRequestError, match="cannot parse filter"):
        parse_where(text)


def test_parse_wheres_keeps_order() -> None:
    parsed = parse_wheres(["ram_gb>=16", "gpu~gtx"])
    assert [p.attribute for p in parsed] == ["ram_gb", "gpu"]

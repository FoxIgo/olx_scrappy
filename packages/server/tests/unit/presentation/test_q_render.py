from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from scrappy.application.use_cases.analytics import Answer
from scrappy.domain.offer import OfferStatus
from scrappy.presentation.cli.q_render import (
    dumps,
    error_envelope,
    ok_envelope,
    table_csv,
    table_jsonl,
    to_jsonable,
)


def test_values_serialise_losslessly() -> None:
    assert to_jsonable(Decimal("1E+3")) == "1000"
    assert to_jsonable(Decimal("0.10")) == "0.10"
    assert to_jsonable(datetime(2026, 10, 1, 12, 0, tzinfo=UTC)) == "2026-10-01T12:00:00Z"
    plus_two = datetime(2026, 10, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_jsonable(plus_two) == "2026-10-01T12:00:00Z"
    assert to_jsonable(OfferStatus.ACTIVE) == "active"
    assert to_jsonable({"a": (Decimal(1), None, True)}) == {"a": ["1", None, True]}
    assert to_jsonable(frozenset({"b", "a"})) == ["a", "b"]


def test_dumps_keeps_polish_text_and_is_compact() -> None:
    text = dumps({"title": "zażółć gęślą jaźń"}, pretty=False)
    assert "zażółć" in text
    assert "\n" not in text
    assert ": " not in text


def test_envelopes() -> None:
    ok = ok_envelope("q.x", {"a": 1}, Answer([1, 2], notes=["n"]))
    assert ok == {
        "ok": True,
        "command": "q.x",
        "params": {"a": 1},
        "count": 2,
        "truncated": False,
        "data": [1, 2],
        "notes": ["n"],
    }
    err = error_envelope("q.x", {}, ValueError("boom"))
    assert err["ok"] is False
    assert err["error"] == {"type": "ValueError", "message": "boom"}


def test_csv_and_jsonl_tables() -> None:
    columns = ["id", "title", "price", "flag", "when"]
    rows = [
        ["1", 'zażółć, "q"', Decimal("10.50"), True, datetime(2026, 1, 1, tzinfo=UTC)],
        ["2", None, None, False, None],
    ]
    parsed = list(csv.reader(io.StringIO(table_csv(columns, rows), newline="")))
    assert parsed[0] == columns
    assert parsed[1] == ["1", 'zażółć, "q"', "10.50", "true", "2026-01-01T00:00:00Z"]
    assert parsed[2] == ["2", "", "", "false", ""]
    lines = [json.loads(line) for line in table_jsonl(columns, rows).splitlines()]
    assert lines[0]["price"] == "10.50"
    assert lines[1]["title"] is None
    assert lines[1]["flag"] is False

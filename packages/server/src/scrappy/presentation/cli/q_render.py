"""JSON rendering for ``scrappy q``: the envelope and value serialisation (no tables)."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from scrappy.application.use_cases.analytics import Answer

type Jsonable = Any


def to_jsonable(value: object) -> Jsonable:
    """Decimals -> plain strings (no exponent), datetimes -> ISO-8601 UTC with ``Z``, enums ->
    values, ids -> ``str``; containers recursively. Never loses precision."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, set | frozenset):
        return sorted((to_jsonable(v) for v in value), key=str)  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [to_jsonable(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def dumps(document: Mapping[str, object], *, pretty: bool) -> str:
    return json.dumps(
        to_jsonable(document),
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )


def ok_envelope(command: str, params: Mapping[str, object], answer: Answer) -> dict[str, object]:
    count = answer.count
    if count is None:
        count = len(answer.data) if isinstance(answer.data, list | tuple) else 1  # pyright: ignore[reportUnknownArgumentType]
    return {
        "ok": True,
        "command": command,
        "params": dict(params),
        "count": count,
        "truncated": answer.truncated,
        "data": answer.data,
        "notes": answer.notes,
    }


def error_envelope(
    command: str, params: Mapping[str, object], error: BaseException
) -> dict[str, object]:
    return {
        "ok": False,
        "command": command,
        "params": dict(params),
        "error": {"type": type(error).__name__, "message": str(error)},
    }


# ----------------------------------------------------------------------------- export


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    jsonable = to_jsonable(value)
    return str(jsonable)


def table_csv(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """CSV text with a header; ``\\n`` line ends; null = empty cell; booleans true/false."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(v) for v in row])
    return buffer.getvalue()


def table_jsonl(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """One JSON object per line (keys = columns, nulls kept, Decimals as strings)."""
    lines = (
        json.dumps(to_jsonable(dict(zip(columns, row, strict=True))), ensure_ascii=False)
        for row in rows
    )
    return "".join(line + "\n" for line in lines)

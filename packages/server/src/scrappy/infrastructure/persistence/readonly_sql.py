"""Raw SQL for ``q sql``: validation plus a genuinely read-only execution path.

Defence in depth, in this order:

1. :func:`validate_read_only_sql` accepts exactly one ``SELECT``/``WITH`` statement (comments
   stripped, string literals and quoted identifiers ignored, no ``;`` followed by more SQL,
   no write/DDL/PRAGMA/ATTACH keywords).
2. The statement runs on a **separate** connection that cannot write: SQLite opens the file
   with ``mode=ro`` and ``PRAGMA query_only=ON``; PostgreSQL uses a ``READ ONLY`` transaction.
   So even a validator bypass cannot modify data (see the tests, which skip step 1).
3. Row limit (``fetchmany``) and wall-clock timeout (SQLite progress handler, PostgreSQL
   ``statement_timeout``).
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import SqlResult

FORBIDDEN_KEYWORDS = frozenset(
    {
        "PRAGMA",
        "ATTACH",
        "DETACH",
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "DROP",
        "ALTER",
        "REPLACE",
        "VACUUM",
        "REINDEX",
        "ANALYZE",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "COPY",
        "CALL",
        "DO",
    }
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _strip(sql: str) -> tuple[str, str]:
    """``(tokens, runnable)``: ``sql`` without comments, once with every string literal /
    quoted identifier replaced by a placeholder (so only real SQL tokens remain) and once
    with them kept. Raises on an unterminated literal/comment."""
    out: list[str] = []
    keep: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
            keep.append(" ")
        elif ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                raise InvalidRequestError("unterminated /* comment")
            i = end + 2
            out.append(" ")
            keep.append(" ")
        elif ch in "'\"`":
            end = i + 1
            while True:
                end = sql.find(ch, end)
                if end < 0:
                    raise InvalidRequestError("unterminated quoted string or identifier")
                if sql.startswith(ch * 2, end):  # doubled quote = escaped quote
                    end += 2
                    continue
                break
            keep.append(sql[i : end + 1])
            i = end + 1
            out.append(" '' ")
        elif ch == "[":
            end = sql.find("]", i)
            if end < 0:
                raise InvalidRequestError("unterminated [identifier]")
            keep.append(sql[i : end + 1])
            i = end + 1
            out.append(" '' ")
        else:
            out.append(ch)
            keep.append(ch)
            i += 1
    return "".join(out), "".join(keep)


def validate_read_only_sql(sql: str) -> str:
    """Return the statement to execute (without a trailing ``;``) or raise
    :class:`InvalidRequestError`."""
    cleaned, runnable = _strip(sql)
    cleaned = cleaned.strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if not cleaned:
        raise InvalidRequestError("empty SQL statement")
    if ";" in cleaned:
        raise InvalidRequestError("only a single SQL statement is allowed")
    words = _WORD.findall(cleaned)
    if not words or words[0].upper() not in ("SELECT", "WITH"):
        raise InvalidRequestError("only SELECT / WITH ... SELECT statements are allowed")
    for match in _WORD.finditer(cleaned):
        word = match.group().upper()
        if word not in FORBIDDEN_KEYWORDS:
            continue
        if word == "REPLACE" and cleaned[match.end() :].lstrip().startswith("("):
            continue  # the string function replace(x, y, z)
        raise InvalidRequestError(f"{word} is not allowed: `q sql` is read-only")
    runnable = runnable.strip()
    while runnable.endswith(";"):
        runnable = runnable[:-1].rstrip()
    return runnable


def run_sqlite_read_only(
    path: str | Path, sql: str, *, max_rows: int, timeout_seconds: float
) -> SqlResult:
    """Execute ``sql`` as-is (NO validation here) on a read-only connection to ``path``."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    deadline = time.monotonic() + timeout_seconds
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
    except sqlite3.Error as error:
        raise InvalidRequestError(f"cannot open the database read-only: {error}") from error
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            cursor = conn.execute(sql)
            columns = tuple(d[0] for d in cursor.description or ())
            fetched = cursor.fetchmany(max_rows + 1)
        except sqlite3.Error as error:
            if "interrupted" in str(error):
                raise InvalidRequestError(f"query timed out after {timeout_seconds:g}s") from error
            raise InvalidRequestError(f"SQL error: {error}") from error
    finally:
        conn.close()
    return SqlResult(columns, [tuple(r) for r in fetched[:max_rows]], len(fetched) > max_rows)

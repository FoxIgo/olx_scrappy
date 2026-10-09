"""``q sql``: the read-only raw SQL fallback."""

from __future__ import annotations

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import AnalyticsQueries
from scrappy.application.use_cases.analytics.common import Answer, Json

DEFAULT_SQL_LIMIT = 200
DEFAULT_SQL_TIMEOUT_SECONDS = 10.0


class RunSql:
    """Delegates to the adapter, which owns the safety (single read-only statement, row limit,
    timeout, read-only connection)."""

    def __init__(
        self, *, queries: AnalyticsQueries, timeout_seconds: float = DEFAULT_SQL_TIMEOUT_SECONDS
    ):
        self._queries = queries
        self._timeout = timeout_seconds

    async def __call__(self, sql: str, *, limit: int = DEFAULT_SQL_LIMIT) -> Answer:
        if limit < 1:
            raise InvalidRequestError("limit must be >= 1")
        result = await self._queries.execute_sql(sql, max_rows=limit, timeout_seconds=self._timeout)
        data: Json = {"columns": list(result.columns), "rows": [list(r) for r in result.rows]}
        notes = [f"dialect: {self._queries.dialect}; read-only connection"]
        if result.truncated:
            notes.append(f"result cut at {limit} rows; add LIMIT/WHERE or raise --limit")
        return Answer(data, len(result.rows), result.truncated, notes)

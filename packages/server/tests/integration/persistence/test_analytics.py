"""``SqlAnalyticsQueries`` against SQLite: parity with the in-memory reference, latest-extraction
semantics, JSON null counting, schema reflection and the read-only raw SQL path."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import OfferRow, OfferScope
from scrappy.domain.category import CategoryName
from scrappy.domain.offer import (
    FieldChange,
    OfferSnapshot,
    OfferStatus,
    Price,
    PriceKind,
    TrackedField,
)
from scrappy.domain.run import RunStatus, ScrapeRun
from scrappy.domain.search import SavedSearch
from scrappy.domain.shared import RunId, SourceId
from scrappy.infrastructure.persistence.analytics import SqlAnalyticsQueries
from scrappy.infrastructure.persistence.readonly_sql import validate_read_only_sql
from tests.integration.persistence.sqlstore import SqlStore
from tests.integration.persistence.test_queries import S1, S2, populate
from tests.integration.persistence.test_repositories import full_offer
from tests.unit.builders import LAPTOP, T0, at, oid
from tests.unit.fakes import InMemoryAnalyticsQueries, InMemoryStore

SCOPES: dict[str, OfferScope] = {
    "all": OfferScope(),
    "search": OfferScope(search=S1),
    "other-search": OfferScope(search=S2),
    "relevant-search": OfferScope(search=S1, relevant_only=True),
    "relevant-any": OfferScope(relevant_only=True),
    "active": OfferScope(statuses=frozenset({OfferStatus.ACTIVE})),
    "sold-removed": OfferScope(statuses=frozenset({OfferStatus.SOLD, OfferStatus.REMOVED})),
    "category": OfferScope(category=CategoryName("laptop")),
    "category+search+active": OfferScope(
        search=S1,
        category=CategoryName("laptop"),
        relevant_only=True,
        statuses=frozenset({OfferStatus.ACTIVE}),
    ),
}


def summary(rows: list[OfferRow]) -> list[tuple[object, ...]]:
    return sorted(
        (
            str(r.offer_id),
            r.status,
            r.price_kind,
            r.price_amount,
            r.price_currency,
            r.category,
            dict(r.attributes),
            r.extracted_at,
            sorted((str(link.search), link.is_relevant, link.last_seen_at) for link in r.links),
        )
        for r in rows
    )


@pytest.fixture
async def both(store: SqlStore) -> tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries]:
    memory = InMemoryStore()
    await populate(memory.uow)
    await populate(store.uow)
    return InMemoryAnalyticsQueries(memory), SqlAnalyticsQueries(store.engine)


@pytest.mark.parametrize("name", list(SCOPES))
async def test_offer_rows_match_the_in_memory_reference(
    both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries], name: str
) -> None:
    reference, sql = both
    expected = await reference.offer_rows(SCOPES[name])
    actual = await sql.offer_rows(SCOPES[name])
    assert summary(actual) == summary(expected)
    assert await sql.count_offers(SCOPES[name]) == len(expected)


async def test_only_the_latest_extraction_counts_and_relevance_override_wins(
    both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries],
) -> None:
    _, sql = both
    rows = {str(r.offer_id): r for r in await sql.offer_rows(OfferScope(search=S1))}
    assert rows["olx_pl:1"].attributes["gpu"] == "GTX 1650"  # not the superseded "OLD"
    assert rows["olx_pl:1"].attributes["screen_in"] == Decimal("15.6")  # Decimal survives
    assert rows["olx_pl:7"].category is None and rows["olx_pl:7"].attributes == {}
    assert rows["olx_pl:4"].links[0].is_relevant is False  # override beats derived=True
    assert rows["olx_pl:5"].links[0].is_relevant is True
    relevant = {str(r.offer_id) for r in await sql.offer_rows(SCOPES["relevant-search"])}
    assert relevant == {"olx_pl:1", "olx_pl:2", "olx_pl:5"}
    unscoped = {str(r.offer_id): r for r in await sql.offer_rows(OfferScope())}
    assert len(unscoped["olx_pl:1"].links) == 2  # both searches
    anywhere = {str(r.offer_id) for r in await sql.offer_rows(OfferScope(relevant_only=True))}
    assert anywhere == relevant | {"olx_pl:6"}  # relevant in S2


async def test_price_kinds_and_amounts(store: SqlStore) -> None:
    async with store.uow() as uow:
        await uow.searches.save(SavedSearch(S1, SourceId("olx_pl"), "https://x.test", LAPTOP, T0))
        for key, price in (
            ("fixed", Price.fixed("1234.50", "PLN")),
            ("free", Price.free()),
            ("swap", Price.exchange()),
            ("none", None),
        ):
            offer = full_offer(key)
            offer.price = price
            await uow.offers.save(offer)
        await uow.commit()
    rows = {
        str(r.offer_id): r for r in await SqlAnalyticsQueries(store.engine).offer_rows(OfferScope())
    }
    assert rows["olx_pl:fixed"].price_amount == Decimal("1234.50")
    assert rows["olx_pl:fixed"].price_kind is PriceKind.FIXED
    assert rows["olx_pl:free"].price_kind is PriceKind.FREE
    assert rows["olx_pl:free"].price_amount is None
    assert rows["olx_pl:swap"].price_kind is PriceKind.EXCHANGE
    assert rows["olx_pl:none"].price_kind is None


async def test_overview_counts(both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries]) -> None:
    reference, sql = both
    expected, actual = await reference.overview(), await sql.overview()
    assert actual.dialect == "sqlite"
    assert [
        (c.search.name, c.offers, c.relevant, c.irrelevant, c.unknown, c.extracted)
        for c in actual.searches
    ] == [
        (c.search.name, c.offers, c.relevant, c.irrelevant, c.unknown, c.extracted)
        for c in expected.searches
    ]
    assert (actual.offers_total, actual.offers_extracted) == (
        expected.offers_total,
        expected.offers_extracted,
    )


async def test_attribute_fill_counts_json_nulls_in_sql(
    both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries],
) -> None:
    reference, sql = both
    names = ["gpu", "ram_gb", "screen_in", "missing_attr"]
    actual = await sql.attribute_fill(LAPTOP, names, None)
    expected = await reference.attribute_fill(LAPTOP, names, None)
    assert actual == expected
    by_name = {f.attribute: f for f in actual}
    assert by_name["gpu"].extracted == 5 and by_name["gpu"].filled == 4  # offer 4 has null gpu
    assert by_name["screen_in"].filled == 3  # 3 null, 10 has none; Decimal objects count
    assert by_name["missing_attr"].filled == 0
    scoped = await sql.attribute_fill(LAPTOP, ["gpu"], S2)
    assert scoped == await reference.attribute_fill(LAPTOP, ["gpu"], S2)
    assert scoped[0].extracted == 1


async def test_runs_snapshots_and_coverage(
    both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries], store: SqlStore
) -> None:
    reference, sql = both
    async with store.uow() as uow:
        for i in range(3):
            run = ScrapeRun(RunId(f"run{i}"), S1, SourceId("olx_pl"), at(i * 10))
            run.status = RunStatus.COMPLETED
            await uow.runs.save(run)
        change = FieldChange(TrackedField.PRICE, Price.fixed("10"), Price.fixed("9"))
        await uow.offers.add_snapshot(OfferSnapshot(oid("1"), at(5), (change,), RunId("run0")))
        await uow.offers.add_snapshot(OfferSnapshot(oid("2"), at(50), (change,)))
        await uow.commit()
    runs = await sql.recent_runs(S1, 2)
    assert [str(r.id) for r in runs] == ["run2", "run1"]
    assert await sql.recent_runs(S2, 5) == []
    everything = await sql.snapshots()
    assert [str(s.offer_id) for s in everything] == ["olx_pl:2", "olx_pl:1"]
    assert everything[1].changes[0].new == Price.fixed("9")
    recent = await sql.snapshots(since=at(5) + timedelta(seconds=1))
    assert [str(s.offer_id) for s in recent] == ["olx_pl:2"]
    only = await sql.snapshots(offer_ids=[oid("1")])
    assert [str(s.offer_id) for s in only] == ["olx_pl:1"]
    coverage = await sql.extraction_coverage(S1)
    expected = await reference.extraction_coverage(S1)
    assert (coverage.offers, coverage.extracted) == (expected.offers, expected.extracted)
    assert (coverage.offers, coverage.extracted) == (7, 6)
    all_coverage = await sql.extraction_coverage(None)
    assert (all_coverage.offers, all_coverage.extracted) == (8, 7)


async def test_tables_reflects_the_schema_without_alembic(store: SqlStore) -> None:
    tables = {t.name: t for t in await SqlAnalyticsQueries(store.engine).tables()}
    assert "alembic_version" not in tables
    assert {"offers", "extractions", "search_offers", "scrape_runs"} <= set(tables)
    columns = {c.name: c for c in tables["offers"].columns}
    assert columns["source"].primary_key and not columns["source"].nullable
    assert columns["title"].nullable


# ------------------------------------------------------------------------------ raw SQL


async def test_sql_select_with_row_limit(
    both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries],
) -> None:
    _, sql = both
    result = await sql.execute_sql(
        "SELECT source, external_id FROM offers ORDER BY external_id; -- trailing",
        max_rows=3,
        timeout_seconds=5,
    )
    assert result.columns == ("source", "external_id")
    assert len(result.rows) == 3 and result.truncated
    full = await sql.execute_sql(
        "WITH n AS (SELECT count(*) AS c FROM offers) SELECT c FROM n",
        max_rows=10,
        timeout_seconds=5,
    )
    assert full.rows == [(8,)] and not full.truncated


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM offers",
        "INSERT INTO saved_searches(name) VALUES ('x')",
        "SELECT 1; DELETE FROM offers",
        "SELECT 1; SELECT 2",
        "PRAGMA table_info(offers)",
        "ATTACH DATABASE 'x.db' AS x",
        "UPDATE offers SET title = 'x'",
        "CREATE TABLE t(x)",
        "DROP TABLE offers",
        "ALTER TABLE offers ADD COLUMN z",
        "REPLACE INTO offers(source) VALUES ('x')",
        "VACUUM",
        "WITH x AS (SELECT 1) DELETE FROM offers",
        "/* hi */ DELETE FROM offers",
        "-- note\nDROP TABLE offers",
        "",
        "   ;  ",
        "EXPLAIN SELECT 1",
        "SELECT 'unterminated",
    ],
)
async def test_sql_validation_rejects(statement: str) -> None:
    with pytest.raises(InvalidRequestError):
        validate_read_only_sql(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1",
        "select 1;",
        'SELECT \'a;b\', "update" FROM (SELECT 1 AS "update")',
        "SELECT replace('abc', 'b', 'x')",
        "SELECT 1 -- DELETE FROM offers",
        "/* DROP */ SELECT 1 /* ; DELETE */",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
        "SELECT 'it''s; DROP TABLE offers'",
    ],
)
def test_sql_validation_accepts(statement: str) -> None:
    assert validate_read_only_sql(statement)


async def test_sql_validation_error_reaches_the_caller(store: SqlStore) -> None:
    with pytest.raises(InvalidRequestError, match=r"read-only|allowed"):
        await SqlAnalyticsQueries(store.engine).execute_sql(
            "DELETE FROM offers", max_rows=5, timeout_seconds=5
        )


@pytest.mark.parametrize(
    "write",
    [
        "DELETE FROM offers",
        "WITH x AS (SELECT 1) DELETE FROM offers",
        "INSERT INTO saved_searches(name, source, url, category, created_at) "
        "VALUES ('x', 's', 'u', 'c', '2026-01-01')",
        "UPDATE offers SET title = 'hacked'",
        "DROP TABLE offers",
        "CREATE TABLE evil(x)",
    ],
)
async def test_read_only_connection_blocks_writes_even_without_validation(
    both: tuple[InMemoryAnalyticsQueries, SqlAnalyticsQueries], write: str
) -> None:
    _, sql = both
    with pytest.raises(InvalidRequestError, match=r"readonly|read-only|SQL error"):
        await sql.execute_validated_sql(write, max_rows=5, timeout_seconds=5)  # validator bypassed
    after = await sql.execute_sql(
        "SELECT count(*), sum(title = 'hacked') FROM offers", max_rows=5, timeout_seconds=5
    )
    assert after.rows == [(8, 0)]
    tables = {t.name for t in await sql.tables()}
    assert "evil" not in tables and "offers" in tables


async def test_sql_timeout(store: SqlStore) -> None:
    with pytest.raises(InvalidRequestError, match="timed out"):
        await SqlAnalyticsQueries(store.engine).execute_sql(
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
            "SELECT count(*) FROM c",
            max_rows=5,
            timeout_seconds=0.3,
        )


async def test_sql_error_is_a_clean_request_error(store: SqlStore) -> None:
    with pytest.raises(InvalidRequestError, match="no such table"):
        await SqlAnalyticsQueries(store.engine).execute_sql(
            "SELECT * FROM nope", max_rows=5, timeout_seconds=5
        )

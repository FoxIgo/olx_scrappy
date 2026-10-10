"""``scrappy q ...``: the read-only, JSON-only query interface for agents (ADR 0009).

Every command prints ONE JSON document on stdout (the envelope: ok, command, params, count,
truncated, data, notes). Failures print the same envelope with ``ok: false`` and exit 1; no
traceback unless the global ``--debug`` is given. ``q export`` without ``--out`` is the one
exception: it streams the table itself (CSV/JSONL) for piping.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import typer

from scrappy.application.errors import InvalidRequestError
from scrappy.application.use_cases.analytics import Answer, QueryScope
from scrappy.application.use_cases.analytics.common import DEFAULT_STATUSES
from scrappy.application.use_cases.analytics.rank import DEFAULT_MIN_COVERAGE, DEFAULT_RANK_LIMIT
from scrappy.application.use_cases.analytics.sql import DEFAULT_SQL_LIMIT
from scrappy.domain.analytics import DEFAULT_MAX_RATIO, DEFAULT_MIN_GROUP
from scrappy.domain.category import CategoryName
from scrappy.domain.component import ComponentKind
from scrappy.domain.offer import OfferStatus
from scrappy.domain.search import SearchName
from scrappy.presentation.cli.common import cli_context
from scrappy.presentation.cli.filters import parse_wheres
from scrappy.presentation.cli.q_render import (
    dumps,
    error_envelope,
    ok_envelope,
    table_csv,
    table_jsonl,
)
from scrappy.presentation.logging import configure_logging
from scrappy.presentation.services import Services

q_app = typer.Typer(
    help="Read-only JSON queries for agents (one JSON document per command).",
    no_args_is_help=True,
)

SearchOpt = Annotated[str | None, typer.Option("--search", help="Scope to a saved search.")]
CategoryOpt = Annotated[
    str | None, typer.Option("--category", help="Category of the latest extraction.")
]
RelevantOpt = Annotated[
    bool, typer.Option("--relevant/--all", help="Hide junk (default) or include everything.")
]
StatusOpt = Annotated[
    list[str] | None,
    typer.Option("--status", help="Offer status, repeatable; default active; 'any' = all."),
]
WhereOpt = Annotated[
    list[str] | None,
    typer.Option("--where", "-w", help='Filter, e.g. "ram_gb>=16" or "price<2000" (repeatable).'),
]
LimitOpt = Annotated[int, typer.Option("--limit", "-n", min=1, help="Maximum rows.")]
PrettyOpt = Annotated[bool, typer.Option("--pretty", help="Indent the JSON.")]


def _statuses(values: list[str] | None) -> frozenset[OfferStatus]:
    if not values:
        return DEFAULT_STATUSES
    allowed = ", ".join([*(s.value for s in OfferStatus), "any"])
    result: set[OfferStatus] = set()
    for value in values:
        if value.lower() == "any":
            return frozenset()
        try:
            result.add(OfferStatus(value.lower()))
        except ValueError:
            raise InvalidRequestError(f"unknown status {value!r}; expected: {allowed}") from None
    return frozenset(result)


def _scope(
    search: str | None,
    category: str | None,
    relevant: bool,
    status: list[str] | None,
    where: list[str] | None,
) -> QueryScope:
    return QueryScope(
        search=SearchName(search) if search else None,
        category=CategoryName(category) if category else None,
        relevant_only=relevant,
        statuses=_statuses(status),
        where=parse_wheres(where or ()),
    )


def _base_params(
    search: str | None,
    category: str | None,
    relevant: bool,
    status: list[str] | None,
    where: list[str] | None,
) -> dict[str, object]:
    return {
        "search": search,
        "category": category,
        "relevance": "relevant" if relevant else "all",
        "status": status or ["active"],
        "filters": list(where or ()),
    }


def _split(values: str | None) -> list[str]:
    return [v.strip() for v in (values or "").split(",") if v.strip()]


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidRequestError(
            f"cannot parse date {value!r}: expected YYYY-MM-DD or an ISO-8601 datetime"
        ) from None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _decimal(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise InvalidRequestError(f"{name} must be a number, got {value!r}") from None


def _emit(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def run_q(
    ctx: typer.Context,
    command: str,
    params: dict[str, object],
    action: Callable[[Services], Awaitable[Answer]],
    *,
    pretty: bool,
    envelope: bool = True,
) -> None:
    """Open the app, run ``action``, print the envelope; map any failure to an error envelope
    (exit 1). ``--debug`` re-raises instead."""
    context = cli_context(ctx)

    async def main() -> Answer:
        app = await context.open_app()
        try:
            configure_logging("DEBUG" if context.debug else "WARNING")
            return await action(app)
        finally:
            await app.aclose()

    try:
        answer = asyncio.run(main())
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except Exception as error:
        if context.debug:
            raise
        _emit(dumps(error_envelope(command, params, error), pretty=pretty))
        raise typer.Exit(1) from None
    if envelope:
        _emit(dumps(ok_envelope(command, params, answer), pretty=pretty))


# ------------------------------------------------------------------------------ commands


@q_app.command("overview")
def overview(ctx: typer.Context, pretty: PrettyOpt = False) -> None:
    """What is in the database: searches, counts, last runs, categories, dialect."""

    async def go(app: Services) -> Answer:
        return await app.q.overview()

    run_q(ctx, "q.overview", {}, go, pretty=pretty)


@q_app.command("schema")
def schema(
    ctx: typer.Context,
    category: CategoryOpt = None,
    tables: Annotated[
        bool, typer.Option("--tables", help="Also list DB tables and columns (for `q sql`).")
    ] = False,
    pretty: PrettyOpt = False,
) -> None:
    """Category attribute specs from the live catalog (+ tables with --tables)."""

    async def go(app: Services) -> Answer:
        return await app.q.schema(
            category=CategoryName(category) if category else None, tables=tables
        )

    run_q(ctx, "q.schema", {"category": category, "tables": tables}, go, pretty=pretty)


@q_app.command("offers")
def offers(
    ctx: typer.Context,
    search: SearchOpt = None,
    category: CategoryOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    limit: LimitOpt = 50,
    fields: Annotated[
        str | None,
        typer.Option("--fields", help="Comma list of fields and/or attribute names to return."),
    ] = None,
    sort: Annotated[
        str, typer.Option("--sort", help="seen (default) | price | price-desc")
    ] = "seen",
    pretty: PrettyOpt = False,
) -> None:
    """Filtered list of offers."""
    params = {
        **_base_params(search, category, relevant, status, where),
        "limit": limit,
        "fields": _split(fields),
        "sort": sort,
    }

    async def go(app: Services) -> Answer:
        scope = _scope(search, category, relevant, status, where)
        return await app.q.offers(scope, limit=limit, fields=_split(fields), sort=sort)

    run_q(ctx, "q.offers", params, go, pretty=pretty)


@q_app.command("offer")
def offer(
    ctx: typer.Context,
    ids: Annotated[list[str], typer.Argument(metavar="ID...", help="source:external_id")],
    pretty: PrettyOpt = False,
) -> None:
    """Full detail of specific offers: extraction, snapshots, searches."""

    async def go(app: Services) -> Answer:
        return await app.q.offer(ids)

    run_q(ctx, "q.offer", {"ids": ids}, go, pretty=pretty)


@q_app.command("facets")
def facets(
    ctx: typer.Context,
    attr: Annotated[
        list[str] | None, typer.Option("--attr", help="Attribute (repeatable, required).")
    ] = None,
    search: SearchOpt = None,
    category: CategoryOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    pretty: PrettyOpt = False,
) -> None:
    """Which values an attribute takes and how often (numbers: min/max/buckets)."""
    params = {**_base_params(search, category, relevant, status, where), "attributes": attr or []}

    async def go(app: Services) -> Answer:
        return await app.q.facets(_scope(search, category, relevant, status, where), attr or [])

    run_q(ctx, "q.facets", params, go, pretty=pretty)


@q_app.command("stats")
def stats(
    ctx: typer.Context,
    by: Annotated[
        list[str] | None, typer.Option("--by", help="Group by this attribute (repeatable).")
    ] = None,
    metric: Annotated[str, typer.Option("--metric", help="Only `price` for now.")] = "price",
    search: SearchOpt = None,
    category: CategoryOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    limit: LimitOpt = 100,
    pretty: PrettyOpt = False,
) -> None:
    """Price statistics (n, min, p25, median, p75, max, mean) per attribute group."""
    params = {
        **_base_params(search, category, relevant, status, where),
        "by": by or [],
        "metric": metric,
        "limit": limit,
    }

    async def go(app: Services) -> Answer:
        scope = _scope(search, category, relevant, status, where)
        return await app.q.stats(scope, by or [], metric=metric, limit=limit)

    run_q(ctx, "q.stats", params, go, pretty=pretty)


@q_app.command("deals")
def deals(
    ctx: typer.Context,
    compare_by: Annotated[
        str | None,
        typer.Option("--compare-by", help="Comma list of attributes that define 'comparable'."),
    ] = None,
    min_group: Annotated[int, typer.Option("--min-group", min=2)] = DEFAULT_MIN_GROUP,
    max_ratio: Annotated[
        str, typer.Option("--max-ratio", help="price/median at or below this is a deal.")
    ] = str(DEFAULT_MAX_RATIO),
    search: SearchOpt = None,
    category: CategoryOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    limit: LimitOpt = 20,
    pretty: PrettyOpt = False,
) -> None:
    """Offers priced well below the median of comparable offers."""
    params = {
        **_base_params(search, category, relevant, status, where),
        "compare_by": _split(compare_by),
        "min_group": min_group,
        "max_ratio": max_ratio,
        "limit": limit,
    }

    async def go(app: Services) -> Answer:
        return await app.q.deals(
            _scope(search, category, relevant, status, where),
            _split(compare_by),
            min_group=min_group,
            max_ratio=_decimal(max_ratio, "max-ratio"),
            limit=limit,
        )

    run_q(ctx, "q.deals", params, go, pretty=pretty)


@q_app.command("rank")
def rank(
    ctx: typer.Context,
    strategy: Annotated[
        str, typer.Option("--strategy", "-s", help="Scoring strategy (see `q strategies`).")
    ],
    min_coverage: Annotated[
        float,
        typer.Option(
            "--min-coverage", min=0, max=1, help="Skip offers whose known share of weight is lower."
        ),
    ] = DEFAULT_MIN_COVERAGE,
    search: SearchOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    limit: LimitOpt = DEFAULT_RANK_LIMIT,
    fields: Annotated[
        str | None,
        typer.Option(
            "--fields",
            help="Comma list: id,title,url,price,currency,performance,"
            "value,coverage,breakdown and/or attribute names.",
        ),
    ] = None,
    pretty: PrettyOpt = False,
) -> None:
    """Rank offers by price per performance under a configured strategy (config/scoring.yaml)."""
    params = {
        **_base_params(search, None, relevant, status, where),
        "strategy": strategy,
        "min_coverage": min_coverage,
        "limit": limit,
        "fields": _split(fields),
    }

    async def go(app: Services) -> Answer:
        scope = _scope(search, None, relevant, status, where)
        return await app.q.rank(
            scope, strategy, min_coverage=min_coverage, limit=limit, fields=_split(fields)
        )

    run_q(ctx, "q.rank", params, go, pretty=pretty)


@q_app.command("strategies")
def strategies(ctx: typer.Context, pretty: PrettyOpt = False) -> None:
    """The configured scoring strategies: terms, weights, baselines, filters."""

    async def go(app: Services) -> Answer:
        return await app.q.strategies()

    run_q(ctx, "q.strategies", {}, go, pretty=pretty)


@q_app.command("components")
def components(
    ctx: typer.Context,
    kind: Annotated[str | None, typer.Option("--kind", help="cpu | gpu")] = None,
    search: Annotated[
        str | None, typer.Option("--search", help="Substring of the part name.")
    ] = None,
    linked: Annotated[
        bool, typer.Option("--linked", help="Only parts that offers link to (most offers first).")
    ] = False,
    limit: LimitOpt = 50,
    pretty: PrettyOpt = False,
) -> None:
    """CPU/GPU parts with their benchmark scores and how many offers link to each."""
    params = {"kind": kind, "search": search, "linked": linked, "limit": limit}

    async def go(app: Services) -> Answer:
        parsed: ComponentKind | None = None
        if kind is not None:
            try:
                parsed = ComponentKind(kind.lower())
            except ValueError:
                raise InvalidRequestError(f"unknown kind {kind!r}; expected: cpu, gpu") from None
        return await app.q.components(kind=parsed, search=search, limit=limit, linked_only=linked)

    run_q(ctx, "q.components", params, go, pretty=pretty)


@q_app.command("history")
def history(
    ctx: typer.Context,
    offer_id: Annotated[str | None, typer.Option("--offer", help="One offer id.")] = None,
    since: Annotated[
        str | None, typer.Option("--since", help="YYYY-MM-DD or ISO datetime (UTC if naive).")
    ] = None,
    field: Annotated[str | None, typer.Option("--field", help="price, title, status, ...")] = None,
    search: SearchOpt = None,
    category: CategoryOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    limit: LimitOpt = 100,
    pretty: PrettyOpt = False,
) -> None:
    """Field changes over time (newest first) and offers first seen since a date."""
    params = {
        **_base_params(search, category, relevant, status, where),
        "offer": offer_id,
        "since": since,
        "field": field,
        "limit": limit,
    }

    async def go(app: Services) -> Answer:
        return await app.q.history(
            _scope(search, category, relevant, status, where),
            offer=offer_id,
            since=_parse_since(since),
            field=field,
            limit=limit,
        )

    run_q(ctx, "q.history", params, go, pretty=pretty)


@q_app.command("health")
def health(
    ctx: typer.Context,
    search: SearchOpt = None,
    runs: Annotated[int, typer.Option("--runs", min=1, help="How many recent runs.")] = 5,
    pretty: PrettyOpt = False,
) -> None:
    """Data quality: recent runs, extraction coverage, null rates, stale offers."""

    async def go(app: Services) -> Answer:
        return await app.q.health(search=SearchName(search) if search else None, runs=runs)

    run_q(ctx, "q.health", {"search": search, "runs": runs}, go, pretty=pretty)


@q_app.command("sql")
def sql(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="A single SELECT / WITH statement.")],
    limit: LimitOpt = DEFAULT_SQL_LIMIT,
    pretty: PrettyOpt = False,
) -> None:
    """Fallback: read-only SQL (read-only connection, row limit, timeout)."""

    async def go(app: Services) -> Answer:
        return await app.q.sql(query, limit=limit)

    run_q(ctx, "q.sql", {"query": query, "limit": limit}, go, pretty=pretty)


@q_app.command("export")
def export(
    ctx: typer.Context,
    fmt: Annotated[str, typer.Option("--format", help="csv (default) | jsonl")] = "csv",
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write here and print the envelope; else stream to stdout."),
    ] = None,
    search: SearchOpt = None,
    category: CategoryOpt = None,
    relevant: RelevantOpt = True,
    status: StatusOpt = None,
    where: WhereOpt = None,
    pretty: PrettyOpt = False,
) -> None:
    """Flat table (one row per offer, attr_* columns) for pandas/DuckDB. No row limit."""
    params = {
        **_base_params(search, category, relevant, status, where),
        "format": fmt,
        "out": None if out is None else str(out),
    }

    async def go(app: Services) -> Answer:
        if fmt not in ("csv", "jsonl"):
            raise InvalidRequestError(f"unknown format {fmt!r}; expected csv or jsonl")
        table = await app.q.export(_scope(search, category, relevant, status, where))
        render = table_csv if fmt == "csv" else table_jsonl
        text = render(table.columns, table.rows)
        if out is None:
            sys.stdout.write(text)
            sys.stdout.flush()
            for note in table.notes:
                sys.stderr.write(f"note: {note}\n")
            return Answer(None)
        target = out.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        data = {"path": str(target), "rows": len(table.rows), "columns": table.columns}
        return Answer(data, len(table.rows), notes=table.notes)

    run_q(ctx, "q.export", params, go, pretty=pretty, envelope=out is not None)

"""``scrappy offers list|show|relevance``."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

import typer

from scrappy.application.errors import InvalidRequestError, NotFoundError
from scrappy.application.ports.queries import (
    LivenessFilter,
    OfferFilter,
    OfferListItem,
    RelevanceFilter,
)
from scrappy.domain.category import CategoryName
from scrappy.domain.offer import OfferId, OfferStatus
from scrappy.domain.search import SearchName
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.filters import parse_wheres
from scrappy.presentation.cli.render import (
    offer_detail,
    offers_table,
    stdout,
    verify_results_table,
)
from scrappy.presentation.services import Services

offers_app = typer.Typer(help="Browse offers.", no_args_is_help=True)

SORTS = ("seen", "price", "price-desc")
SORT_FETCH_LIMIT = 50_000
"""Sorting by price happens here (the query port orders by last seen), so all matches are
fetched first and cut to ``--limit`` afterwards."""


def _amount(item: OfferListItem) -> Decimal | None:
    price = item.offer.price
    return price.amount.amount if price and price.amount else None


def sort_items(items: list[OfferListItem], sort: str) -> list[OfferListItem]:
    """Order for ``--sort``; offers without a money amount always come last."""
    if sort not in ("price", "price-desc"):
        return items
    priced = [i for i in items if _amount(i) is not None]
    unpriced = [i for i in items if _amount(i) is None]
    priced.sort(key=lambda i: _amount(i) or Decimal(0), reverse=sort == "price-desc")
    return priced + unpriced


def _statuses(values: list[str] | None) -> frozenset[OfferStatus]:
    allowed = ", ".join(s.value for s in OfferStatus)
    result: set[OfferStatus] = set()
    for value in values or ():
        try:
            result.add(OfferStatus(value.lower()))
        except ValueError:
            raise InvalidRequestError(f"unknown status {value!r}; expected: {allowed}") from None
    return frozenset(result)


@offers_app.command("list")
def list_cmd(
    ctx: typer.Context,
    search: Annotated[str, typer.Argument(help="Saved search name.")],
    relevant: Annotated[
        bool, typer.Option("--relevant/--all", help="Only offers relevant to the search.")
    ] = False,
    status: Annotated[
        list[str] | None, typer.Option("--status", help="Offer status (repeatable).")
    ] = None,
    where: Annotated[
        list[str] | None,
        typer.Option("--where", "-w", help='Attribute filter, e.g. "ram_gb>=16" (repeatable).'),
    ] = None,
    delivery: Annotated[
        bool | None,
        typer.Option(
            "--delivery/--no-delivery",
            help="Filter by OLX delivery (safe buy) availability.",
        ),
    ] = None,
    alive: Annotated[
        bool | None,
        typer.Option(
            "--alive/--all-liveness",
            help="Filter alive offers only (hides stale and zombie/ghost offers).",
        ),
    ] = None,
    liveness: Annotated[
        str | None,
        typer.Option("--liveness", help="all | alive | stale | zombie"),
    ] = None,
    category: Annotated[
        str | None, typer.Option("--category", help="Category of the latest extraction.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1)] = 50,
    sort: Annotated[
        str, typer.Option("--sort", help="seen (default) | price | price-desc")
    ] = "seen",
    verify: Annotated[
        bool,
        typer.Option("--verify", help="Live-verify matching offers and refresh before displaying."),
    ] = False,
) -> None:
    """List a search's offers with optional filters (AND-ed)."""

    async def go(app: Services) -> None:
        if sort not in SORTS:
            raise InvalidRequestError(f"unknown sort {sort!r}; expected one of: {', '.join(SORTS)}")
        liveness_filter = LivenessFilter.ALL
        if alive is True:
            liveness_filter = LivenessFilter.ALIVE
        elif liveness:
            try:
                liveness_filter = LivenessFilter(liveness.lower())
            except ValueError as exc:
                raise InvalidRequestError(
                    f"unknown liveness {liveness!r}; expected one of: all, alive, stale, zombie"
                ) from exc
        query = OfferFilter(
            search=SearchName(search),
            relevance=RelevanceFilter.RELEVANT if relevant else RelevanceFilter.ALL,
            liveness=liveness_filter,
            statuses=_statuses(status),
            category=CategoryName(category) if category else None,
            attributes=parse_wheres(where or ()),
            has_delivery=delivery,
            limit=limit if sort == "seen" else SORT_FETCH_LIMIT,
        )
        items = sort_items(await app.list_offers(query), sort)[:limit]
        if verify and items:
            await app.verify_offers.verify_many([item.offer.id for item in items])
            items = sort_items(await app.list_offers(query), sort)[:limit]

        console = stdout()
        if not items:
            console.print("No offers match.")
            return
        console.print(offers_table(items, with_relevance=True, title=f"Offers of {search}"))
        console.print(f"{len(items)} offer(s) shown.")

    execute(ctx, go)


@offers_app.command("show")
def show(
    ctx: typer.Context,
    offer_id: Annotated[str, typer.Argument(metavar="SOURCE:EXTERNAL_ID")],
) -> None:
    """Show one offer: details, latest extraction, searches, change history."""

    async def go(app: Services) -> None:
        oid = OfferId.parse(offer_id)
        async with app.uow() as uow:
            offer = await uow.offers.get(oid)
            if offer is None:
                raise NotFoundError(f"offer {oid} not found")
            extraction = await uow.extractions.latest(oid)
            snapshots = await uow.offers.list_snapshots(oid)
            links = await uow.search_offers.list_for_offer(oid)
        stdout().print(offer_detail(offer, extraction, snapshots, links))

    execute(ctx, go)


@offers_app.command("relevance")
def relevance(
    ctx: typer.Context,
    search: str,
    offer_id: Annotated[str, typer.Argument(metavar="SOURCE:EXTERNAL_ID")],
    yes: Annotated[bool, typer.Option("--yes", help="Mark relevant.")] = False,
    no: Annotated[bool, typer.Option("--no", help="Mark irrelevant.")] = False,
    clear: Annotated[bool, typer.Option("--clear", help="Remove the manual decision.")] = False,
) -> None:
    """Override relevance of an offer for a search."""
    if [yes, no, clear].count(True) != 1:
        raise typer.BadParameter("give exactly one of --yes, --no, --clear")
    value: bool | None = True if yes else (False if no else None)

    async def go(app: Services) -> None:
        link = await app.set_override(SearchName(search), OfferId.parse(offer_id), value)
        state = {True: "relevant", False: "irrelevant", None: "override cleared"}[value]
        effective = {True: "relevant", False: "irrelevant", None: "unknown"}[link.is_relevant]
        stdout().print(f"Offer {link.offer_id} in {link.search}: {state} (effective: {effective})")

    execute(ctx, go)


@offers_app.command("verify")
def verify_cmd(
    ctx: typer.Context,
    offer_ids: Annotated[
        list[str] | None,
        typer.Argument(metavar="[OFFER_ID...]", help="Specific offer IDs (e.g. olx_pl:123456)."),
    ] = None,
    search: Annotated[
        str | None, typer.Option("--search", "-s", help="Filter by saved search name.")
    ] = None,
    relevant: Annotated[
        bool, typer.Option("--relevant/--all", help="Only offers relevant to the search.")
    ] = True,
    status: Annotated[
        list[str] | None, typer.Option("--status", help="Offer status filter; default: active.")
    ] = None,
    where: Annotated[
        list[str] | None,
        typer.Option("--where", "-w", help='Attribute filter, e.g. "price<2000" (repeatable).'),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1)] = 20,
) -> None:
    """Verify live freshness / availability of stored offers against their source."""

    async def go(app: Services) -> None:
        target_ids: list[OfferId] = []
        if offer_ids:
            target_ids = [OfferId.parse(oid) for oid in offer_ids]
        elif search:
            query = OfferFilter(
                search=SearchName(search),
                relevance=RelevanceFilter.RELEVANT if relevant else RelevanceFilter.ALL,
                statuses=_statuses(status or ["active"]),
                attributes=parse_wheres(where or ()),
                limit=limit,
            )
            items = await app.list_offers(query)
            target_ids = [item.offer.id for item in items]
        else:
            raise typer.BadParameter("specify one or more OFFER_ID arguments or --search")

        console = stdout()
        if not target_ids:
            console.print("No offers match for verification.")
            return

        results = await app.verify_offers.verify_many(target_ids)
        console.print(verify_results_table(results))
        dead_count = sum(1 for r in results if not r.is_active)
        changed_count = sum(1 for r in results if r.changed)
        console.print(
            f"Verified {len(results)} offer(s): {len(results) - dead_count} active, "
            f"{dead_count} unavailable ({changed_count} updated in database)."
        )

    execute(ctx, go)

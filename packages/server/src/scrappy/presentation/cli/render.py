"""Rich rendering for the CLI: tables and the run report. No business logic."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, TextIO

from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from scrappy.application.extraction.prepare import prepare_description
from scrappy.application.jobs.model import Job, JobStatus
from scrappy.application.ports.queries import OfferListItem
from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import (
    LivenessEvaluation,
    LivenessStatus,
    Offer,
    OfferSnapshot,
)
from scrappy.domain.offer.offer import FieldChange
from scrappy.domain.run import Phase, PhaseMetrics, RunStatus, ScrapeRun
from scrappy.domain.search import SavedSearch, SearchOffer

_STATUS_STYLE: Mapping[RunStatus, str] = {
    RunStatus.RUNNING: "cyan",
    RunStatus.COMPLETED: "green",
    RunStatus.PARTIAL: "yellow",
    RunStatus.DEGRADED: "yellow",
    RunStatus.FAILED: "red",
}


def configure_streams(streams: Iterable[TextIO] | None = None) -> None:
    """Make output survive non-ASCII text (Polish letters) on Windows.

    A redirected or piped stream there uses the ANSI code page (cp1251, cp1252...), and
    printing e.g. ``ą`` raises ``UnicodeEncodeError``. Redirected streams become UTF-8 (what
    consumers of a pipe or file expect); a terminal keeps its encoding but never raises."""
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        if stream.isatty():
            reconfigure(errors="replace")
        else:
            reconfigure(encoding="utf-8", errors="replace")


def stdout() -> Console:
    return Console()


def stderr() -> Console:
    return Console(stderr=True)


def error_line(message: str) -> None:
    stderr().print(f"[bold red]error:[/] {_escape(message)}")


def _escape(text: str) -> str:
    return escape(text)


def fmt_time(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def fmt_duration(delta: timedelta | None) -> str:
    if delta is None:
        return "-"
    seconds = int(delta.total_seconds())
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def status_text(status: RunStatus) -> Text:
    return Text(status.value.upper(), style=_STATUS_STYLE[status])


def relevance_text(value: bool | None) -> str:
    return {True: "yes", False: "no", None: "?"}[value]


def attribute_text(extraction: OfferExtraction | None) -> str:
    if extraction is None:
        return "-"
    parts = [f"{k}={v}" for k, v in extraction.attributes.items() if v is not None]
    return f"{extraction.category}: " + (" ".join(parts) if parts else "-")


# ------------------------------------------------------------------------------ searches


def searches_table(searches: Sequence[SavedSearch]) -> Table:
    table = Table(title="Saved searches")
    for column in ("Name", "Source", "Category", "Last run", "URL"):
        table.add_column(column, overflow="fold")
    for search in searches:
        table.add_row(
            Text(str(search.name)),
            Text(str(search.source)),
            Text(str(search.category)),
            Text(fmt_time(search.last_run_at)),
            Text(search.url),
        )
    return table


def search_detail(search: SavedSearch, runs: Sequence[ScrapeRun]) -> RenderableType:
    info = Table.grid(padding=(0, 2))
    info.add_row("Name", str(search.name))
    info.add_row("Source", str(search.source))
    info.add_row("Category", str(search.category))
    info.add_row("URL", Text(search.url, overflow="fold"))
    info.add_row("Created", fmt_time(search.created_at))
    info.add_row("Last run", fmt_time(search.last_run_at))
    return Group(Panel(info, title=f"Search {search.name}"), runs_table(runs, title="Recent runs"))


# ---------------------------------------------------------------------------------- runs


def runs_table(runs: Sequence[ScrapeRun], *, title: str = "Runs") -> Table:
    table = Table(title=title)
    table.add_column("Run", no_wrap=True, min_width=32)  # the id is what other commands take
    for column in ("Search", "Status", "Started", "Duration", "Accepted", "Failed jobs"):
        table.add_column(column)
    for run in runs:
        duration = run.finished_at - run.started_at if run.finished_at else None
        table.add_row(
            str(run.id),
            str(run.search),
            status_text(run.status),
            fmt_time(run.started_at),
            fmt_duration(duration),
            str(run.metrics.discovery.accepted),
            str(run.metrics.failed_jobs),
        )
    return table


def _shown_phases(run: ScrapeRun) -> list[Phase]:
    """Extraction is no longer part of a run (ADR 0010); only old runs have its metrics."""
    return [p for p in Phase if p is not Phase.EXTRACTION or run.metrics.extraction.seen]


def _phase_table(run: ScrapeRun) -> Table:
    table = Table(title="Phases")
    for column in ("Phase", "Accepted", "Rejected", "Rejected %", "Fetch outcomes"):
        table.add_column(column)
    for phase in _shown_phases(run):
        metrics = run.metrics.phase(phase)
        outcomes = ", ".join(f"{o.value}={n}" for o, n in sorted(metrics.outcomes.items()))
        table.add_row(
            phase.value,
            str(metrics.accepted),
            str(metrics.rejected),
            f"{metrics.rejected_ratio:.1%}",
            outcomes or "-",
        )
    return table


def _fill_rate_table(run: ScrapeRun) -> Table | None:
    rows: list[tuple[str, str, PhaseMetrics]] = []
    for phase in _shown_phases(run):
        metrics = run.metrics.phase(phase)
        for name in sorted(metrics.applicable):
            rows.append((phase.value, name, metrics))
    if not rows:
        return None
    table = Table(title="Fill rates")
    for column in ("Phase", "Field", "Present", "Rate"):
        table.add_column(column)
    for phase_name, name, metrics in rows:
        rate = metrics.fill_rate(name)
        table.add_row(
            phase_name,
            name,
            f"{metrics.present.get(name, 0)}/{metrics.applicable.get(name, 0)}",
            f"{rate:.0%}" if rate is not None else "-",
        )
    return table


def run_report(
    run: ScrapeRun, jobs: Sequence[Job] | None = None, *, extraction_backlog: int | None = None
) -> RenderableType:
    metrics = run.metrics
    head = Table.grid(padding=(0, 2))
    head.add_row("Run", str(run.id))
    head.add_row("Search", f"{run.search} ({run.source})")
    head.add_row("Status", status_text(run.status))
    head.add_row("Started", fmt_time(run.started_at))
    head.add_row("Finished", fmt_time(run.finished_at))
    if run.finished_at:
        head.add_row("Duration", fmt_duration(run.finished_at - run.started_at))
    if jobs is not None:
        counts = {s: sum(1 for j in jobs if j.status is s) for s in JobStatus}
        head.add_row("Jobs", ", ".join(f"{s.value}={n}" for s, n in counts.items() if n) or "-")
    coverage = metrics.coverage
    total = coverage.total_reported if coverage.total_reported is not None else "?"
    head.add_row("Coverage", f"{coverage.pages} page(s), site reports {total} result(s)")
    usage = metrics.usage
    if usage.total_tokens or usage.cost_usd is not None:  # runs from before ADR 0010
        cost = f", cost ${usage.cost_usd:.4f}" if usage.cost_usd is not None else ""
        head.add_row(
            "LLM tokens",
            f"{usage.prompt_tokens} prompt + {usage.completion_tokens} completion{cost}",
        )
    if extraction_backlog is not None:
        head.add_row(
            "Extraction",
            f"backlog for this search: {extraction_backlog} offer(s)"
            + (" (processed by the extractor loop)" if extraction_backlog else ""),
        )

    parts: list[RenderableType] = [Panel(head, title="Run report"), _phase_table(run)]
    fills = _fill_rate_table(run)
    if fills is not None:
        parts.append(fills)
    if coverage.truncated:
        parts.append(
            Text(
                "WARNING: results were truncated by the site - split your search "
                "(price ranges, region, category) to reach every offer.",
                style="bold yellow",
            )
        )
    for warning in run.warnings:
        parts.append(Text(f"warning: {warning}", style="yellow"))
    for reason in run.reasons:
        parts.append(Text(f"reason: {reason}", style="yellow"))
    if run.errors:
        parts.append(Text("Errors:", style="bold red"))
        parts.extend(Text(f"  {error}", style="red", overflow="fold") for error in run.errors)
    return Group(*parts)


# ------------------------------------------------------------------------------- offers


WIDE_TABLE = 130
"""Terminal width from which the offers table also shows the URL column."""


def liveness_text(eval: LivenessEvaluation) -> Text:
    match eval.status:
        case LivenessStatus.ALIVE:
            return Text(f"alive ({eval.score})", style="green")
        case LivenessStatus.STALE:
            return Text(f"stale ({eval.score})", style="yellow")
        case LivenessStatus.ZOMBIE:
            return Text(f"zombie ({eval.score})", style="red")


def liveness_style(status: LivenessStatus) -> str:
    match status:
        case LivenessStatus.ALIVE:
            return "green"
        case LivenessStatus.STALE:
            return "yellow"
        case LivenessStatus.ZOMBIE:
            return "red"


def offers_table(items: Sequence[OfferListItem], *, with_relevance: bool, title: str) -> Table:
    table = Table(title=title)
    table.add_column("Offer", no_wrap=True)
    table.add_column("Title", overflow="fold", ratio=3)
    table.add_column("Price", justify="right", min_width=8)
    table.add_column("Location", overflow="fold", ratio=2)
    if with_relevance:
        table.add_column("Rel", no_wrap=True)
    table.add_column("Live", no_wrap=True)
    table.add_column("Delivery", no_wrap=True)
    table.add_column("Attributes", overflow="fold", ratio=2)
    with_url = stdout().width >= WIDE_TABLE  # seven columns do not fit a narrow terminal
    if with_url:
        table.add_column("URL", no_wrap=True, overflow="ellipsis", max_width=40)
    for item in items:
        offer = item.offer
        row = [
            Text(str(offer.id)),
            Text(offer.title or "-"),
            Text(str(offer.price) if offer.price else "-"),
            Text(offer.location or "-"),
        ]
        if with_relevance:
            row.append(Text(relevance_text(item.link.is_relevant if item.link else None)))
        row.append(liveness_text(offer.liveness))
        row.append(Text("yes", style="green") if offer.has_delivery else Text("-", style="dim"))
        row.append(Text(attribute_text(item.extraction)))
        if with_url:
            row.append(Text(offer.url))
        table.add_row(*row)
    return table


def _change_text(change: FieldChange) -> str:
    return f"{change.field.value}: {change.old} -> {change.new}"


def offer_detail(
    offer: Offer,
    extraction: OfferExtraction | None,
    snapshots: Sequence[OfferSnapshot],
    links: Sequence[SearchOffer],
) -> RenderableType:
    info = Table.grid(padding=(0, 2))
    info.add_row("Id", str(offer.id))
    info.add_row("Title", Text(offer.title or "-"))
    info.add_row("Price", str(offer.price) if offer.price else "-")
    info.add_row("Location", Text(offer.location or "-"))
    info.add_row("Status", offer.status.value)
    live = offer.liveness
    reasons_str = f" ({'; '.join(live.reasons)})" if live.reasons else ""
    info.add_row(
        "Liveness",
        Text(
            f"{live.status.value.upper()} [{live.score}/100]{reasons_str}",
            style=liveness_style(live.status),
        ),
    )
    if offer.seller:
        seller_parts = [offer.seller.name or "anonymous"]
        if offer.seller.last_seen_at:
            seller_parts.append(f"last seen: {fmt_time(offer.seller.last_seen_at)}")
        if offer.seller.created_at:
            seller_parts.append(f"joined: {fmt_time(offer.seller.created_at)}")
        if offer.seller.is_online:
            seller_parts.append("(online now)")
        info.add_row("Seller", Text(", ".join(seller_parts)))
    if offer.posted_at:
        info.add_row("Posted at", fmt_time(offer.posted_at))
    if offer.refreshed_at:
        info.add_row("Refreshed at", fmt_time(offer.refreshed_at))
    info.add_row(
        "Delivery",
        Text("available (Przesyłka OLX)", style="green")
        if offer.has_delivery
        else Text("no (pickup only)", style="dim"),
    )
    info.add_row("URL", Text(offer.url, overflow="fold"))
    info.add_row("First seen", fmt_time(offer.first_seen_at))
    info.add_row("Last seen", fmt_time(offer.last_seen_at))
    info.add_row("Details fetched", fmt_time(offer.details_fetched_at))
    if offer.params:
        info.add_row("Params", Text("; ".join(f"{k}={v}" for k, v in offer.params)))
    parts: list[RenderableType] = [Panel(info, title=f"Offer {offer.id}")]
    if offer.description:
        text, _ = prepare_description(offer.description, 2000)
        parts.append(Panel(Text(text), title="Description"))

    if extraction is None:
        parts.append(Text("No extraction yet.", style="dim"))
    else:
        grid = Table(title=f"Latest extraction: {extraction.category}")
        grid.add_column("Attribute")
        grid.add_column("Value")
        for key, value in extraction.attributes.items():
            grid.add_row(Text(key), Text("-" if value is None else str(value)))
        prov = extraction.provenance
        grid.caption = escape(
            f"model {prov.model}, prompt {prov.prompt_version}, schema v{prov.schema_version}, "
            f"at {fmt_time(prov.extracted_at)}"
        )
        parts.append(grid)

    if links:
        link_table = Table(title="Found by searches")
        for column in ("Search", "First seen", "Last seen", "Derived", "Override", "Effective"):
            link_table.add_column(column)
        for link in links:
            link_table.add_row(
                str(link.search),
                fmt_time(link.first_seen_at),
                fmt_time(link.last_seen_at),
                relevance_text(link.derived_relevance),
                relevance_text(link.relevance_override),
                relevance_text(link.is_relevant),
            )
        parts.append(link_table)

    history = Table(title="History")
    history.add_column("When")
    history.add_column("Changes", overflow="fold")
    for snapshot in snapshots:
        history.add_row(
            Text(fmt_time(snapshot.observed_at)),
            Text("; ".join(map(_change_text, snapshot.changes))),
        )
    parts.append(history if snapshots else Text("No recorded changes.", style="dim"))
    return Group(*parts)

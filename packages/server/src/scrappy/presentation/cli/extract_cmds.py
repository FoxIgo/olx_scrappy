"""``scrappy extract``: the reconciling extractor from the command line (ADR 0010).

* ``scrappy extract``: show the backlog (the worker's extractor loop processes it).
* ``scrappy extract --inline [--profile NAME] [--no-wait]``: process it in this process.
* ``scrappy extract status`` / ``profiles [--probe]`` / ``force`` / ``requeue`` (alias).
"""

from __future__ import annotations

import re
from typing import Annotated

import typer
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from scrappy.application.errors import InvalidRequestError
from scrappy.application.use_cases.extraction import (
    ExtractionStatusReport,
    PollReport,
    ProvenanceFilter,
    ReconcileReport,
)
from scrappy.domain.category import CategoryName
from scrappy.domain.search import SearchName
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.render import fmt_time, stdout
from scrappy.presentation.services import Services
from scrappy.presentation.worker import ExtractorStats, extract_until_idle

extract_app = typer.Typer(
    help="LLM extraction: backlog, profiles, forced re-extraction (ADR 0010).",
)

_WHERE = re.compile(r"^\s*([a-z_]+)\s*(!=|=|~)\s*(.*?)\s*$")


def parse_where(expression: str) -> ProvenanceFilter:
    match = _WHERE.match(expression)
    if match is None or not match[3]:
        raise InvalidRequestError(
            f"invalid --where {expression!r}; use FIELD=VALUE, FIELD!=VALUE or FIELD~TEXT "
            "(fields: model, profile, provider, prompt_version, category)"
        )
    return ProvenanceFilter(match[1], match[2], match[3])


def _check_profile(app: Services, profile: str | None) -> None:
    if profile is not None and profile not in app.profiles.names():
        known = ", ".join(app.profiles.names())
        raise InvalidRequestError(f"unknown extraction profile {profile} (known: {known})")


# ---------------------------------------------------------------------------- rendering


def _summary(report: ExtractionStatusReport, source: str) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_row("Backlog", f"{report.backlog} offer(s) waiting for extraction")
    grid.add_row("Open batches", str(len(report.open_batches)))
    grid.add_row("Parked", f"{len(report.parked)} offer(s) after repeated failures")
    grid.add_row("Profiles from", source)
    return grid


def _batches_table(report: ExtractionStatusReport) -> Table | None:
    batches = report.open_batches + report.recent_batches
    if not batches:
        return None
    table = Table(title="Batches (open, then recent)")
    for column in ("Batch", "Profile", "Status", "Items", "Created", "Result", "Tokens", "Cost"):
        table.add_column(column)
    for batch in batches:
        cost = batch.usage.cost_usd
        table.add_row(
            batch.id,
            batch.profile,
            batch.status.value,
            str(len(batch.items)),
            fmt_time(batch.created_at),
            "-"
            if batch.is_open
            else f"{batch.succeeded} ok / {batch.failed} failed / {batch.stale} stale",
            str(batch.usage.total_tokens),
            "-" if cost is None else f"${cost:.4f}",
        )
    return table


def _parked_table(report: ExtractionStatusReport, limit: int = 10) -> Table | None:
    if not report.parked:
        return None
    table = Table(title=f"Parked offers (newest {min(limit, len(report.parked))})")
    for column in ("Offer", "Attempts", "Since", "Last error"):
        table.add_column(column, overflow="fold")
    for state in report.parked[:limit]:
        table.add_row(
            str(state.offer_id),
            str(state.attempts),
            fmt_time(state.updated_at),
            Text(state.last_error or "-"),
        )
    return table


def _profiles_table(report: ExtractionStatusReport, *, live: bool) -> Table:
    table = Table(title="Extraction profiles")
    columns = ["Profile", "Pool", "Provider", "Model", "Mode", "Output"]
    columns += ["Conc.", "Rate", "Today", "Batch"]
    columns.append("Health" if live else "State")
    for column in columns:
        table.add_column(column, overflow="fold")
    for view in report.profiles:
        profile, caps = view.profile, view.profile.capabilities
        output = caps.structured_output.value
        if view.health is not None and view.health.effective_structured_output is not None:
            output = f"{output} -> {view.health.effective_structured_output.value}"
        rate = "-" if caps.rate_limit_per_minute is None else f"{caps.rate_limit_per_minute:g}/min"
        today = str(view.quota_status.requests_on(report.at, caps.quota_tz))
        if caps.daily_limit is not None:
            today += f"/{caps.daily_limit}"
        if caps.quota_group is not None:
            today += f" ({caps.quota_group})"
        if view.health is not None:
            state = Text(
                ("ok: " if view.health.ok else "UNAVAILABLE: ") + view.health.detail,
                style="green" if view.health.ok else "red",
            )
        elif view.blocked:
            why = view.status.reason if view.status.is_blocked(report.at) else None
            why = why or view.quota_status.reason or "daily limit"
            state = Text(f"blocked: {why}", style="yellow")
        else:
            state = Text("ready")
        table.add_row(
            profile.name,
            "lane" if view.in_pool else "-",
            profile.provider,
            profile.model,
            profile.mode.value,
            output,
            str(caps.concurrency),
            rate,
            today,
            "yes" if caps.supports_batch else "no",
            state,
        )
    return table


def status_view(
    report: ExtractionStatusReport, source: str, *, live: bool = False
) -> RenderableType:
    parts: list[RenderableType] = [_summary(report, source)]
    for table in (_batches_table(report), _parked_table(report)):
        if table is not None:
            parts.append(table)
    parts.append(_profiles_table(report, live=live))
    return Group(*parts)


def _stats_line(stats: ExtractorStats) -> str:
    parts = [f"stored {stats.stored}", f"failed {stats.failed}"]
    if stats.batches_submitted or stats.batches_finished:
        parts.append(f"batches submitted {stats.batches_submitted}")
        parts.append(f"finished {stats.batches_finished}")
    line = "Extraction: " + ", ".join(parts) + "."
    if stats.stored_by_profile:
        lanes = ", ".join(f"{name} {count}" for name, count in stats.stored_by_profile.items())
        line += f" Per lane: {lanes}."
    return line


# ---------------------------------------------------------------------------- commands


@extract_app.callback(invoke_without_command=True)
def extract(
    ctx: typer.Context,
    inline: Annotated[
        bool, typer.Option("--inline", help="Process the backlog in this process.")
    ] = False,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Use only this profile (not the whole pool)."),
    ] = None,
    no_wait: Annotated[
        bool,
        typer.Option("--no-wait", help="With batches: return once they are submitted."),
    ] = False,
    max_offers: Annotated[
        int | None,
        typer.Option("--max", min=1, help="With --inline: claim at most this many offers."),
    ] = None,
) -> None:
    """Show the extraction backlog, or process it with --inline."""
    if ctx.invoked_subcommand is not None:
        return

    async def go(app: Services) -> None:
        console = stdout()
        _check_profile(app, profile)
        if not inline:
            report = await app.extraction_status()
            console.print(status_view(report, app.extraction_config_source))
            if report.backlog:
                console.print(
                    "The worker's extractor loop processes the backlog (`scrappy worker`); "
                    "`scrappy extract --inline` does it here."
                )
            return
        with console.status("Extracting...") as status:

            def on_tick(report: ReconcileReport | PollReport) -> None:
                if isinstance(report, ReconcileReport) and report.profile:
                    status.update(
                        f"Extracting with {report.profile} ({report.mode})... "
                        f"stored {report.stored}, failed {report.failed}"
                    )
                elif isinstance(report, PollReport):
                    status.update(f"Waiting for batches... {report.running} running")

            stats = await extract_until_idle(
                app, profile=profile, wait=not no_wait, on_tick=on_tick, limit=max_offers
            )
        console.print(_stats_line(stats))
        for note in stats.notes:
            console.print(Text(f"note: {note}", style="yellow"))
        if stats.unavailable:
            console.print(
                "[yellow]No extraction profile is available; see `scrappy extract profiles`.[/]"
            )
        report = await app.extraction_status()
        console.print(status_view(report, app.extraction_config_source))

    execute(ctx, go)


@extract_app.command("status")
def status(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Option("--search", help="Also count this search.")] = None,
) -> None:
    """Backlog, open and recent batches, parked offers, profiles."""

    async def go(app: Services) -> None:
        report = await app.extraction_status(search=SearchName(search) if search else None)
        console = stdout()
        console.print(status_view(report, app.extraction_config_source))
        if search is not None:
            console.print(f"Backlog for {search}: {report.search_backlog} offer(s)")

    execute(ctx, go)


@extract_app.command("profiles")
def profiles(
    ctx: typer.Context,
    probe: Annotated[
        bool,
        typer.Option(
            "--probe",
            help="Send one tiny structured request per profile to find the usable "
            "structured-output level (skipped for profiles with probe: false).",
        ),
    ] = False,
) -> None:
    """List profiles with live health checks (endpoint, model, key) and capabilities."""

    async def go(app: Services) -> None:
        report = await app.extraction_status(check_health=True, probe=probe)
        stdout().print(_profiles_table(report, live=True))
        stdout().print(f"Profiles from {app.extraction_config_source}.")

    execute(ctx, go)


@extract_app.command("force")
def force(
    ctx: typer.Context,
    category: Annotated[
        str | None, typer.Option("--category", help="Only offers classified in this category.")
    ] = None,
    where: Annotated[
        list[str] | None,
        typer.Option(
            "--where",
            "-w",
            help="Provenance filter, repeatable: model=..., profile!=..., provider=..., "
            "prompt_version=..., category=...; ~ is a substring match.",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Re-extract with this profile only."),
    ] = None,
    parked: Annotated[
        bool, typer.Option("--parked", help="Retry parked offers (reset their failures).")
    ] = False,
) -> None:
    """Re-extract offers even if up to date (better model, prompt test), or retry parked ones."""

    async def go(app: Services) -> None:
        filters = [parse_where(w) for w in where or []]
        result = await app.force_reextract(
            category=CategoryName(category) if category else None,
            where=filters,
            profile=profile,
            parked_only=parked,
        )
        what = "retry" if parked else "re-extraction"
        stdout().print(
            f"Marked {result.marked} offer(s) for {what}"
            + (f" with profile {profile}" if profile else "")
            + ". The extractor loop picks them up "
            "(`scrappy worker`, or `scrappy extract --inline`)."
        )

    execute(ctx, go)


@extract_app.command("requeue", hidden=True)
def requeue(
    ctx: typer.Context,
    category: Annotated[str | None, typer.Option("--category")] = None,
    force_: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Deprecated: use `scrappy extract force` (there is no queue any more)."""

    async def go(app: Services) -> None:
        console = stdout()
        if force_:
            result = await app.force_reextract(
                category=CategoryName(category) if category else None
            )
            console.print(
                f"`extract requeue --force` is now `extract force`: marked {result.marked} "
                "offer(s) for re-extraction."
            )
            return
        backlog = await app.extraction_status.backlog()
        console.print(
            "Nothing to queue: the extraction backlog is computed automatically "
            f"({backlog} offer(s) waiting). Use `scrappy extract force` to redo up-to-date offers."
        )

    execute(ctx, go)

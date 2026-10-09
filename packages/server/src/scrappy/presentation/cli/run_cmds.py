"""``scrappy run``, ``runs list|show``, ``resume``."""

from __future__ import annotations

from collections import Counter
from typing import Annotated

import typer

from scrappy.application.errors import NotFoundError
from scrappy.application.jobs.dispatcher import DispatchReport
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SearchName
from scrappy.domain.shared import RunId
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.render import run_report, runs_table, stdout
from scrappy.presentation.services import Services
from scrappy.presentation.worker import run_until_idle, wait_for_run

runs_app = typer.Typer(help="Inspect runs.", no_args_is_help=True)


async def _print_report(app: Services, run_id: RunId) -> ScrapeRun:
    async with app.uow() as uow:
        run = await uow.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        jobs = await uow.jobs.list_for_run(run_id)
    backlog = await app.extraction_status.backlog(run.search)
    stdout().print(run_report(run, jobs, extraction_backlog=backlog))
    return run


async def _drive_inline(app: Services, run_id: RunId) -> None:
    console = stdout()
    done: Counter[str] = Counter()

    with console.status("Running jobs in-process...") as status:

        def on_dispatch(report: DispatchReport) -> None:
            done[report.job.type.value] += 1
            summary = ", ".join(f"{name}={n}" for name, n in sorted(done.items()))
            status.update(f"Running jobs in-process... {summary}")

        await run_until_idle(app, run_id, on_dispatch=on_dispatch)


async def _drive_wait(app: Services, run_id: RunId) -> None:
    with stdout().status("Waiting for the worker...") as status:

        def on_poll(run: ScrapeRun, unfinished: int) -> None:
            status.update(f"Waiting for the worker... {unfinished} job(s) unfinished")

        await wait_for_run(app, run_id, on_poll=on_poll)


def run(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Saved search name.")],
    inline: Annotated[
        bool,
        typer.Option("--inline", help="Scrape in this process (extraction is not part of a run)."),
    ] = False,
    wait: Annotated[
        bool, typer.Option("--wait", help="Wait for a separate worker to finish the run.")
    ] = False,
) -> None:
    """Start a run of a saved search (idempotent while one is running).

    A run is scraping only. Its offers enter the extraction backlog, which the worker's
    extractor loop (or `scrappy extract --inline`) processes."""

    async def go(app: Services) -> None:
        console = stdout()
        result = await app.start_run(SearchName(name))
        run_id = result.run.id
        if result.created:
            console.print(f"Started run [bold]{run_id}[/] for {name}.")
        else:
            console.print(f"Search {name} already has a running run: [bold]{run_id}[/].")
        if inline:
            await _drive_inline(app, run_id)
        elif wait:
            await _drive_wait(app, run_id)
        else:
            console.print(
                f"A worker will execute it (`scrappy worker`); follow with "
                f"`scrappy runs show {run_id}`."
            )
            return
        finished = await _print_report(app, run_id)
        if finished.is_running:
            console.print(
                f"[yellow]Run is still running (interrupted?).[/] Continue with "
                f"`scrappy run {name} --inline`."
            )

    execute(ctx, go)


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Only this saved search.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1)] = 20,
) -> None:
    """List recent runs (newest first)."""

    async def go(app: Services) -> None:
        async with app.uow() as uow:
            if name is not None:
                if await uow.searches.get(SearchName(name)) is None:
                    raise NotFoundError(f"search {name} not found")
                names = [SearchName(name)]
            else:
                names = [s.name for s in await uow.searches.list_all()]
            runs: list[ScrapeRun] = []
            for search_name in names:
                runs.extend(await uow.runs.list_for_search(search_name, limit=limit))
        runs.sort(key=lambda r: r.started_at, reverse=True)
        console = stdout()
        if runs:
            console.print(runs_table(runs[:limit]))
        else:
            console.print("No runs yet.")

    execute(ctx, go)


@runs_app.command("show")
def runs_show(ctx: typer.Context, run_id: str) -> None:
    """Show the run report: status, phases, fill rates, coverage, LLM usage, errors."""

    async def go(app: Services) -> None:
        await _print_report(app, RunId(run_id))

    execute(ctx, go)


def resume(
    ctx: typer.Context,
    run_id: str,
    inline: Annotated[
        bool, typer.Option("--inline", help="Run the re-queued jobs in this process.")
    ] = False,
) -> None:
    """Resume a run: re-queue its failed jobs."""

    async def go(app: Services) -> None:
        console = stdout()
        result = await app.resume_run(RunId(run_id))
        console.print(f"Re-queued {result.requeued} job(s) of run [bold]{run_id}[/].")
        if inline and result.run.is_running:
            await _drive_inline(app, result.run.id)
        await _print_report(app, result.run.id)

    execute(ctx, go)

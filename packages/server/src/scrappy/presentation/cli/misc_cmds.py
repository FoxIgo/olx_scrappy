"""``scrappy extract requeue``, ``worker``, ``db upgrade``."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Annotated

import typer

from scrappy.domain.category import CategoryName
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.render import stdout
from scrappy.presentation.services import Services
from scrappy.presentation.worker import run_worker

extract_app = typer.Typer(help="Extraction maintenance.", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)


@extract_app.command("requeue")
def requeue(
    ctx: typer.Context,
    category: Annotated[
        str | None, typer.Option("--category", help="Only offers classified in this category.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-extract even if up to date (e.g. new model).")
    ] = False,
) -> None:
    """Queue extraction jobs from stored data (no scraping). A worker executes them."""

    async def go(app: Services) -> None:
        result = await app.requeue_extractions(
            category=CategoryName(category) if category else None, force=force
        )
        console = stdout()
        console.print(
            f"Considered {result.considered}, queued {result.enqueued}, "
            f"already queued {result.already_queued}."
        )
        if result.enqueued:
            console.print("Run `scrappy worker` to process them.")
        if not app.has_extractor:
            console.print("[yellow]OPENROUTER_API_KEY is not set: these jobs will fail.[/]")

    execute(ctx, go)


@db_app.command("upgrade")
def upgrade(ctx: typer.Context) -> None:
    """Migrate the database to the latest schema (also done on every start)."""

    async def go(app: Services) -> None:
        stdout().print(f"Database is at the latest schema ({app.data_location}).")

    execute(ctx, go)


def worker(ctx: typer.Context) -> None:
    """Run the long-lived worker: process queued jobs until stopped (Ctrl+C / SIGTERM)."""

    async def go(app: Services) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # Not supported on Windows: there Ctrl+C cancels the main task, which
            # run_worker turns into a graceful stop (see worker/loop.py).
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(sig, stop.set)
        await run_worker(app, stop)

    execute(ctx, go, long_running=True)

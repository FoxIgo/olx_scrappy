"""``scrappy worker``, ``db upgrade``."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Annotated

import typer

from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.render import stdout
from scrappy.presentation.services import Services
from scrappy.presentation.worker import WorkerRole, run_worker

db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)


@db_app.command("upgrade")
def upgrade(ctx: typer.Context) -> None:
    """Migrate the database to the latest schema (also done on every start)."""

    async def go(app: Services) -> None:
        stdout().print(f"Database is at the latest schema ({app.data_location}).")

    execute(ctx, go)


def worker(
    ctx: typer.Context,
    only: Annotated[
        WorkerRole | None,
        typer.Option(
            "--only",
            help="Run only the scraper loop (jobs) or only the extractor loop (LLM backlog).",
        ),
    ] = None,
) -> None:
    """Run the long-lived worker: scraper and extractor loops until stopped (Ctrl+C/SIGTERM)."""

    async def go(app: Services) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # Not supported on Windows: there Ctrl+C cancels the main task, which
            # run_worker turns into a graceful stop (see worker/loop.py).
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(sig, stop.set)
        await run_worker(app, stop, only=only)

    execute(ctx, go, long_running=True)

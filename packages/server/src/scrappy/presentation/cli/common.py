"""Shared plumbing for commands: open the app, run a coroutine, map errors to exit codes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import typer

from scrappy.presentation.cli.render import error_line
from scrappy.presentation.logging import configure_logging
from scrappy.presentation.services import CliContext, Services


def cli_context(ctx: typer.Context) -> CliContext:
    obj = ctx.find_root().obj
    if not isinstance(obj, CliContext):
        error_line("the application is not configured (start the CLI through `scrappy`)")
        raise typer.Exit(1)
    return obj


def execute[T](
    ctx: typer.Context,
    action: Callable[[Services], Awaitable[T]],
    *,
    long_running: bool = False,
) -> T:
    """Open the application, run ``action`` in a fresh event loop, always close it.

    Expected errors (application, domain and config errors) become a red one-line message
    and exit code 1; ``--debug`` lets them propagate with a traceback. Long-running commands
    (the worker) log at the configured level; the others stay quiet (WARNING, DEBUG with
    ``--debug``).
    """
    context = cli_context(ctx)

    async def main() -> T:
        app = await context.open_app()
        try:
            if long_running:
                configure_logging(app.log_level)
            else:
                configure_logging("DEBUG" if context.debug else "WARNING")
            return await action(app)
        finally:
            await app.aclose()

    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        error_line("interrupted")
        raise typer.Exit(130) from None
    except context.expected_errors as error:
        if context.debug:
            raise
        error_line(str(error))
        raise typer.Exit(1) from None

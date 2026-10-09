"""Typer CLI entry point (`scrappy`). Commands are thin: parse -> use case -> render.

The application (composition root) is injected through the Typer context object
(:class:`~scrappy.presentation.services.CliContext`) by ``scrappy.main:cli``; tests inject
their own.
"""

from importlib.metadata import version as _pkg_version
from typing import Annotated

import typer

from scrappy.presentation.cli.misc_cmds import db_app, extract_app, worker
from scrappy.presentation.cli.offers_cmds import offers_app
from scrappy.presentation.cli.run_cmds import resume, run, runs_app
from scrappy.presentation.cli.search_cmds import search_app
from scrappy.presentation.services import CliContext

app = typer.Typer(help="olx_scrappy command line interface.", no_args_is_help=True)
app.add_typer(search_app, name="search")
app.add_typer(runs_app, name="runs")
app.add_typer(offers_app, name="offers")
app.add_typer(extract_app, name="extract")
app.add_typer(db_app, name="db")
app.command("run")(run)
app.command("resume")(resume)
app.command("worker")(worker)


@app.callback()
def main(
    ctx: typer.Context,
    debug: Annotated[bool, typer.Option("--debug", help="Show tracebacks and debug logs.")] = False,
) -> None:
    """olx_scrappy command line interface."""
    if debug and isinstance(ctx.obj, CliContext):
        ctx.obj.debug = True


@app.command()
def version() -> None:
    """Print the installed scrappy version."""
    typer.echo(_pkg_version("scrappy"))

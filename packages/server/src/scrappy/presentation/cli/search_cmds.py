"""``scrappy search add|list|show``."""

from __future__ import annotations

from typing import Annotated

import typer

from scrappy.application.errors import NotFoundError
from scrappy.domain.category import CategoryName
from scrappy.domain.search import SearchName
from scrappy.domain.shared import SourceId
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.render import search_detail, searches_table, stdout
from scrappy.presentation.services import Services

search_app = typer.Typer(help="Manage saved searches.", no_args_is_help=True)


@search_app.command("add")
def add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Unique slug, e.g. gtx-laptops.")],
    url: Annotated[str, typer.Argument(help="Search URL copied from the browser.")],
    category: Annotated[str, typer.Option("--category", "-c", help="Target category.")],
    source: Annotated[str, typer.Option("--source", help="Source recipe id.")] = "olx_pl",
) -> None:
    """Save a named search. Unsupported URLs are rejected right away."""

    async def go(app: Services) -> None:
        result = await app.add_search(
            SearchName(name), SourceId(source), url, CategoryName(category)
        )
        verb = "Added" if result.created else "Already exists (identical):"
        stdout().print(f"{verb} search [bold]{result.search.name}[/] ({source}, {category})")

    execute(ctx, go)


@search_app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List saved searches."""

    async def go(app: Services) -> None:
        async with app.uow() as uow:
            searches = await uow.searches.list_all()
        console = stdout()
        if searches:
            console.print(searches_table(searches))
        else:
            console.print("No saved searches. Add one with `scrappy search add`.")

    execute(ctx, go)


@search_app.command("show")
def show(ctx: typer.Context, name: str) -> None:
    """Show a saved search and its recent runs."""

    async def go(app: Services) -> None:
        search_name = SearchName(name)
        async with app.uow() as uow:
            search = await uow.searches.get(search_name)
            if search is None:
                raise NotFoundError(f"search {name} not found")
            runs = await uow.runs.list_for_search(search_name, limit=5)
        stdout().print(search_detail(search, runs))

    execute(ctx, go)

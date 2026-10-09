"""``scrappy components resolve|status|alias add``: link offers' raw CPU/GPU text to
canonical components (ADR 0011 section 3). Every command prints one JSON document."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

import typer

from scrappy.application.errors import InvalidRequestError
from scrappy.domain.component import ComponentKind
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.q_render import dumps
from scrappy.presentation.services import Services

components_app = typer.Typer(
    help="Link offers' raw CPU/GPU text to canonical components.", no_args_is_help=True
)
alias_app = typer.Typer(help="Manual aliases for texts the matcher cannot resolve.")
components_app.add_typer(alias_app, name="alias", no_args_is_help=True)


def _echo(document: dict[str, object]) -> None:
    typer.echo(dumps(document, pretty=True))


def _kind(value: str) -> ComponentKind:
    try:
        return ComponentKind(value.lower())
    except ValueError:
        raise InvalidRequestError(f"unknown kind {value!r}; expected: cpu, gpu") from None


@components_app.command("resolve")
def resolve_cmd(
    ctx: typer.Context,
    max_items: Annotated[
        int | None,
        typer.Option("--max", min=1, help="Resolve at most this many raw texts (default: all)."),
    ] = None,
) -> None:
    """Resolve the backlog: raw texts without an up-to-date link."""

    async def go(app: Services) -> None:
        report = await app.resolve_components(max_items)
        _echo({"ok": True, "command": "components resolve", **asdict(report)})

    execute(ctx, go)


@components_app.command("status")
def status_cmd(
    ctx: typer.Context,
    top: Annotated[
        int, typer.Option("--top", "-n", min=1, help="Most frequent unresolved texts to list.")
    ] = 30,
) -> None:
    """Links by kind and method, the backlog and the top unresolved raw texts."""

    async def go(app: Services) -> None:
        report = await app.component_resolution_status(top=top)
        _echo({"ok": True, "command": "components status", **asdict(report)})

    execute(ctx, go)


@alias_app.command("add")
def alias_add_cmd(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="cpu or gpu.")],
    raw_text: Annotated[str, typer.Argument(help="The text as written in offers, e.g. 'iris xe'.")],
    component_id: Annotated[str, typer.Argument(help="Target id, e.g. gpu:rtx-4060-laptop.")],
) -> None:
    """Make RAW_TEXT mean COMPONENT_ID; affected offers are re-resolved by the next resolve."""

    async def go(app: Services) -> None:
        added = await app.add_component_alias(_kind(kind), raw_text, component_id)
        _echo({"ok": True, "command": "components alias add", **asdict(added)})

    execute(ctx, go)

"""``scrappy benchmarks import|list``: CPU/GPU components and their benchmark scores
(ADR 0011). Both commands print one JSON document on stdout."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.components import ComponentWithBenchmarks
from scrappy.domain.component import ComponentKind
from scrappy.presentation.cli.common import execute
from scrappy.presentation.cli.q_render import dumps
from scrappy.presentation.services import Services

benchmarks_app = typer.Typer(
    help="CPU/GPU components and their benchmark scores (Blender Open Data).",
    no_args_is_help=True,
)


def _echo(document: dict[str, object]) -> None:
    typer.echo(dumps(document, pretty=True))


def _kind(value: str | None) -> ComponentKind | None:
    if value is None:
        return None
    try:
        return ComponentKind(value.lower())
    except ValueError:
        raise InvalidRequestError(f"unknown kind {value!r}; expected: cpu, gpu") from None


@benchmarks_app.command("import")
def import_cmd(
    ctx: typer.Context,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file", help="Blender Open Data snapshot: the .zip, the .jsonl or a folder."
        ),
    ] = None,
    download: Annotated[
        bool, typer.Option("--download", help="Download the latest snapshot first (~100 MB).")
    ] = False,
) -> None:
    """Import benchmark scores; re-running updates scores and adds new components."""

    async def go(app: Services) -> None:
        report = await app.import_benchmarks(file, download=download)
        _echo({"ok": True, "command": "benchmarks import", **asdict(report)})

    execute(ctx, go)


@benchmarks_app.command("list")
def list_cmd(
    ctx: typer.Context,
    kind: Annotated[str | None, typer.Option("--kind", help="cpu or gpu.")] = None,
    search: Annotated[
        str | None, typer.Option("--search", help="Part of a name, e.g. 'rtx 4060'.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="Maximum rows.")] = 50,
) -> None:
    """List components with their scores, best score first."""

    async def go(app: Services) -> None:
        found = await app.list_components(kind=_kind(kind), search=search, limit=limit)
        _echo(
            {
                "ok": True,
                "command": "benchmarks list",
                "params": {"kind": kind, "search": search, "limit": limit},
                "count": len(found),
                "data": [_row(item) for item in found],
            }
        )

    execute(ctx, go)


def _row(item: ComponentWithBenchmarks) -> dict[str, object]:
    c = item.component
    return {
        "id": c.id,
        "kind": c.kind,
        "name": c.name,
        "slug": c.slug,
        "vendor": c.vendor,
        "family": c.family,
        "generation": c.generation,
        "segment": c.segment,
        "benchmarks": [
            {
                "source": b.source,
                "metric": b.metric,
                "score": b.score,
                "samples": b.samples,
                "fetched_at": b.fetched_at,
            }
            for b in item.benchmarks
        ],
    }

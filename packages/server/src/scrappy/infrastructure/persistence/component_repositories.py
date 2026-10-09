"""SQL repository of CPU/GPU components, aliases and benchmark scores (ADR 0011).
Reference behaviour: ``tests/unit/fakes/store.py``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from scrappy.application.ports.components import ComponentWithBenchmarks
from scrappy.domain.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    Segment,
    component_slug,
)
from scrappy.infrastructure.persistence._sql import insert_ignore, upsert
from scrappy.infrastructure.persistence.tables import (
    component_aliases,
    component_benchmarks,
)
from scrappy.infrastructure.persistence.tables import (
    components as components_table,
)


def _component(r: Mapping[Any, Any]) -> Component:
    return Component(
        kind=ComponentKind(r["kind"]),
        slug=r["slug"],
        name=r["name"],
        vendor=r["vendor"],
        family=r["family"],
        generation=r["generation"],
        segment=Segment(r["segment"]),
    )


class SqlComponentRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def add_missing(self, components: Sequence[Component]) -> int:
        added = 0
        for c in components:
            values = {
                "id": c.id,
                "kind": c.kind.value,
                "slug": c.slug,
                "name": c.name,
                "vendor": c.vendor,
                "family": c.family,
                "generation": c.generation,
                "segment": c.segment.value,
            }
            added += await insert_ignore(self._conn, components_table, values, ("id",))
        return added

    async def add_aliases(self, aliases: Sequence[ComponentAlias]) -> int:
        added = 0
        for a in aliases:
            values = {"kind": a.kind.value, "alias": a.alias, "component_id": a.component_id}
            added += await insert_ignore(self._conn, component_aliases, values, ("kind", "alias"))
        return added

    async def save_benchmarks(self, benchmarks: Sequence[Benchmark]) -> None:
        for b in benchmarks:
            values = {
                "component_id": b.component_id,
                "source": b.source,
                "metric": b.metric,
                "score": b.score,
                "samples": b.samples,
                "fetched_at": b.fetched_at,
            }
            await upsert(
                self._conn, component_benchmarks, values, ("component_id", "source", "metric")
            )

    async def get(self, component_id: str) -> Component | None:
        row = (
            (
                await self._conn.execute(
                    select(components_table).where(components_table.c.id == component_id)
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _component(row)

    async def find(
        self, *, kind: ComponentKind | None = None, search: str | None = None
    ) -> list[ComponentWithBenchmarks]:
        stmt = select(components_table)
        if kind is not None:
            stmt = stmt.where(components_table.c.kind == kind.value)
        if search:
            conditions = [components_table.c.name.icontains(search, autoescape=True)]
            for slug_kind in ("gpu", "cpu"):
                slug = component_slug(search, slug_kind)
                if slug:
                    conditions.append(components_table.c.slug.contains(slug, autoescape=True))
            stmt = stmt.where(or_(*conditions))
        found = [_component(row) for row in (await self._conn.execute(stmt)).mappings()]
        ids = {c.id for c in found}
        by_component: dict[str, list[Benchmark]] = {}
        for row in (await self._conn.execute(select(component_benchmarks))).mappings():
            if row["component_id"] in ids:
                by_component.setdefault(row["component_id"], []).append(
                    Benchmark(
                        row["component_id"],
                        row["source"],
                        row["metric"],
                        row["score"],
                        row["samples"],
                        row["fetched_at"],
                    )
                )
        result = [ComponentWithBenchmarks(c, tuple(by_component.get(c.id, ()))) for c in found]
        result.sort(key=lambda c: c.sort_key)
        return result

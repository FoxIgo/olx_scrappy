"""SQL repository of CPU/GPU components, aliases and benchmark scores (ADR 0011).
Reference behaviour: ``tests/unit/fakes/store.py``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from scrappy.application.ports.components import (
    ComponentWithBenchmarks,
    ResolutionTask,
    UnresolvedText,
)
from scrappy.domain.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    OfferComponentLink,
    ResolutionMethod,
    Segment,
    component_slug,
)
from scrappy.domain.offer import OfferId
from scrappy.domain.shared import SourceId
from scrappy.infrastructure.persistence._sql import (
    chunks,
    insert_ignore,
    json_attribute,
    upsert,
)
from scrappy.infrastructure.persistence.repositories import latest_extraction_cte
from scrappy.infrastructure.persistence.tables import (
    component_aliases,
    component_benchmarks,
    offer_components,
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

    async def list_components(self) -> list[Component]:
        rows = (await self._conn.execute(select(components_table))).mappings()
        return [_component(row) for row in rows]

    async def list_aliases(self) -> list[ComponentAlias]:
        rows = (await self._conn.execute(select(component_aliases))).mappings()
        return [
            ComponentAlias(ComponentKind(r["kind"]), r["alias"], r["component_id"]) for r in rows
        ]

    async def save_alias(self, alias: ComponentAlias) -> None:
        values = {
            "kind": alias.kind.value,
            "alias": alias.alias,
            "component_id": alias.component_id,
        }
        await upsert(self._conn, component_aliases, values, ("kind", "alias"))

    # ------------------------------------------------------------------ offer links

    def _backlog_stmt(self, kind: ComponentKind, resolver_version: int) -> Any:
        latest = latest_extraction_cte()
        dialect = self._conn.dialect.name
        raw = json_attribute(latest.c.attributes, kind.value, dialect)
        vram = json_attribute(latest.c.attributes, "vram_gb", dialect)
        oc = offer_components.c
        joined: Any = latest.outerjoin(
            offer_components,
            and_(
                oc.source == latest.c.source,
                oc.external_id == latest.c.external_id,
                oc.kind == kind.value,
            ),
        )
        return (
            select(
                latest.c.source,
                latest.c.external_id,
                latest.c.category,
                raw.label("raw"),
                vram.label("vram"),
            )
            .select_from(joined)
            .where(
                raw.is_not(None),
                func.trim(raw) != "",
                or_(
                    oc.source.is_(None),
                    oc.raw_text != raw,
                    oc.resolver_version < resolver_version,
                ),
            )
            .order_by(latest.c.extracted_at.desc(), latest.c.source, latest.c.external_id)
        )

    async def resolution_backlog(
        self, resolver_version: int, *, limit: int | None = None
    ) -> list[ResolutionTask]:
        tasks: list[ResolutionTask] = []
        for kind in (ComponentKind.GPU, ComponentKind.CPU):
            stmt = self._backlog_stmt(kind, resolver_version)
            if limit is not None:
                stmt = stmt.limit(limit - len(tasks))
            for row in (await self._conn.execute(stmt)).mappings():
                vram = row["vram"]
                tasks.append(
                    ResolutionTask(
                        OfferId(SourceId(row["source"]), row["external_id"]),
                        row["category"],
                        kind,
                        str(row["raw"]),
                        int(vram) if isinstance(vram, int | float) else None,
                    )
                )
            if limit is not None and len(tasks) >= limit:
                break
        return tasks

    async def count_resolution_backlog(self, resolver_version: int) -> int:
        total = 0
        for kind in (ComponentKind.GPU, ComponentKind.CPU):
            sub = self._backlog_stmt(kind, resolver_version).order_by(None).subquery()
            total += (await self._conn.execute(select(func.count()).select_from(sub))).scalar_one()
        return total

    async def save_links(self, links: Sequence[OfferComponentLink]) -> None:
        for link in links:
            values = {
                "source": link.offer_id.source.value,
                "external_id": link.offer_id.external_id,
                "kind": link.kind.value,
                "component_id": link.resolution.component_id,
                "raw_text": link.raw_text,
                "confidence": link.resolution.confidence,
                "method": link.resolution.method.value,
                "resolver_version": link.resolver_version,
                "resolved_at": link.resolved_at,
            }
            await upsert(self._conn, offer_components, values, ("source", "external_id", "kind"))

    async def linked_raw_texts(self, kind: ComponentKind) -> list[str]:
        stmt = select(offer_components.c.raw_text).where(offer_components.c.kind == kind.value)
        return list((await self._conn.execute(stmt.distinct())).scalars())

    async def mark_links_stale(self, kind: ComponentKind, raw_texts: Sequence[str]) -> int:
        changed = 0
        for part in chunks(list(raw_texts)):
            stmt = (
                update(offer_components)
                .where(offer_components.c.kind == kind.value, offer_components.c.raw_text.in_(part))
                .values(resolver_version=0)
            )
            changed += (await self._conn.execute(stmt)).rowcount
        return changed

    async def link_counts(self) -> dict[tuple[ComponentKind, ResolutionMethod], int]:
        oc = offer_components.c
        stmt = select(oc.kind, oc.method, func.count()).group_by(oc.kind, oc.method)
        return {
            (ComponentKind(kind), ResolutionMethod(method)): count
            for kind, method, count in await self._conn.execute(stmt)
        }

    async def top_unresolved(self, limit: int) -> list[UnresolvedText]:
        oc = offer_components.c
        text = func.lower(oc.raw_text)
        stmt = (
            select(oc.kind, text, func.count().label("n"))
            .where(oc.method == ResolutionMethod.UNRESOLVED.value)
            .group_by(oc.kind, text)
            .order_by(func.count().desc(), text)
            .limit(limit)
        )
        return [
            UnresolvedText(ComponentKind(kind), raw, count)
            for kind, raw, count in await self._conn.execute(stmt)
        ]

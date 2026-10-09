"""Benchmark use cases: ``ImportBenchmarks`` (idempotent) and ``ListComponents``."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.benchmarks import BenchmarkDownloader, BenchmarkSource
from scrappy.application.ports.components import ComponentWithBenchmarks
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    is_identifying_slug,
)
from scrappy.domain.shared import DomainError


@dataclass(frozen=True, slots=True)
class ImportReport:
    location: str
    entries: int
    components_added: int
    components_total: dict[str, int]
    aliases_added: int
    benchmarks_saved: int
    skipped: int


class ImportBenchmarks:
    """Reads a benchmark snapshot and upserts components, aliases and scores.

    Re-running updates the scores, adds new components and aliases, and never removes or
    renames anything. Aliases are seeded per original device name. Two device names with the
    same slug (e.g. with and without "12th Gen") become one component; if a source reports
    both, the first name is canonical and the larger sample wins.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        source: BenchmarkSource,
        downloader: BenchmarkDownloader,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._source = source
        self._downloader = downloader
        self._clock = clock

    async def __call__(
        self, location: Path | None = None, *, download: bool = False
    ) -> ImportReport:
        if (location is None) == (not download):
            raise InvalidRequestError("give exactly one of a snapshot file or --download")
        path = location
        if download:
            path = await asyncio.to_thread(self._downloader.download)
        assert path is not None
        if not path.exists():
            raise InvalidRequestError(f"snapshot not found: {path}")
        entries = await asyncio.to_thread(self._source.load, path)

        fetched_at = self._clock.now()
        components: dict[str, Component] = {}
        aliases: dict[tuple[ComponentKind, str], ComponentAlias] = {}
        best: dict[tuple[str, str, str], Benchmark] = {}
        skipped = 0
        for entry in entries:
            try:
                component = Component.from_name(entry.kind, entry.device_name)
            except DomainError:
                skipped += 1
                continue
            if not is_identifying_slug(component.slug):
                skipped += 1
                continue
            components.setdefault(component.id, component)
            alias = ComponentAlias.for_name(component, entry.device_name)
            aliases.setdefault((alias.kind, alias.alias), alias)
            key = (component.id, entry.source, entry.metric)
            known = best.get(key)
            if known is None or entry.samples > known.samples:
                best[key] = Benchmark(
                    component.id, entry.source, entry.metric, entry.score, entry.samples, fetched_at
                )

        async with self._uow() as uow:
            added = await uow.components.add_missing(list(components.values()))
            aliases_added = await uow.components.add_aliases(list(aliases.values()))
            await uow.components.save_benchmarks(list(best.values()))
            await uow.commit()
        totals = {kind.value: 0 for kind in ComponentKind}
        for component in components.values():
            totals[component.kind.value] += 1
        return ImportReport(
            location=str(path),
            entries=len(entries),
            components_added=added,
            components_total=totals,
            aliases_added=aliases_added,
            benchmarks_saved=len(best),
            skipped=skipped,
        )


class ListComponents:
    def __init__(self, *, uow: UnitOfWorkFactory) -> None:
        self._uow = uow

    async def __call__(
        self, *, kind: ComponentKind | None = None, search: str | None = None, limit: int = 50
    ) -> list[ComponentWithBenchmarks]:
        async with self._uow() as uow:
            found = await uow.components.find(kind=kind, search=search)
        return found[:limit]

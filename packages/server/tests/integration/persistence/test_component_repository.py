"""SQL component repository: round-trips, idempotent writes, search, migration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from scrappy.application.ports.unit_of_work import UnitOfWork
from scrappy.domain.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    Segment,
)
from tests.integration.persistence.sqlstore import SqlStore

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
LAPTOP = Component.from_name(ComponentKind.GPU, "NVIDIA GeForce RTX 4060 Laptop GPU")
DESKTOP = Component.from_name(ComponentKind.GPU, "NVIDIA GeForce RTX 4060")
CPU = Component.from_name(ComponentKind.CPU, "AMD Ryzen 7 5800H with Radeon Graphics")


def bench(component: Component, score: float, samples: int = 5, metric: str = "spm") -> Benchmark:
    return Benchmark(component.id, "blender_open_data", metric, score, samples, NOW)


async def test_round_trip_and_idempotent_inserts(uow: Callable[[], UnitOfWork]) -> None:
    async with uow() as u:
        assert await u.components.add_missing([LAPTOP, DESKTOP, CPU]) == 3
        alias = ComponentAlias.for_name(LAPTOP, "NVIDIA GeForce RTX 4060 Laptop GPU")
        assert await u.components.add_aliases([alias]) == 1
        await u.components.save_benchmarks([bench(LAPTOP, 345.5, 40)])
        await u.commit()

    async with uow() as u:
        assert await u.components.add_missing([LAPTOP, DESKTOP]) == 0
        assert await u.components.add_aliases([alias]) == 0
        assert await u.components.get(LAPTOP.id) == LAPTOP
        assert (await u.components.get(CPU.id)) == CPU
        assert (await u.components.get("gpu:nope")) is None
        (found,) = await u.components.find(search="laptop")
        assert found.component.segment is Segment.MOBILE
        assert found.benchmarks == (bench(LAPTOP, 345.5, 40),)


async def test_save_benchmarks_upserts_by_component_source_metric(
    uow: Callable[[], UnitOfWork],
) -> None:
    async with uow() as u:
        await u.components.add_missing([LAPTOP])
        await u.components.save_benchmarks(
            [bench(LAPTOP, 100.0, 3), bench(LAPTOP, 7.0, metric="m2")]
        )
        await u.components.save_benchmarks([bench(LAPTOP, 120.0, 9)])
        await u.commit()

    async with uow() as u:
        (found,) = await u.components.find()
        scores = {b.metric: (b.score, b.samples) for b in found.benchmarks}
        assert scores == {"spm": (120.0, 9), "m2": (7.0, 5)}


async def test_find_filters_and_orders_by_best_score(uow: Callable[[], UnitOfWork]) -> None:
    async with uow() as u:
        await u.components.add_missing([LAPTOP, DESKTOP, CPU])
        await u.components.save_benchmarks([bench(LAPTOP, 345.0), bench(DESKTOP, 480.0)])
        await u.commit()

    async with uow() as u:
        everything = await u.components.find()
        assert [c.component.id for c in everything] == [DESKTOP.id, LAPTOP.id, CPU.id]
        gpus = await u.components.find(kind=ComponentKind.GPU)
        assert [c.component.slug for c in gpus] == ["rtx-4060", "rtx-4060-laptop"]
        assert [c.component.slug for c in await u.components.find(search="RTX 4060")] == [
            "rtx-4060",
            "rtx-4060-laptop",
        ]
        assert [c.component.slug for c in await u.components.find(search="ryzen")] == [
            "ryzen-7-5800h"
        ]
        assert await u.components.find(search="100%") == []  # LIKE wildcards are escaped


async def test_unknown_component_id_is_rejected_at_commit(uow: Callable[[], UnitOfWork]) -> None:
    async def save_orphan() -> None:
        async with uow() as u:
            await u.components.save_benchmarks([bench(LAPTOP, 1.0)])
            await u.commit()

    with pytest.raises(IntegrityError):
        await save_orphan()


async def test_kind_slug_is_unique(store: SqlStore) -> None:
    async with store.uow() as u:
        await u.components.add_missing([LAPTOP])
        await u.commit()

    with pytest.raises(IntegrityError):
        async with store.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO components (id, kind, slug, name, segment) "
                    "VALUES ('gpu:other', 'gpu', :slug, 'dup', 'unknown')"
                ),
                {"slug": LAPTOP.slug},
            )

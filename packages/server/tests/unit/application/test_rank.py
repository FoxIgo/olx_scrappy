"""``q rank``, ``q strategies`` and ``q components`` over the in-memory fakes."""

from __future__ import annotations

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.scoring import ComponentFact
from scrappy.domain.component import Component, ComponentKind, ResolutionMethod
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.domain.offer import Price
from scrappy.domain.scoring import Strategy, Term
from tests.unit.application.test_analytics_use_cases import World, scope
from tests.unit.builders import LAPTOP, oid

GPU_FACT = "gpu.blender_open_data.samples_per_minute"
STRATEGY = Strategy(
    "gaming",
    LAPTOP,
    (
        Term("gpu.blender", GPU_FACT, 0.6, 1000),
        Term("ram_gb", "ram_gb", 0.4, 16, cap=32),
    ),
    description="test",
    filters=(AttributePredicate("ram_gb", Comparison.GE, "8"),),
)


def fact(key: str, score: float, *, confidence: float = 1.0) -> ComponentFact:
    return ComponentFact(
        offer_id=oid(key),
        kind=ComponentKind.GPU,
        component_id="gpu:rtx-3060-laptop",
        component_name="RTX 3060 Laptop",
        source="blender_open_data",
        metric="samples_per_minute",
        score=score,
        samples=10,
        confidence=confidence,
        method=ResolutionMethod.EXACT,
    )


@pytest.fixture
def world() -> World:
    w = World({"gaming": STRATEGY})
    w.add("fast", Price.fixed("2000"), {"ram_gb": 16}, minutes=1)  # gpu 2000 -> 1.2 + 0.4
    w.add("cheap", Price.fixed("1000"), {"ram_gb": 16}, minutes=2)  # gpu 1000 -> 0.6 + 0.4
    w.add("nogpu", Price.fixed("500"), {"ram_gb": 32}, minutes=3)  # coverage 0.4
    w.add("small", Price.fixed("400"), {"ram_gb": 4}, minutes=4)  # filtered out (ram < 8)
    w.add("unknown", Price.fixed("400"), {"ram_gb": None}, minutes=5)  # filter: null never matches
    w.add("free", Price.free(), {"ram_gb": 16}, minutes=6)  # not a fixed price
    w.add("raw", Price.fixed("700"), None, minutes=7)  # not extracted
    w.add("phone", Price.fixed("300"), {"model": "x"}, category="phone", minutes=8)
    w.scoring_queries.facts = [fact("fast", 2000, confidence=0.8), fact("cheap", 1000)]
    return w


async def test_rank_orders_by_value_with_breakdown(world: World) -> None:
    answer = await world.q.rank(scope(), "gaming", min_coverage=0.0)
    rows: list[dict[str, object]] = answer.data  # type: ignore[assignment]
    # fast: perf 1.6 / 2000 = 0.8 per 1000;  cheap: 1.0 / 1000 = 1.0;  nogpu: 0.8 / 500 = 1.6
    assert [r["id"] for r in rows] == ["olx_pl:nogpu", "olx_pl:cheap", "olx_pl:fast"]
    cheap = rows[1]
    assert cheap["performance"] == 1.0
    assert cheap["value"] == 1.0
    assert cheap["coverage"] == 1.0
    assert cheap["price"] is not None
    assert cheap["currency"] == "PLN"
    assert cheap["breakdown"] == {
        "gpu.blender": {"points": 0.6, "value": 1000.0, "part": "RTX 3060 Laptop"},
        "ram_gb": {"points": 0.4, "value": 16},
    }
    fast = rows[2]
    assert fast["breakdown"]["gpu.blender"]["link_confidence"] == 0.8  # type: ignore[index]
    nogpu = rows[0]
    assert nogpu["coverage"] == 0.4
    assert nogpu["breakdown"] == {"gpu.blender": "missing", "ram_gb": {"points": 0.8, "value": 32}}


async def test_default_min_coverage_hides_offers_with_unknown_parts(world: World) -> None:
    answer = await world.q.rank(scope(), "gaming")
    assert [r["id"] for r in answer.data] == ["olx_pl:cheap", "olx_pl:fast"]  # type: ignore[index,union-attr]
    excluded = next(n for n in answer.notes if n.startswith("excluded"))
    assert "2 by filters" in excluded  # small, and unknown (null never satisfies ram_gb>=8)
    assert "2 not extracted as laptop" in excluded  # raw and phone
    assert "1 without a fixed price" in excluded
    assert "1 below coverage 0.6" in excluded


async def test_facts_are_fetched_once_for_all_candidates(world: World) -> None:
    await world.q.rank(scope(), "gaming")
    assert len(world.scoring_queries.fact_calls) == 1
    assert {str(o) for o in world.scoring_queries.fact_calls[0]} == {
        "olx_pl:fast",
        "olx_pl:cheap",
        "olx_pl:nogpu",
    }


async def test_user_filters_add_to_the_strategy_filters(world: World) -> None:
    extra = scope(where=(AttributePredicate("price", Comparison.LT, "1500"),))
    answer = await world.q.rank(extra, "gaming", min_coverage=0.0)
    assert [r["id"] for r in answer.data] == ["olx_pl:nogpu", "olx_pl:cheap"]  # type: ignore[index,union-attr]


async def test_limit_truncates_and_fields_project(world: World) -> None:
    answer = await world.q.rank(
        scope(), "gaming", min_coverage=0.0, limit=1, fields=["id", "value", "ram_gb"]
    )
    assert answer.truncated
    assert answer.count == 1
    assert answer.data == [{"id": "olx_pl:nogpu", "value": 1.6, "ram_gb": 32}]  # type: ignore[comparison-overlap]
    assert any("showing the best 1 of 3" in n for n in answer.notes)


async def test_bad_requests(world: World) -> None:
    with pytest.raises(InvalidRequestError, match=r"unknown strategy 'x' .*gaming"):
        await world.q.rank(scope(), "x")
    with pytest.raises(InvalidRequestError, match="between 0 and 1"):
        await world.q.rank(scope(), "gaming", min_coverage=1.5)
    with pytest.raises(InvalidRequestError, match="unknown field 'nope'"):
        await world.q.rank(scope(), "gaming", fields=["nope"])
    with pytest.raises(InvalidRequestError, match="limit"):
        await world.q.rank(scope(), "gaming", limit=0)


async def test_empty_result_says_why(world: World) -> None:
    answer = await world.q.rank(
        scope(where=(AttributePredicate("ram_gb", Comparison.GE, "99"),)), "gaming"
    )
    assert answer.data == []
    assert any("nothing to rank" in n for n in answer.notes)


async def test_strategies_listing(world: World) -> None:
    answer = await world.q.strategies()
    (item,) = answer.data  # type: ignore[misc]
    assert item["name"] == "gaming"
    assert item["filters"] == ["ram_gb>=8"]  # type: ignore[index]
    assert item["terms"][0] == {  # type: ignore[index]
        "fact": "gpu.blender",
        "weight": 0.6,
        "baseline": 1000,
        "transform": "linear",
        "resolves_to": GPU_FACT,
    }
    assert item["terms"][1]["cap"] == 32  # type: ignore[index]


async def test_components_listing_counts_linked_offers(world: World) -> None:
    from scrappy.domain.component import Benchmark
    from tests.unit.builders import T0

    async with world.store.uow() as uow:
        await uow.components.add_missing(
            [
                Component.from_name(ComponentKind.GPU, "NVIDIA GeForce RTX 3060 Laptop GPU"),
                Component.from_name(ComponentKind.GPU, "NVIDIA GeForce RTX 4060 Laptop GPU"),
                Component.from_name(ComponentKind.CPU, "Intel Core i5-12450H"),
            ]
        )
        await uow.components.save_benchmarks(
            [
                Benchmark(
                    "gpu:rtx-3060-laptop", "blender_open_data", "samples_per_minute", 2100, 5, T0
                )
            ]
        )
        await uow.commit()
    world.scoring_queries.counts = {"gpu:rtx-3060-laptop": 7}

    everything = await world.q.components()
    assert everything.count == 3
    top = everything.data[0]  # type: ignore[index]
    assert top["id"] == "gpu:rtx-3060-laptop"
    assert top["offers"] == 7  # type: ignore[index]
    assert top["benchmarks"] == [  # type: ignore[index]
        {
            "source": "blender_open_data",
            "metric": "samples_per_minute",
            "score": 2100.0,
            "samples": 5,
        }
    ]
    gpus = await world.q.components(kind=ComponentKind.GPU, search="4060")
    assert [c["id"] for c in gpus.data] == ["gpu:rtx-4060-laptop"]  # type: ignore[index,union-attr]
    linked = await world.q.components(linked_only=True)
    assert [c["id"] for c in linked.data] == ["gpu:rtx-3060-laptop"]  # type: ignore[index,union-attr]
    assert (await world.q.components(limit=1)).truncated

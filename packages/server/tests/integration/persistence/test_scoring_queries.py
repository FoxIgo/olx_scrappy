"""Component facts for ranking on real SQLite, and ``q rank`` over a tiny seeded database."""

from __future__ import annotations

from scrappy.application.ports.scoring import ComponentFact
from scrappy.application.use_cases.analytics import QueryScope, build_query_use_cases
from scrappy.domain.component import (
    Benchmark,
    ComponentKind,
    OfferComponentLink,
    Resolution,
    ResolutionMethod,
)
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.domain.scoring import Strategy, Term
from scrappy.infrastructure.persistence.analytics import SqlAnalyticsQueries
from tests.integration.persistence.sqlstore import SqlStore
from tests.integration.persistence.test_component_resolution_sql import GPU, seed_world
from tests.unit.builders import LAPTOP, at, catalog, oid
from tests.unit.fakes import StaticCategoryProvider, StaticScoringProvider

FACT = "gpu.blender_open_data.samples_per_minute"


def resolved(key: str, component: str, confidence: float = 1.0) -> OfferComponentLink:
    return OfferComponentLink(
        oid(key),
        GPU,
        "x",
        Resolution(component, confidence, ResolutionMethod.EXACT),
        1,
        at(10),
    )


async def seed_links(store: SqlStore) -> None:
    await seed_world(store.uow)
    async with store.uow() as u:
        await u.components.save_benchmarks(
            [
                Benchmark(
                    "gpu:rtx-4060-laptop", "blender_open_data", "samples_per_minute", 3300, 9, at(0)
                ),
                Benchmark("gpu:rtx-4060-laptop", "other_source", "points", 7, 1, at(0)),
            ]
        )
        await u.components.save_links(
            [
                resolved("1", "gpu:rtx-4060-laptop", 0.95),
                resolved("5", "gpu:rtx-4060-laptop"),
                # linked to a part without any benchmark: no fact
                resolved("4", "gpu:rtx-4060"),
                OfferComponentLink(
                    oid("2"), ComponentKind.CPU, "x", Resolution.unresolved(), 1, at(10)
                ),
            ]
        )
        await u.commit()


async def test_component_facts_are_one_row_per_benchmark_of_linked_components(
    store: SqlStore,
) -> None:
    await seed_links(store)
    queries = SqlAnalyticsQueries(store.engine)
    facts = await queries.component_facts([oid("1"), oid("4"), oid("5"), oid("2"), oid("3")])
    by_offer: dict[str, list[ComponentFact]] = {}
    for fact in facts:
        by_offer.setdefault(str(fact.offer_id), []).append(fact)
    assert sorted(by_offer) == ["olx_pl:1", "olx_pl:5"]  # 4: no benchmark, 2: unresolved
    first = {(f.source, f.metric): f for f in by_offer["olx_pl:1"]}
    blender = first[("blender_open_data", "samples_per_minute")]
    assert blender.score == 3300 and blender.samples == 9
    assert (blender.kind, blender.component_id) == (GPU, "gpu:rtx-4060-laptop")
    assert blender.component_name == "NVIDIA GeForce RTX 4060 Laptop GPU"
    assert blender.confidence == 0.95 and blender.method is ResolutionMethod.EXACT
    assert ("other_source", "points") in first
    assert await queries.component_facts([]) == []


async def test_offer_counts_per_component(store: SqlStore) -> None:
    await seed_links(store)
    counts = await SqlAnalyticsQueries(store.engine).component_offer_counts()
    assert counts == {"gpu:rtx-4060-laptop": 2, "gpu:rtx-4060": 1}


async def test_rank_over_sql(store: SqlStore) -> None:
    await seed_links(store)
    strategy = Strategy(
        "gaming",
        LAPTOP,
        (Term("gpu.blender", FACT, 1.0, 3300),),
        filters=(AttributePredicate("gpu", Comparison.CONTAINS, "rtx"),),
    )
    analytics = SqlAnalyticsQueries(store.engine)
    q = build_query_use_cases(
        uow=store.uow,
        queries=analytics,
        categories=StaticCategoryProvider(catalog()),
        scoring=StaticScoringProvider({"gaming": strategy}),
        scoring_queries=analytics,
    )
    answer = await q.rank(QueryScope(relevant_only=False), "gaming", min_coverage=0.0)
    rows = {r["id"]: r for r in answer.data}  # type: ignore[union-attr]
    # offer 1 has gpu "RTX 4060" (offer 5's latest extraction is "GTX 1650": filtered out)
    assert list(rows) == ["olx_pl:1"]
    row = rows["olx_pl:1"]
    assert row["performance"] == 1.0 and row["coverage"] == 1.0
    assert row["breakdown"]["gpu.blender"]["part"] == "NVIDIA GeForce RTX 4060 Laptop GPU"  # type: ignore[index]
    assert row["breakdown"]["gpu.blender"]["link_confidence"] == 0.95  # type: ignore[index]
    assert row["price"] is not None and row["value"] is not None

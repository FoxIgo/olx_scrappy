"""Tiering (ADR 0012): the rule pass, escalation, the gated LLM backlog and promotion.

Re-run unchanged against SQLite by ``tests/integration/persistence/test_unit_suite_on_sql``.
"""

from __future__ import annotations

from collections.abc import Sequence

from scrappy.application.policy import ExtractionPolicy, PipelinePolicy, TieringPolicy
from scrappy.application.ports.extractor import RULES_MODEL, ExtractionResult, RuleExtraction
from scrappy.application.ports.listing_source import SearchPageResult
from scrappy.domain.category import OTHER_CATEGORY
from scrappy.domain.component import Component, ComponentKind
from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import ObservationLevel, OfferId, OfferObservation
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, SourceId
from tests.unit.application.harness import App, rules_by_title
from tests.unit.builders import LAPTOP, details
from tests.unit.fakes.extraction import FixedTop, ScriptedRules

SEARCH = SearchName("laptops")
URL = "https://www.olx.pl/oferty/q-laptop/"


def tiered(**options: object) -> PipelinePolicy:
    return PipelinePolicy(
        extraction=ExtractionPolicy(tiering=TieringPolicy(enabled=True, **options))  # type: ignore[arg-type]
    )


async def seeded(app: App, titles: Sequence[str]) -> list[OfferId]:
    """One detail-complete offer per title, found by one run."""
    source = app.add_source("olx_pl")
    await app.add_search(SEARCH, SourceId("olx_pl"), URL, LAPTOP)
    observations = tuple(
        details(str(n), title=title, description=f"offer {n}")
        for n, title in enumerate(titles, start=1)
    )
    source.script_page(URL, SearchPageResult(FetchOutcome.OK, observations=observations))
    await app.start_run(SEARCH)
    await app.drain()
    return [o.offer_id for o in observations]


async def latest(app: App, offer_id: OfferId) -> OfferExtraction | None:
    async with app.store.uow() as uow:
        return await uow.extractions.latest(offer_id)


async def escalation(app: App, offer_id: OfferId) -> tuple[str, ...]:
    async with app.store.uow() as uow:
        state = await uow.extraction_states.get(offer_id)
    return () if state is None else state.escalation_reasons


# ---------------------------------------------------------------------------- rule pass


async def test_rule_pass_stores_rule_extractions_once() -> None:
    app = App(policy=tiered())
    ids = await seeded(app, ["Laptop A", "Laptop B"])

    report = await app.tier()

    assert (report.ruled, report.stored, report.escalated) == (2, 2, 0)
    for offer_id in ids:
        found = await latest(app, offer_id)
        assert found is not None
        assert found.category == LAPTOP
        assert found.attributes["ram_gb"] == 8
        assert found.provenance.model == RULES_MODEL
        assert found.provenance.prompt_version == "rules-t1"
    again = await app.tier()
    assert again.ruled == 0
    assert len(app.rules.calls) == 2


async def test_rule_extraction_derives_relevance() -> None:
    app = App(policy=tiered())
    (laptop,) = await seeded(app, ["Laptop A"])

    await app.tier()

    async with app.store.uow() as uow:
        (link,) = await uow.search_offers.list_for_offer(laptop)
    assert link.derived_relevance is True


async def test_uncertain_offers_are_escalated_and_only_they_reach_the_llm() -> None:
    app = App(policy=tiered())
    sure, unsure, empty = await seeded(
        app, ["Laptop sure", "Laptop unsure:ram_conflict", "Charger"]
    )

    report = await app.tier()

    assert report.escalated == 2
    assert report.reasons == {"ram_conflict": 1, "empty": 1}
    assert await escalation(app, sure) == ()
    assert await escalation(app, unsure) == ("ram_conflict",)
    assert await escalation(app, empty) == ("empty",)
    assert await latest(app, empty) is None  # no rule result for it
    assert await app.backlog() == 2

    stored = await app.extract()

    assert stored == 2
    called = {request.offer_id for request in app.extractor.calls}
    assert called == {unsure, empty}
    llm = await latest(app, unsure)
    assert llm is not None
    assert llm.provenance.model == "fake-model"
    rules = await latest(app, sure)
    assert rules is not None
    assert rules.provenance.model == RULES_MODEL
    assert await app.backlog() == 0


async def test_reasons_outside_the_escalate_list_stay_with_the_rules() -> None:
    app = App(policy=tiered(escalate=frozenset({"damaged"})))
    (offer,) = await seeded(app, ["Laptop unsure:ram_conflict"])

    report = await app.tier()

    assert report.escalated == 0
    assert await escalation(app, offer) == ()
    assert await app.backlog() == 0


async def test_llm_extraction_is_not_overwritten_by_a_rule_rerun() -> None:
    app = App(policy=tiered())
    (offer,) = await seeded(app, ["Laptop unsure:damaged"])
    await app.tier()
    await app.extract()

    app.tier._rules = ScriptedRules(rules_by_title, version="rules-t2")  # pyright: ignore[reportPrivateUsage]
    report = await app.tier()

    assert report.ruled == 1
    assert report.stored == 0
    assert app.tier._rules.calls == []  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
    found = await latest(app, offer)
    assert found is not None
    assert found.provenance.model == "fake-model"
    assert await app.backlog() == 0


async def test_changed_content_reruns_the_rules_and_supersedes_the_old_llm_answer() -> None:
    app = App(policy=tiered())
    (offer,) = await seeded(app, ["Laptop unsure:damaged"])
    await app.tier()
    await app.extract()

    async with app.store.uow() as uow:
        stored = await uow.offers.get(offer)
        assert stored is not None
        stored.apply(
            OfferObservation(offer, ObservationLevel.DETAILS, description="edited"),
            app.clock.now(),
        )
        await uow.offers.save(stored)
        await uow.commit()
    report = await app.tier()

    assert (report.ruled, report.stored) == (1, 1)
    found = await latest(app, offer)
    assert found is not None
    assert found.provenance.model == RULES_MODEL
    assert await escalation(app, offer) == ("damaged",)  # the title still says so
    assert await app.backlog() == 1


async def test_invalid_rule_output_is_escalated() -> None:
    def bad(request: object) -> RuleExtraction:
        return RuleExtraction(ExtractionResult(LAPTOP, {"nonsense": 1}, RULES_MODEL, "rules-t1"))

    app = App(policy=tiered(), rules=ScriptedRules(bad))  # type: ignore[arg-type]
    (offer,) = await seeded(app, ["Laptop A"])

    report = await app.tier()

    assert report.stored == 0
    assert await escalation(app, offer) == ("rules_invalid",)
    assert report.notes


async def test_junk_classified_by_rules_is_stored_as_other() -> None:
    def junk(request: object) -> RuleExtraction:
        return RuleExtraction(ExtractionResult(OTHER_CATEGORY, {}, RULES_MODEL, "rules-t1"))

    app = App(policy=tiered(), rules=ScriptedRules(junk))  # type: ignore[arg-type]
    (offer,) = await seeded(app, ["Zasilacz do laptopa"])

    await app.tier()

    found = await latest(app, offer)
    assert found is not None
    assert found.category == OTHER_CATEGORY
    async with app.store.uow() as uow:
        (link,) = await uow.search_offers.list_for_offer(offer)
    assert link.derived_relevance is False


# ---------------------------------------------------------------------------- promotion


async def test_top_offers_are_promoted_to_the_llm() -> None:
    app = App(policy=tiered(top_n=1, min_coverage=0.3), top=FixedTop())
    first, second, third = await seeded(app, ["Laptop 1", "Laptop 2", "Laptop 3"])
    app.top.ranking = {"gaming": [second, first], "work": [third]}

    report = await app.tier()

    assert report.promoted == 2
    assert report.reasons == {"top:gaming": 1, "top:work": 1}
    assert app.top.calls == [(1, 0.3)]
    assert await escalation(app, second) == ("top:gaming",)
    assert await escalation(app, first) == ()
    assert await app.backlog() == 2

    await app.extract()
    app.top.ranking = {"gaming": [second, first]}
    again = await app.tier(promote=True)

    assert again.promoted == 0  # second is LLM-extracted now; first is beyond top_n
    app.tier._policy = ExtractionPolicy(tiering=TieringPolicy(enabled=True, top_n=2))  # pyright: ignore[reportPrivateUsage]
    third_round = await app.tier(promote=True)
    assert third_round.promoted == 1
    assert await escalation(app, first) == ("top:gaming",)


async def test_promotion_adds_a_reason_without_counting_twice() -> None:
    app = App(policy=tiered(top_n=5), top=FixedTop())
    (offer,) = await seeded(app, ["Laptop unsure:damaged"])
    app.top.ranking = {"gaming": [offer], "work": [offer]}

    report = await app.tier()

    assert report.escalated == 1
    assert report.promoted == 0  # already on its way to the LLM
    assert await escalation(app, offer) == ("damaged", "top:gaming", "top:work")


async def test_no_promotion_without_rule_work_unless_asked() -> None:
    app = App(policy=tiered(), top=FixedTop())
    await seeded(app, ["Laptop 1"])
    await app.tier()
    calls = len(app.top.calls)

    await app.tier()
    assert len(app.top.calls) == calls
    await app.tier(promote=True)
    assert len(app.top.calls) == calls + 1


# ---------------------------------------------------------------------------- disabled


async def test_without_tiering_the_llm_backlog_is_not_gated() -> None:
    app = App(top=FixedTop())
    first, _ = await seeded(app, ["Laptop 1", "Laptop 2"])
    app.top.ranking = {"gaming": [first]}

    report = await app.tier()

    assert report.ruled == 2
    assert report.promoted == 0
    assert app.top.calls == []
    assert await app.backlog() == 2


# ---------------------------------------------------------------------------- components


async def test_components_are_resolved_only_once_a_catalogue_exists() -> None:
    calls: list[None] = []

    async def resolve() -> None:
        calls.append(None)

    app = App(policy=tiered())
    app.tier._resolve = resolve  # pyright: ignore[reportPrivateUsage]
    await seeded(app, ["Laptop 1"])

    await app.tier()
    assert calls == []  # before `benchmarks import`: links would all be stored unresolved

    async with app.store.uow() as uow:
        await uow.components.add_missing([Component.from_name(ComponentKind.GPU, "RTX 3060")])
        await uow.commit()
    await change_title(app)
    await app.tier()
    assert calls == [None]


async def change_title(app: App) -> None:
    async with app.store.uow() as uow:
        offer = await uow.offers.get(OfferId(SourceId("olx_pl"), "1"))
        assert offer is not None
        offer.apply(
            OfferObservation(offer.id, ObservationLevel.DETAILS, description="edited"),
            app.clock.now(),
        )
        await uow.offers.save(offer)
        await uow.commit()

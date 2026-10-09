import pytest

from scrappy.domain.category import OTHER_CATEGORY
from scrappy.domain.extraction import OfferExtraction, TokenUsage
from scrappy.domain.offer import Offer
from scrappy.domain.run import (
    DiscoveryCoverage,
    HealthThresholds,
    Phase,
    PhaseMetrics,
    RunMetrics,
    RunStatus,
    ScrapeRun,
    conclude_run,
    run_health,
)
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer, relevance
from scrappy.domain.shared import FetchOutcome, InvalidValueError, RunId, SourceId
from tests.unit.builders import LAPTOP, at, catalog, details


def search() -> SavedSearch:
    return SavedSearch(
        SearchName("gtx-laptops"), SourceId("olx_pl"), "https://x.test/q", LAPTOP, at(0)
    )


def extraction(category: object = LAPTOP) -> OfferExtraction:
    offer = Offer.from_observation(details("1"), at(0))
    assert offer.content_hash is not None
    return OfferExtraction.validated(
        offer_id=offer.id,
        category=category,  # type: ignore[arg-type]
        raw_attributes={},
        catalog=catalog(),
        model="m",
        prompt_version="p",
        content_hash=offer.content_hash,
        extracted_at=at(1),
    )


class TestRelevance:
    def test_unknown_until_extracted(self) -> None:
        assert relevance(search(), None) is None

    def test_category_match(self) -> None:
        assert relevance(search(), extraction(LAPTOP)) is True
        assert relevance(search(), extraction(OTHER_CATEGORY)) is False

    def test_override_wins(self) -> None:
        assert relevance(search(), extraction(OTHER_CATEGORY), override=True) is True
        assert relevance(search(), None, override=False) is False

    def test_search_offer_effective_relevance(self) -> None:
        link = SearchOffer.first_seen(search().name, extraction().offer_id, at(0))
        link.update_relevance(search(), extraction(OTHER_CATEGORY))
        assert link.is_relevant is False
        link.set_override(True)
        assert link.is_relevant is True
        link.update_relevance(search(), extraction(OTHER_CATEGORY))  # re-extraction
        assert link.is_relevant is True  # override survives
        link.set_override(None)
        assert link.is_relevant is False

    def test_search_validation(self) -> None:
        with pytest.raises(InvalidValueError):
            SearchName("Has Spaces")
        with pytest.raises(InvalidValueError):
            SavedSearch(SearchName("a"), SourceId("olx_pl"), "ftp://x", LAPTOP, at(0))


def discovery(accepted: int, rejected: int, price_present: int) -> PhaseMetrics:
    return PhaseMetrics(
        accepted=accepted,
        rejected=rejected,
        present={"price": price_present},
        applicable={"price": accepted},
        outcomes={FetchOutcome.OK: 1},
    )


class TestMetrics:
    def test_builders_and_rates(self) -> None:
        metrics = (
            PhaseMetrics()
            .with_outcome(FetchOutcome.OK)
            .with_accepted({"price": True, "title": True})
            .with_accepted({"price": False, "title": True})
            .with_rejected()
        )
        assert metrics.seen == 3
        assert metrics.fill_rate("price") == 0.5
        assert metrics.fill_rate("unknown") is None
        assert metrics.rejected_ratio == pytest.approx(1 / 3)
        assert metrics.outcome_count(FetchOutcome.OK) == 1

    def test_run_metrics_sum(self) -> None:
        a = RunMetrics(
            discovery=discovery(2, 0, 2),
            usage=TokenUsage(1, 1),
            coverage=DiscoveryCoverage(1, 173, False),
        )
        b = RunMetrics(
            discovery=discovery(3, 1, 3),
            usage=TokenUsage(2, 2),
            coverage=DiscoveryCoverage(1, 1000, True),
        )
        total = a + b
        assert total.discovery.accepted == 5
        assert total.usage == TokenUsage(3, 3)
        assert total.coverage == DiscoveryCoverage(2, 1000, True)
        assert total.phase(Phase.DISCOVERY) is total.discovery


class TestRunHealth:
    thresholds = HealthThresholds(
        max_rejected_ratio=0.05, min_fill_rates={Phase.DISCOVERY: {"price": 0.95}}, min_sample=5
    )

    def test_healthy(self) -> None:
        report = run_health(RunMetrics(discovery=discovery(100, 1, 100)), self.thresholds)
        assert report.status is RunStatus.COMPLETED
        assert report.reasons == ()

    def test_fill_rate_drop_is_degraded_and_named(self) -> None:
        report = run_health(RunMetrics(discovery=discovery(100, 0, 50)), self.thresholds)
        assert report.status is RunStatus.DEGRADED
        assert "price" in report.reasons[0]

    def test_rejections_degrade(self) -> None:
        report = run_health(RunMetrics(discovery=discovery(90, 10, 90)), self.thresholds)
        assert report.status is RunStatus.DEGRADED

    def test_small_samples_not_judged(self) -> None:
        report = run_health(RunMetrics(discovery=discovery(2, 2, 0)), self.thresholds)
        assert report.status is RunStatus.COMPLETED

    def test_invalid_thresholds(self) -> None:
        with pytest.raises(InvalidValueError):
            HealthThresholds(max_rejected_ratio=2)


class TestConcludeRun:
    thresholds = HealthThresholds(min_sample=1, min_fill_rates={Phase.DISCOVERY: {"price": 0.9}})

    def test_completed(self) -> None:
        assert conclude_run(RunMetrics(discovery=discovery(10, 0, 10)), self.thresholds).status is (
            RunStatus.COMPLETED
        )

    def test_failed_when_no_page_fetched(self) -> None:
        metrics = RunMetrics(discovery=PhaseMetrics(outcomes={FetchOutcome.BLOCKED: 1}))
        assert conclude_run(metrics, self.thresholds).status is RunStatus.FAILED

    def test_partial_when_jobs_failed(self) -> None:
        metrics = RunMetrics(discovery=discovery(10, 0, 10), failed_jobs=2)
        conclusion = conclude_run(metrics, self.thresholds)
        assert conclusion.status is RunStatus.PARTIAL
        assert "2 work item" in conclusion.reasons[0]

    def test_degraded_wins_over_partial(self) -> None:
        metrics = RunMetrics(discovery=discovery(10, 0, 1), failed_jobs=1)
        conclusion = conclude_run(metrics, self.thresholds)
        assert conclusion.status is RunStatus.DEGRADED
        assert len(conclusion.reasons) == 2

    def test_truncation_is_a_warning(self) -> None:
        metrics = RunMetrics(
            discovery=discovery(10, 0, 10), coverage=DiscoveryCoverage(25, 1000, True)
        )
        conclusion = conclude_run(metrics, self.thresholds)
        assert conclusion.status is RunStatus.COMPLETED
        assert "1000 reported" in conclusion.warnings[0]


class TestScrapeRun:
    def test_lifecycle(self) -> None:
        run = ScrapeRun.start(RunId("r1"), search(), at(0))
        assert run.is_running
        run.finish(
            conclude_run(RunMetrics(discovery=discovery(1, 0, 1)), HealthThresholds()),
            RunMetrics(),
            at(1),
        )
        assert run.status is RunStatus.COMPLETED
        assert run.finished_at == at(1)
        run.reopen()
        assert run.is_running
        assert run.finished_at is None

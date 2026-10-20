"""Wires the application with in-memory fakes, the way ``main.py`` wires real adapters.

Scraping and extraction are separate (ADR 0010): ``drain()`` runs the scraping jobs,
``extract()`` runs the extractor (reconcile + poll ticks) until there is nothing left.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scrappy.application.jobs.dispatcher import JobDispatcher, JobHandler
from scrappy.application.jobs.handlers.discover_page import DiscoverPageHandler
from scrappy.application.jobs.handlers.enrich_offer import EnrichOfferHandler
from scrappy.application.jobs.model import Job, JobStatus, JobType
from scrappy.application.policy import PipelinePolicy
from scrappy.application.ports.extraction_backends import ExtractionProfiles
from scrappy.application.ports.extractor import (
    RULES_MODEL,
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RuleExtraction,
)
from scrappy.application.ports.listing_source import ListingSource
from scrappy.application.use_cases.extraction import (
    ExtractionStatus,
    ForceReextract,
    PollBatches,
    ReconcileExtractions,
    TierExtractions,
)
from scrappy.application.use_cases.finalize_run import FinalizeRun
from scrappy.application.use_cases.list_offers import ListOffers
from scrappy.application.use_cases.runs import FinalizeIdleRuns, RefreshOffer, ResumeRun, StartRun
from scrappy.application.use_cases.searches import AddSavedSearch, SetRelevanceOverride
from scrappy.application.use_cases.verify_offers import VerifyOffers
from scrappy.domain.category import OTHER_CATEGORY, CategoryCatalog
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.shared import SourceId
from tests.unit.builders import LAPTOP, catalog
from tests.unit.fakes import (
    FakeClock,
    InMemoryOfferQueries,
    InMemoryStore,
    ScriptedExtractor,
    ScriptedListingSource,
    SequentialIds,
    StaticCategoryProvider,
)
from tests.unit.fakes.extraction import FixedTop, ScriptedRules, make_profile, profiles_of


def classify_by_title(request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
    """Default fake LLM: titles mentioning 'laptop' are laptops, everything else is other."""
    usage = TokenUsage(100, 20)
    if "laptop" in request.title.lower():
        return ExtractionResult(
            LAPTOP, {"gpu": "GTX 1650", "ram_gb": 16}, "fake-model", "p1", usage
        )
    return ExtractionResult(OTHER_CATEGORY, {}, "fake-model", "p1", usage)


def rules_by_title(request: ExtractionInput) -> RuleExtraction:
    """Default fake rule pass: laptops get ``ram_gb`` 8; a title with ``unsure:<reason>``
    words reports those reasons; titles without 'laptop' give nothing."""
    reasons = tuple(w.split(":", 1)[1] for w in request.title.split() if w.startswith("unsure:"))
    if "laptop" not in request.title.lower():
        return RuleExtraction(None, reasons or ("empty",))
    result = ExtractionResult(LAPTOP, {"ram_gb": 8}, RULES_MODEL, "rules-t1")
    return RuleExtraction(result, reasons)


@dataclass
class App:
    policy: PipelinePolicy = field(default_factory=PipelinePolicy)
    catalog: CategoryCatalog = field(default_factory=catalog)
    store: InMemoryStore = field(default_factory=InMemoryStore)
    clock: FakeClock = field(default_factory=FakeClock)
    ids: SequentialIds = field(default_factory=SequentialIds)
    sources: dict[SourceId, ListingSource] = field(default_factory=dict[SourceId, ListingSource])
    extractor: ScriptedExtractor = field(
        default_factory=lambda: ScriptedExtractor(classify_by_title)
    )
    profiles: ExtractionProfiles | None = None
    """Default: one sync profile ``main`` around :attr:`extractor`."""
    rules: ScriptedRules = field(default_factory=lambda: ScriptedRules(rules_by_title))
    top: FixedTop = field(default_factory=FixedTop)

    def __post_init__(self) -> None:
        self.categories = StaticCategoryProvider(self.catalog)
        uow = self.store.uow
        self.finalize_run = FinalizeRun(uow=uow, clock=self.clock, policy=self.policy)
        handlers: dict[JobType, JobHandler] = {
            JobType.DISCOVER_PAGE: DiscoverPageHandler(
                uow=uow, sources=self.sources, clock=self.clock, ids=self.ids, policy=self.policy
            ),
            JobType.ENRICH_OFFER: EnrichOfferHandler(
                uow=uow, sources=self.sources, clock=self.clock
            ),
        }
        if self.profiles is None:
            self.profiles = profiles_of(make_profile("main", self.extractor))
        self.reconcile = ReconcileExtractions(
            uow=uow,
            profiles=self.profiles,
            categories=self.categories,
            clock=self.clock,
            ids=self.ids,
            policy=self.policy.extraction,
            worker_id="w1",
        )
        self.poll = PollBatches(
            uow=uow,
            profiles=self.profiles,
            categories=self.categories,
            clock=self.clock,
            ids=self.ids,
            policy=self.policy.extraction,
            reconcile=self.reconcile,
        )
        self.extraction_status = ExtractionStatus(
            uow=uow,
            profiles=self.profiles,
            categories=self.categories,
            clock=self.clock,
            selector=self.reconcile.selector,
            gated=self.policy.extraction.tiering.enabled,
        )
        self.tier = TierExtractions(
            uow=uow,
            clock=self.clock,
            categories=self.categories,
            rules=self.rules,
            policy=self.policy.extraction,
            top_offers=self.top,
        )
        self.force_reextract = ForceReextract(uow=uow, profiles=self.profiles, clock=self.clock)
        self.finalize_idle_runs = FinalizeIdleRuns(uow=uow, finalize_run=self.finalize_run)
        self.dispatcher = JobDispatcher(
            handlers=handlers,
            uow=uow,
            clock=self.clock,
            retry=self.policy.retry,
            finalize_run=self.finalize_run,
        )
        self.add_search = AddSavedSearch(
            uow=uow, categories=self.categories, sources=self.sources, clock=self.clock
        )
        self.start_run = StartRun(uow=uow, clock=self.clock, ids=self.ids)
        self.resume_run = ResumeRun(uow=uow, clock=self.clock, finalize_run=self.finalize_run)
        self.refresh_offer = RefreshOffer(uow=uow, clock=self.clock, ids=self.ids)
        self.list_offers = ListOffers(
            uow=uow, queries=InMemoryOfferQueries(self.store), categories=self.categories
        )
        self.set_override = SetRelevanceOverride(uow=uow)
        self.verify_offers = VerifyOffers(uow=uow, sources=self.sources, clock=self.clock)

    def add_source(self, name: str) -> ScriptedListingSource:
        source = ScriptedListingSource(name)
        self.sources[source.source_id] = source
        return source

    async def drain(self, max_jobs: int = 1000) -> int:
        """Process due jobs until none is left (what ``--inline`` will do)."""
        processed = 0
        while processed < max_jobs:
            self.clock.advance()
            if not await self.dispatcher.run_once():
                return processed
            processed += 1
        raise AssertionError("job queue did not drain")

    async def extract(self, *, flush: bool = True, max_ticks: int = 100) -> int:
        """Run the extractor until a tick does nothing: reconcile, then poll open batches.
        Returns the number of extractions stored."""
        stored = 0
        for _ in range(max_ticks):
            self.clock.advance()
            report = await self.reconcile(flush=flush)
            polled = await self.poll()
            stored += report.stored + polled.stored
            if not report.did_work and not polled.did_work:
                return stored
        raise AssertionError("extractor did not settle")

    async def backlog(self) -> int:
        return await self.extraction_status.backlog()

    def jobs(self, job_type: JobType | None = None) -> list[Job]:
        jobs = sorted(self.store.state.jobs.values(), key=lambda j: self.store.state.job_seq[j.id])
        return [j for j in jobs if job_type is None or j.type is job_type]

    def jobs_with_status(self, status: JobStatus) -> list[Job]:
        return [j for j in self.jobs() if j.status is status]

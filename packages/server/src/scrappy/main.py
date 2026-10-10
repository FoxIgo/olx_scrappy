"""Composition root: the only module allowed to import from every layer.

``build_app(settings)`` wires real adapters into the use cases and the job dispatcher and
returns a :class:`Container`. No DI framework; manual wiring (ADR 0002). Every adapter can
be replaced through keyword arguments, which is how the CLI tests inject a fake listing
source and a fake extractor while still running the real SQLite persistence.

Extraction (ADR 0010) is not a job: ``config/extraction.yaml`` (or, without it, the
``SCRAPPY_LLM_*`` settings) defines extraction profiles, and the extractor loop reconciles
the backlog. A missing API key is **not** a startup error: that profile reports itself
unavailable (``scrappy extract profiles``), offers stay in the backlog, and extraction heals
by itself once the key is set.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import typer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from scrappy.application.errors import ApplicationError
from scrappy.application.jobs.dispatcher import JobDispatcher, JobHandler
from scrappy.application.jobs.handlers.discover_page import DiscoverPageHandler
from scrappy.application.jobs.handlers.enrich_offer import EnrichOfferHandler
from scrappy.application.jobs.model import JobType
from scrappy.application.policy import ExtractionPolicy, PipelinePolicy
from scrappy.application.ports.extraction_backends import (
    ExtractionProfile,
    ExtractionProfiles,
    ProfileHealth,
    StaticExtractionProfiles,
)
from scrappy.application.ports.extractor import AttributeExtractor
from scrappy.application.ports.listing_source import ListingSource
from scrappy.application.ports.queries import OfferQueries
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics import QueryUseCases, build_query_use_cases
from scrappy.application.use_cases.benchmarks import ImportBenchmarks, ListComponents
from scrappy.application.use_cases.component_resolution import (
    AddComponentAlias,
    ComponentResolutionStatus,
    ResolveComponents,
)
from scrappy.application.use_cases.extraction import (
    ExtractionStatus,
    ForceReextract,
    PollBatches,
    ProvisionalTop,
    ReconcileExtractions,
    TierExtractions,
)
from scrappy.application.use_cases.finalize_run import FinalizeRun
from scrappy.application.use_cases.list_offers import ListOffers
from scrappy.application.use_cases.runs import (
    FinalizeIdleRuns,
    RefreshOffer,
    ResumeRun,
    StartRun,
)
from scrappy.application.use_cases.searches import AddSavedSearch, SetRelevanceOverride
from scrappy.domain.shared import DomainError, SourceId
from scrappy.infrastructure.benchmarks import BlenderOpenDataDownloader, BlenderOpenDataSource
from scrappy.infrastructure.config.categories import YamlCategoryProvider
from scrappy.infrastructure.config.errors import ConfigError
from scrappy.infrastructure.config.extraction import load_extraction_config
from scrappy.infrastructure.config.policy import build_pipeline_policy
from scrappy.infrastructure.config.scoring import YamlScoringProvider
from scrappy.infrastructure.config.settings import Settings
from scrappy.infrastructure.config.sources import SourceConfig, SourcesConfig, load_sources
from scrappy.infrastructure.extraction.profiles import build_profiles
from scrappy.infrastructure.extraction.prompt import PROMPT_VERSION
from scrappy.infrastructure.extraction.rules import RuleBasedExtractor
from scrappy.infrastructure.persistence import (
    SqlAnalyticsQueries,
    SqlOfferQueries,
    create_engine,
    sql_unit_of_work_factory,
    upgrade_to_head_async,
)
from scrappy.infrastructure.scraping.engines.base import PageFetcher
from scrappy.infrastructure.scraping.engines.decorators import FileArchiveWriter
from scrappy.infrastructure.scraping.engines.factory import build_fetcher
from scrappy.infrastructure.scraping.sources.olx_pl.source import OlxPlListingSource
from scrappy.infrastructure.system import SystemClock, UuidIdGenerator
from scrappy.presentation.cli.app import app as cli_app
from scrappy.presentation.cli.render import configure_streams
from scrappy.presentation.services import CliContext

type SourceFactory = Callable[[SourceConfig, PageFetcher], ListingSource]


def _olx_pl(config: SourceConfig, fetcher: PageFetcher) -> ListingSource:
    if config.page_size is None:
        return OlxPlListingSource(fetcher, timeout=config.engine.timeout_seconds)
    return OlxPlListingSource(
        fetcher, page_size=config.page_size, timeout=config.engine.timeout_seconds
    )


SOURCE_REGISTRY: Mapping[str, SourceFactory] = {"olx_pl": _olx_pl}
"""Source recipes by source id. A new site = one entry here (ADR 0004)."""


class _AlwaysHealthy:
    async def check(self, *, probe: bool = False) -> ProfileHealth:
        return ProfileHealth(True, "injected extractor (no health check)")


def single_profile(
    extractor: AttributeExtractor,
    *,
    name: str = "custom",
    model: str = "custom",
    prompt_version: str = PROMPT_VERSION,
) -> StaticExtractionProfiles:
    """Profiles made of one injected sync extractor (tests, embedding)."""
    profile = ExtractionProfile(
        name=name,
        provider="custom",
        model=model,
        prompt_version=prompt_version,
        extractor=extractor,
        health=_AlwaysHealthy(),
    )
    return StaticExtractionProfiles({name: profile}, default_profile=name)


@dataclass
class Container:
    """Everything presentation needs: use cases, read ports and lifecycle."""

    settings: Settings
    policy: PipelinePolicy
    engine: AsyncEngine
    uow: UnitOfWorkFactory
    clock: Clock
    categories: CategoryProvider
    queries: OfferQueries
    sources: Mapping[SourceId, ListingSource]
    dispatcher: JobDispatcher
    finalize_run: FinalizeRun
    add_search: AddSavedSearch
    start_run: StartRun
    resume_run: ResumeRun
    refresh_offer: RefreshOffer
    finalize_idle_runs: FinalizeIdleRuns
    list_offers: ListOffers
    set_override: SetRelevanceOverride
    q: QueryUseCases
    profiles: ExtractionProfiles
    reconcile_extractions: ReconcileExtractions
    tier_extractions: TierExtractions
    poll_batches: PollBatches
    extraction_status: ExtractionStatus
    force_reextract: ForceReextract
    extraction_policy: ExtractionPolicy
    extraction_config_source: str
    import_benchmarks: ImportBenchmarks
    list_components: ListComponents
    resolve_components: ResolveComponents
    component_resolution_status: ComponentResolutionStatus
    add_component_alias: AddComponentAlias
    log_level: str
    worker_poll_interval: float
    _fetchers: list[PageFetcher] = field(default_factory=list[PageFetcher], repr=False)
    _closed: bool = field(default=False, repr=False)

    @property
    def data_location(self) -> str:
        return self.engine.url.render_as_string(hide_password=True)

    async def aclose(self) -> None:
        """Close the fetchers and dispose the engine. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for fetcher in self._fetchers:
            await fetcher.aclose()
        await self.engine.dispose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def _build_sources(
    sources_config: SourcesConfig, settings: Settings
) -> tuple[dict[SourceId, ListingSource], list[PageFetcher]]:
    archive_dir = settings.archive_dir or settings.data_dir / "raw"
    writer = FileArchiveWriter(archive_dir)  # shared by every source with archive: true
    sources: dict[SourceId, ListingSource] = {}
    fetchers: list[PageFetcher] = []
    for config in sources_config.enabled:
        factory = SOURCE_REGISTRY.get(config.id.value)
        if factory is None:
            known = ", ".join(sorted(SOURCE_REGISTRY))
            raise ConfigError(
                f"sources.yaml enables source {config.id}, but no recipe exists for it "
                f"(known recipes: {known})"
            )
        try:
            fetcher = build_fetcher(config.engine, archive_writer=writer)
        except ValueError as error:
            raise ConfigError(f"sources.yaml: source {config.id}: {error}") from error
        fetchers.append(fetcher)
        sources[config.id] = factory(config, fetcher)
    return sources, fetchers


async def build_app(
    settings: Settings,
    *,
    sources: Mapping[SourceId, ListingSource] | None = None,
    extractor: AttributeExtractor | None = None,
    profiles: ExtractionProfiles | None = None,
    categories: CategoryProvider | None = None,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    migrate: bool = True,
) -> Container:
    """Create the engine, migrate the database and wire the application.

    Overrides (tests, embedding): ``sources`` replaces the sources.yaml/recipe wiring (no
    fetchers are built and sources.yaml is optional); ``profiles`` replaces the extraction
    profiles of extraction.yaml; ``extractor`` is a shortcut for one sync profile around it.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    listing_sources: dict[SourceId, ListingSource]
    fetchers: list[PageFetcher]
    if sources is None:
        sources_config = load_sources(settings.sources_file)
        listing_sources, fetchers = _build_sources(sources_config, settings)
    else:
        sources_config = (
            load_sources(settings.sources_file)
            if settings.sources_file.exists()
            else SourcesConfig()
        )
        listing_sources, fetchers = dict(sources), []

    extraction_config = load_extraction_config(settings)
    policy = build_pipeline_policy(settings, sources_config, extraction_config.policy)
    if profiles is None:
        profiles = (
            single_profile(extractor)
            if extractor is not None
            else build_profiles(extraction_config, settings)
        )
    engine = create_engine(settings.database_url)
    try:
        if migrate:
            await upgrade_to_head_async(engine)
    except BaseException:
        for fetcher in fetchers:
            await fetcher.aclose()
        await engine.dispose()
        raise

    uow = sql_unit_of_work_factory(engine)
    queries = SqlOfferQueries(engine)
    clock = clock or SystemClock()
    ids = ids or UuidIdGenerator()
    category_provider = categories or YamlCategoryProvider(settings.categories_file)
    analytics_queries = SqlAnalyticsQueries(engine)

    finalize_run = FinalizeRun(uow=uow, clock=clock, policy=policy)
    handlers: dict[JobType, JobHandler] = {
        JobType.DISCOVER_PAGE: DiscoverPageHandler(
            uow=uow, sources=listing_sources, clock=clock, ids=ids, policy=policy
        ),
        JobType.ENRICH_OFFER: EnrichOfferHandler(uow=uow, sources=listing_sources, clock=clock),
    }
    reconcile = ReconcileExtractions(
        uow=uow,
        profiles=profiles,
        categories=category_provider,
        clock=clock,
        ids=ids,
        policy=policy.extraction,
    )
    extraction_status = ExtractionStatus(
        uow=uow,
        profiles=profiles,
        categories=category_provider,
        clock=clock,
        selector=reconcile.selector,
        gated=policy.extraction.tiering.enabled,
    )
    q = build_query_use_cases(
        uow=uow,
        queries=analytics_queries,
        categories=category_provider,
        scoring=(scoring := YamlScoringProvider(settings.scoring_file, category_provider)),
        scoring_queries=analytics_queries,
        extraction=extraction_status,
    )
    resolve_components = ResolveComponents(uow=uow, clock=clock)
    tier_extractions = TierExtractions(
        uow=uow,
        clock=clock,
        categories=category_provider,
        rules=RuleBasedExtractor(),
        policy=policy.extraction,
        resolve=resolve_components,
        top_offers=ProvisionalTop(q.rank, scoring),
    )
    dispatcher = JobDispatcher(
        handlers=handlers, uow=uow, clock=clock, retry=policy.retry, finalize_run=finalize_run
    )
    return Container(
        settings=settings,
        policy=policy,
        engine=engine,
        uow=uow,
        clock=clock,
        categories=category_provider,
        queries=queries,
        sources=listing_sources,
        dispatcher=dispatcher,
        finalize_run=finalize_run,
        add_search=AddSavedSearch(
            uow=uow, categories=category_provider, sources=listing_sources, clock=clock
        ),
        start_run=StartRun(uow=uow, clock=clock, ids=ids),
        resume_run=ResumeRun(uow=uow, clock=clock, finalize_run=finalize_run),
        refresh_offer=RefreshOffer(uow=uow, clock=clock, ids=ids),
        finalize_idle_runs=FinalizeIdleRuns(uow=uow, finalize_run=finalize_run),
        list_offers=ListOffers(uow=uow, queries=queries, categories=category_provider),
        set_override=SetRelevanceOverride(uow=uow),
        q=q,
        profiles=profiles,
        reconcile_extractions=reconcile,
        tier_extractions=tier_extractions,
        poll_batches=PollBatches(
            uow=uow,
            profiles=profiles,
            categories=category_provider,
            clock=clock,
            ids=ids,
            policy=policy.extraction,
            reconcile=reconcile,
        ),
        extraction_status=extraction_status,
        force_reextract=ForceReextract(uow=uow, profiles=profiles, clock=clock),
        extraction_policy=policy.extraction,
        extraction_config_source=(
            "injected" if extractor is not None else extraction_config.source
        ),
        import_benchmarks=ImportBenchmarks(
            uow=uow,
            source=BlenderOpenDataSource(),
            downloader=BlenderOpenDataDownloader(settings.data_dir / "benchmarks"),
            clock=clock,
        ),
        list_components=ListComponents(uow=uow),
        resolve_components=resolve_components,
        component_resolution_status=ComponentResolutionStatus(uow=uow),
        add_component_alias=AddComponentAlias(uow=uow),
        log_level=settings.log_level,
        worker_poll_interval=settings.worker_poll_interval,
        _fetchers=fetchers,
    )


# ---------------------------------------------------------------------------- CLI wiring

EXPECTED_ERRORS: tuple[type[BaseException], ...] = (ApplicationError, DomainError, ConfigError)
"""Shown by the CLI as one red line with exit code 1 (traceback only with ``--debug``)."""


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors(include_url=False)
        )
        raise ConfigError(f"invalid environment settings: {details}") from error


def make_cli_context(
    settings: Settings | None = None,
    *,
    sources: Mapping[SourceId, ListingSource] | None = None,
    extractor: AttributeExtractor | None = None,
    profiles: ExtractionProfiles | None = None,
    categories: CategoryProvider | None = None,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> CliContext:
    """The context the CLI opens the application with; the keyword overrides are those of
    :func:`build_app` (tests inject a fake source and extractor here)."""

    async def open_app() -> Container:
        return await build_app(
            settings or load_settings(),
            sources=sources,
            extractor=extractor,
            profiles=profiles,
            categories=categories,
            clock=clock,
            ids=ids,
        )

    return CliContext(open_app=open_app, expected_errors=EXPECTED_ERRORS)


def cli() -> None:
    """Console-script entry point (`scrappy`)."""
    configure_streams()
    try:
        cli_app(obj=make_cli_context())
    except KeyboardInterrupt:  # second Ctrl+C: hard stop
        raise typer.Exit(130) from None

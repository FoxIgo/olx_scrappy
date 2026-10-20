"""What presentation needs from the composition root, as structural types.

``scrappy.main.Container`` satisfies :class:`Services`. Presentation never imports
``main`` or infrastructure (layer contract): ``main`` hands a :class:`CliContext` to the
Typer app, which opens the application per command and closes it afterwards.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from scrappy.application.jobs.dispatcher import JobDispatcher
from scrappy.application.policy import ExtractionPolicy
from scrappy.application.ports.extraction_backends import ExtractionProfiles
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics import QueryUseCases
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
    ReconcileExtractions,
    TierExtractions,
)
from scrappy.application.use_cases.finalize_run import FinalizeRun
from scrappy.application.use_cases.list_offers import ListOffers
from scrappy.application.use_cases.runs import FinalizeIdleRuns, ResumeRun, StartRun
from scrappy.application.use_cases.searches import AddSavedSearch, SetRelevanceOverride
from scrappy.application.use_cases.verify_offers import VerifyOffers


class Services(Protocol):
    @property
    def uow(self) -> UnitOfWorkFactory: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def dispatcher(self) -> JobDispatcher: ...
    @property
    def finalize_run(self) -> FinalizeRun: ...
    @property
    def add_search(self) -> AddSavedSearch: ...
    @property
    def start_run(self) -> StartRun: ...
    @property
    def resume_run(self) -> ResumeRun: ...
    @property
    def finalize_idle_runs(self) -> FinalizeIdleRuns: ...
    @property
    def list_offers(self) -> ListOffers: ...
    @property
    def verify_offers(self) -> VerifyOffers: ...
    @property
    def set_override(self) -> SetRelevanceOverride: ...
    @property
    def q(self) -> QueryUseCases:
        """The read-only agent query interface (``scrappy q``)."""
        ...

    @property
    def profiles(self) -> ExtractionProfiles: ...
    @property
    def reconcile_extractions(self) -> ReconcileExtractions: ...
    @property
    def tier_extractions(self) -> TierExtractions:
        """Rule pass + LLM gate (ADR 0012)."""
        ...

    @property
    def poll_batches(self) -> PollBatches: ...
    @property
    def extraction_status(self) -> ExtractionStatus: ...
    @property
    def force_reextract(self) -> ForceReextract: ...
    @property
    def extraction_policy(self) -> ExtractionPolicy: ...
    @property
    def extraction_config_source(self) -> str:
        """Where the profiles come from (extraction.yaml path or the settings fallback)."""
        ...

    @property
    def import_benchmarks(self) -> ImportBenchmarks: ...
    @property
    def list_components(self) -> ListComponents: ...
    @property
    def resolve_components(self) -> ResolveComponents: ...
    @property
    def component_resolution_status(self) -> ComponentResolutionStatus: ...
    @property
    def add_component_alias(self) -> AddComponentAlias: ...
    @property
    def log_level(self) -> str: ...
    @property
    def worker_poll_interval(self) -> float: ...
    @property
    def data_location(self) -> str:
        """Human-readable location of the database (for ``db upgrade`` / worker start)."""
        ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class CliContext:
    """Stored in the Typer context (``obj``). Tests build one with fakes injected."""

    open_app: Callable[[], Awaitable[Services]]
    expected_errors: tuple[type[BaseException], ...] = ()
    """Errors shown as a one-line red message with exit code 1 (no traceback)."""
    debug: bool = False

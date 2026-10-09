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
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics import QueryUseCases
from scrappy.application.use_cases.extractions import RequeueExtractions
from scrappy.application.use_cases.finalize_run import FinalizeRun
from scrappy.application.use_cases.list_offers import ListOffers
from scrappy.application.use_cases.runs import ResumeRun, StartRun
from scrappy.application.use_cases.searches import AddSavedSearch, SetRelevanceOverride


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
    def requeue_extractions(self) -> RequeueExtractions: ...
    @property
    def list_offers(self) -> ListOffers: ...
    @property
    def set_override(self) -> SetRelevanceOverride: ...
    @property
    def q(self) -> QueryUseCases:
        """The read-only agent query interface (``scrappy q``)."""
        ...

    @property
    def has_extractor(self) -> bool: ...
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

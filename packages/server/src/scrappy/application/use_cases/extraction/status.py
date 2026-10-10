"""ExtractionStatus: backlog, open batches, parked failures, profiles (ADR 0010 section 6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from scrappy.application.extraction.batch import ExtractionBatch
from scrappy.application.extraction.profile_status import ProfileStatus
from scrappy.application.ports.extraction_backends import (
    ExtractionProfile,
    ExtractionProfiles,
    ProfileHealth,
)
from scrappy.application.ports.repositories import BacklogQuery
from scrappy.application.ports.system import CategoryProvider, Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.extraction.common import ProfileSelector
from scrappy.domain.extraction import ExtractionState, ExtractionTarget
from scrappy.domain.search import SearchName


@dataclass(frozen=True, slots=True)
class ProfileView:
    profile: ExtractionProfile
    is_default: bool
    in_pool: bool
    """A lane of the parallel pool (ADR 0010 section 9)."""
    status: ProfileStatus
    quota_status: ProfileStatus
    """The status row that holds today's count and the daily block: the profile's own, or
    its quota group's (``profile.quota_group``) when the daily limit is shared."""
    health: ProfileHealth | None
    """``None`` unless a live check was requested."""
    blocked: bool


@dataclass(frozen=True, slots=True)
class ExtractionStatusReport:
    at: datetime
    backlog: int
    """Offers waiting for extraction (default profile's prompt version), any search."""
    search_backlog: int | None
    """Same, for the requested search."""
    open_batches: list[ExtractionBatch]
    recent_batches: list[ExtractionBatch]
    parked: list[ExtractionState]
    """Parked for their offer's *current* target, newest first."""
    profiles: list[ProfileView] = field(default_factory=list[ProfileView])


class ExtractionStatus:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        profiles: ExtractionProfiles,
        categories: CategoryProvider,
        clock: Clock,
        selector: ProfileSelector,
        gated: bool = False,
    ) -> None:
        self._uow = uow
        self._profiles = profiles
        self._categories = categories
        self._clock = clock
        self._selector = selector
        self._gated = gated
        """Tiering (ADR 0012): the backlog is only what the rule pass escalated."""

    @property
    def profiles(self) -> ExtractionProfiles:
        return self._profiles

    async def backlog(self, search: SearchName | None = None) -> int:
        """The backlog size (for one search, or all) as the default profile sees it."""
        catalog = await self._categories.catalog()
        prompt = self._profiles.get(self._profiles.default).prompt_version
        query = BacklogQuery(catalog, prompt, self._clock.now(), search=search, gated=self._gated)
        async with self._uow() as uow:
            return await uow.extraction_states.count_backlog(query)

    async def __call__(
        self,
        *,
        search: SearchName | None = None,
        check_health: bool = False,
        probe: bool = False,
        recent: int = 5,
    ) -> ExtractionStatusReport:
        now = self._clock.now()
        catalog = await self._categories.catalog()
        default = self._profiles.get(self._profiles.default)
        query = BacklogQuery(catalog, default.prompt_version, now, gated=self._gated)
        async with self._uow() as uow:
            backlog = await uow.extraction_states.count_backlog(query)
            search_backlog = (
                None
                if search is None
                else await uow.extraction_states.count_backlog(
                    BacklogQuery(
                        catalog, default.prompt_version, now, search=search, gated=self._gated
                    )
                )
            )
            open_batches = await uow.extraction_batches.list_open()
            recent_batches = [
                b
                for b in await uow.extraction_batches.list_recent(limit=recent + len(open_batches))
                if not b.is_open
            ][:recent]
            parked_states = await uow.extraction_states.list_parked()
            offers = await uow.offers.get_many([s.offer_id for s in parked_states])
            statuses = {s.profile: s for s in await uow.profile_status.list_all()}
        parked: list[ExtractionState] = []
        for state in parked_states:
            offer = offers.get(state.offer_id)
            if offer is None or offer.content_hash is None:
                continue
            if state.applies_to(ExtractionTarget.of(offer, catalog, default.prompt_version)):
                parked.append(state)

        pool = list(self._profiles.pool)
        views: list[ProfileView] = []
        for name in self._profiles.names():
            profile = self._profiles.get(name)
            status = statuses.get(name) or ProfileStatus.new(name, now)
            quota_status = (
                status
                if profile.quota_key == name
                else statuses.get(profile.quota_key) or ProfileStatus.new(profile.quota_key, now)
            )
            health = (
                await self._selector.health(name, refresh=True, probe=probe)
                if check_health
                else None
            )
            left = quota_status.remaining_today(
                profile.capabilities.daily_limit, now, profile.capabilities.quota_tz
            )
            views.append(
                ProfileView(
                    profile=profile,
                    is_default=name == self._profiles.default,
                    in_pool=name in pool,
                    status=status,
                    quota_status=quota_status,
                    health=health,
                    blocked=status.is_blocked(now) or quota_status.is_blocked(now) or left == 0,
                )
            )
        return ExtractionStatusReport(
            at=now,
            backlog=backlog,
            search_backlog=search_backlog,
            open_batches=open_batches,
            recent_batches=recent_batches,
            parked=parked,
            profiles=views,
        )

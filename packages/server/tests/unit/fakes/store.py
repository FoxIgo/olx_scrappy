"""In-memory persistence: repositories, job queue and unit of work.

Reference behaviour for adapter authors:

* A unit of work works on a private deep copy of the committed state and publishes it on
  ``commit`` (serialised, last commit wins: like SQLite's single writer). Without commit,
  everything is discarded.
* Repositories store and return *copies*, so mutating a returned entity changes nothing
  until ``save`` (catches handlers that forget to save).
* The job queue enforces dedup keys forever, claims FIFO by ``(available_at, seq)``.
* The extraction backlog applies the domain rule ``extraction_due`` to every offer with
  content, ordered by ``last_seen_at`` newest first, then ``(source, external_id)``.
"""

from __future__ import annotations

import copy
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import TracebackType
from typing import Self

from scrappy.application.extraction.batch import ExtractionBatch
from scrappy.application.extraction.profile_status import ProfileStatus
from scrappy.application.jobs.model import Job, JobId, JobResult, JobStatus, JobType
from scrappy.application.ports.components import (
    ComponentWithBenchmarks,
    ResolutionTask,
    UnresolvedText,
)
from scrappy.application.ports.repositories import BacklogQuery
from scrappy.domain.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    OfferComponentLink,
    ResolutionMethod,
    component_slug,
)
from scrappy.domain.extraction import ExtractionState, OfferExtraction, extraction_due
from scrappy.domain.offer import Offer, OfferId, OfferSnapshot
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import RunId


@dataclass
class StoreState:
    offers: dict[OfferId, Offer] = field(default_factory=dict[OfferId, Offer])
    snapshots: list[OfferSnapshot] = field(default_factory=list[OfferSnapshot])
    searches: dict[SearchName, SavedSearch] = field(default_factory=dict[SearchName, SavedSearch])
    links: dict[tuple[SearchName, OfferId], SearchOffer] = field(
        default_factory=dict[tuple[SearchName, OfferId], SearchOffer]
    )
    extractions: list[OfferExtraction] = field(default_factory=list[OfferExtraction])
    runs: dict[RunId, ScrapeRun] = field(default_factory=dict[RunId, ScrapeRun])
    jobs: dict[JobId, Job] = field(default_factory=dict[JobId, Job])
    job_seq: dict[JobId, int] = field(default_factory=dict[JobId, int])
    dedup_keys: set[str] = field(default_factory=set[str])
    next_seq: int = 0
    extraction_states: dict[OfferId, ExtractionState] = field(
        default_factory=dict[OfferId, ExtractionState]
    )
    batches: dict[str, ExtractionBatch] = field(default_factory=dict[str, ExtractionBatch])
    """Insertion order = creation order (dicts keep it)."""
    profile_status: dict[str, ProfileStatus] = field(default_factory=dict[str, ProfileStatus])
    components: dict[str, Component] = field(default_factory=dict[str, Component])
    component_aliases: dict[tuple[ComponentKind, str], ComponentAlias] = field(
        default_factory=dict[tuple[ComponentKind, str], ComponentAlias]
    )
    benchmarks: dict[tuple[str, str, str], Benchmark] = field(
        default_factory=dict[tuple[str, str, str], Benchmark]
    )
    offer_components: dict[tuple[OfferId, ComponentKind], OfferComponentLink] = field(
        default_factory=dict[tuple[OfferId, ComponentKind], OfferComponentLink]
    )


class InMemoryStore:
    """Committed state shared by all units of work (and the read-side fake)."""

    def __init__(self) -> None:
        self.state = StoreState()
        self.commits = 0

    def uow(self) -> InMemoryUnitOfWork:
        """Use as the ``UnitOfWorkFactory``: ``uow=store.uow``."""
        return InMemoryUnitOfWork(self)


def _copy[T](value: T) -> T:
    return copy.deepcopy(value)


class InMemoryOfferRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, offer_id: OfferId) -> Offer | None:
        offer = self._s.offers.get(offer_id)
        return _copy(offer) if offer else None

    async def get_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, Offer]:
        return {i: _copy(self._s.offers[i]) for i in offer_ids if i in self._s.offers}

    async def save(self, offer: Offer) -> None:
        self._s.offers[offer.id] = _copy(offer)

    async def add_snapshot(self, snapshot: OfferSnapshot) -> None:
        self._s.snapshots.append(snapshot)

    async def list_snapshots(self, offer_id: OfferId) -> list[OfferSnapshot]:
        return [s for s in self._s.snapshots if s.offer_id == offer_id]

    async def list_with_content(self, *, after: OfferId | None, limit: int) -> list[Offer]:
        def key(i: OfferId) -> tuple[str, str]:
            return (i.source.value, i.external_id)

        ids = sorted((i for i, o in self._s.offers.items() if o.content_hash), key=key)
        if after is not None:
            ids = [i for i in ids if key(i) > key(after)]
        return [_copy(self._s.offers[i]) for i in ids[:limit]]


class InMemorySavedSearchRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, name: SearchName) -> SavedSearch | None:
        search = self._s.searches.get(name)
        return _copy(search) if search else None

    async def save(self, search: SavedSearch) -> None:
        self._s.searches[search.name] = _copy(search)

    async def list_all(self) -> list[SavedSearch]:
        return [_copy(self._s.searches[n]) for n in sorted(self._s.searches)]


class InMemorySearchOfferRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, search: SearchName, offer_id: OfferId) -> SearchOffer | None:
        link = self._s.links.get((search, offer_id))
        return _copy(link) if link else None

    async def get_many(
        self, search: SearchName, offer_ids: Collection[OfferId]
    ) -> dict[OfferId, SearchOffer]:
        return {
            i: _copy(self._s.links[(search, i)]) for i in offer_ids if (search, i) in self._s.links
        }

    async def save(self, link: SearchOffer) -> None:
        self._s.links[(link.search, link.offer_id)] = _copy(link)

    async def list_for_offer(self, offer_id: OfferId) -> list[SearchOffer]:
        links = [link for (_, o), link in self._s.links.items() if o == offer_id]
        return [_copy(link) for link in sorted(links, key=lambda link: link.search)]


class InMemoryExtractionRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def add(self, extraction: OfferExtraction) -> None:
        self._s.extractions.append(extraction)

    async def latest(self, offer_id: OfferId) -> OfferExtraction | None:
        best: OfferExtraction | None = None
        for extraction in self._s.extractions:  # insertion order breaks ties: last wins
            if extraction.offer_id == offer_id and (
                best is None or extraction.provenance.extracted_at >= best.provenance.extracted_at
            ):
                best = extraction
        return best

    async def latest_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, OfferExtraction]:
        result: dict[OfferId, OfferExtraction] = {}
        for offer_id in offer_ids:
            latest = await self.latest(offer_id)
            if latest is not None:
                result[offer_id] = latest
        return result


class InMemoryScrapeRunRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, run_id: RunId) -> ScrapeRun | None:
        run = self._s.runs.get(run_id)
        return _copy(run) if run else None

    async def save(self, run: ScrapeRun) -> None:
        self._s.runs[run.id] = _copy(run)

    async def find_running(self, search: SearchName) -> ScrapeRun | None:
        for run in self._s.runs.values():
            if run.search == search and run.is_running:
                return _copy(run)
        return None

    async def list_for_search(self, search: SearchName, *, limit: int) -> list[ScrapeRun]:
        runs = [r for r in self._s.runs.values() if r.search == search]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return [_copy(r) for r in runs[:limit]]

    async def list_running(self) -> list[ScrapeRun]:
        runs = [r for r in self._s.runs.values() if r.is_running]
        runs.sort(key=lambda r: r.started_at)
        return [_copy(r) for r in runs]


def _latest_of(state: StoreState, offer_id: OfferId) -> OfferExtraction | None:
    best: OfferExtraction | None = None
    for extraction in state.extractions:
        if extraction.offer_id == offer_id and (
            best is None or extraction.provenance.extracted_at >= best.provenance.extracted_at
        ):
            best = extraction
    return best


def _routed(state: ExtractionState | None, query: BacklogQuery) -> bool:
    pinned = state.requested_profile if state is not None and state.forced else None
    if query.pinned_only:
        return pinned is not None and pinned == query.profile
    return query.profile is None or pinned is None or pinned == query.profile


class InMemoryExtractionStateRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, offer_id: OfferId) -> ExtractionState | None:
        found = self._s.extraction_states.get(offer_id)
        return _copy(found) if found else None

    async def get_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, ExtractionState]:
        return {
            i: _copy(self._s.extraction_states[i])
            for i in offer_ids
            if i in self._s.extraction_states
        }

    async def save(self, state: ExtractionState) -> None:
        self._s.extraction_states[state.offer_id] = _copy(state)

    async def backlog(self, query: BacklogQuery, *, limit: int | None = None) -> list[OfferId]:
        linked = (
            None if query.search is None else {o for (s, o) in self._s.links if s == query.search}
        )
        offers = [
            o
            for o in self._s.offers.values()
            if o.content_hash is not None and (linked is None or o.id in linked)
        ]
        offers.sort(
            key=lambda o: (-o.last_seen_at.timestamp(), o.id.source.value, o.id.external_id)
        )
        result: list[OfferId] = []
        for offer in offers:
            state = self._s.extraction_states.get(offer.id)
            if not _routed(state, query):
                continue
            latest = _latest_of(self._s, offer.id)
            if extraction_due(
                offer,
                latest,
                state,
                query.catalog,
                query.prompt_version,
                query.now,
                gated=query.gated,
            ):
                result.append(offer.id)
                if limit is not None and len(result) >= limit:
                    break
        return result

    async def count_backlog(self, query: BacklogQuery) -> int:
        return len(await self.backlog(query))

    async def claim(
        self, query: BacklogQuery, *, owner: str, lease_until: datetime, limit: int
    ) -> list[OfferId]:
        if limit < 1:
            return []
        claimed = await self.backlog(query, limit=limit)
        for offer_id in claimed:
            state = self._s.extraction_states.get(offer_id) or ExtractionState.new(
                offer_id, query.now
            )
            state.lease(owner, lease_until, query.now)
            self._s.extraction_states[offer_id] = state
        return claimed

    async def release_owner(self, owner: str, *, now: datetime) -> int:
        count = 0
        for state in self._s.extraction_states.values():
            if state.lease_owner == owner:
                state.release(now)
                count += 1
        return count

    async def rules_backlog(self, version: str, *, limit: int | None = None) -> list[OfferId]:
        offers = [o for o in self._s.offers.values() if o.content_hash is not None]
        offers.sort(
            key=lambda o: (-o.last_seen_at.timestamp(), o.id.source.value, o.id.external_id)
        )
        result: list[OfferId] = []
        for offer in offers:
            state = self._s.extraction_states.get(offer.id)
            assert offer.content_hash is not None
            if state is None or not state.rules_done(offer.content_hash, version):
                result.append(offer.id)
                if limit is not None and len(result) >= limit:
                    break
        return result

    async def list_parked(self) -> list[ExtractionState]:
        parked = [s for s in self._s.extraction_states.values() if s.parked]
        parked.sort(
            key=lambda s: (
                -s.updated_at.timestamp(),
                s.offer_id.source.value,
                s.offer_id.external_id,
            )
        )
        return [_copy(s) for s in parked]


class InMemoryExtractionBatchRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, batch_id: str) -> ExtractionBatch | None:
        found = self._s.batches.get(batch_id)
        return _copy(found) if found else None

    async def save(self, batch: ExtractionBatch) -> None:
        self._s.batches[batch.id] = _copy(batch)  # an update keeps the creation position

    async def list_open(self, profile: str | None = None) -> list[ExtractionBatch]:
        return [
            _copy(b)
            for b in self._s.batches.values()
            if b.is_open and (profile is None or b.profile == profile)
        ]

    async def list_recent(self, *, limit: int) -> list[ExtractionBatch]:
        return [_copy(b) for b in reversed(self._s.batches.values())][:limit]


class InMemoryProfileStatusRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def get(self, profile: str) -> ProfileStatus | None:
        found = self._s.profile_status.get(profile)
        return _copy(found) if found else None

    async def save(self, status: ProfileStatus) -> None:
        self._s.profile_status[status.profile] = _copy(status)

    async def list_all(self) -> list[ProfileStatus]:
        return [_copy(self._s.profile_status[n]) for n in sorted(self._s.profile_status)]


class InMemoryComponentRepository:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def add_missing(self, components: Sequence[Component]) -> int:
        added = 0
        for component in components:
            if component.id not in self._s.components:
                self._s.components[component.id] = component
                added += 1
        return added

    async def add_aliases(self, aliases: Sequence[ComponentAlias]) -> int:
        added = 0
        for alias in aliases:
            key = (alias.kind, alias.alias)
            if key not in self._s.component_aliases:
                self._s.component_aliases[key] = alias
                added += 1
        return added

    async def save_benchmarks(self, benchmarks: Sequence[Benchmark]) -> None:
        for benchmark in benchmarks:
            self._s.benchmarks[(benchmark.component_id, benchmark.source, benchmark.metric)] = (
                benchmark
            )

    async def get(self, component_id: str) -> Component | None:
        return self._s.components.get(component_id)

    async def find(
        self, *, kind: ComponentKind | None = None, search: str | None = None
    ) -> list[ComponentWithBenchmarks]:
        needle = search.lower() if search else None
        slug_needle = component_slug(search, "gpu") if search else None
        found: list[ComponentWithBenchmarks] = []
        for component in self._s.components.values():
            if kind is not None and component.kind is not kind:
                continue
            if (
                needle
                and needle not in component.name.lower()
                and not (slug_needle and slug_needle in component.slug)
            ):
                continue
            scores = tuple(b for b in self._s.benchmarks.values() if b.component_id == component.id)
            found.append(ComponentWithBenchmarks(component, scores))
        found.sort(key=lambda c: c.sort_key)
        return found

    async def list_components(self) -> list[Component]:
        return list(self._s.components.values())

    async def list_aliases(self) -> list[ComponentAlias]:
        return list(self._s.component_aliases.values())

    async def save_alias(self, alias: ComponentAlias) -> None:
        self._s.component_aliases[(alias.kind, alias.alias)] = alias

    def _tasks(self, resolver_version: int) -> list[ResolutionTask]:
        latest: dict[OfferId, OfferExtraction] = {}
        for extraction in self._s.extractions:
            known = latest.get(extraction.offer_id)
            if known is None or extraction.provenance.extracted_at >= known.provenance.extracted_at:
                latest[extraction.offer_id] = extraction
        tasks: list[ResolutionTask] = []
        for kind in (ComponentKind.GPU, ComponentKind.CPU):
            for offer_id, extraction in sorted(
                latest.items(),
                key=lambda item: (
                    -item[1].provenance.extracted_at.timestamp(),
                    item[0].source.value,
                    item[0].external_id,
                ),
            ):
                raw = extraction.attributes.get(kind.value)
                if raw is None or not str(raw).strip():
                    continue
                link = self._s.offer_components.get((offer_id, kind))
                if (
                    link is None
                    or link.raw_text != str(raw)
                    or link.resolver_version < resolver_version
                ):
                    vram = extraction.attributes.get("vram_gb")
                    tasks.append(
                        ResolutionTask(
                            offer_id,
                            extraction.category.value,
                            kind,
                            str(raw),
                            vram if isinstance(vram, int) else None,
                        )
                    )
        return tasks

    async def resolution_backlog(
        self, resolver_version: int, *, limit: int | None = None
    ) -> list[ResolutionTask]:
        tasks = self._tasks(resolver_version)
        return tasks if limit is None else tasks[:limit]

    async def count_resolution_backlog(self, resolver_version: int) -> int:
        return len(self._tasks(resolver_version))

    async def save_links(self, links: Sequence[OfferComponentLink]) -> None:
        for link in links:
            self._s.offer_components[(link.offer_id, link.kind)] = link

    async def linked_raw_texts(self, kind: ComponentKind) -> list[str]:
        return list({k.raw_text for (_, kd), k in self._s.offer_components.items() if kd is kind})

    async def mark_links_stale(self, kind: ComponentKind, raw_texts: Sequence[str]) -> int:
        wanted = set(raw_texts)
        changed = 0
        for key, link in list(self._s.offer_components.items()):
            if key[1] is kind and link.raw_text in wanted:
                self._s.offer_components[key] = replace(link, resolver_version=0)
                changed += 1
        return changed

    async def link_counts(self) -> dict[tuple[ComponentKind, ResolutionMethod], int]:
        counts: dict[tuple[ComponentKind, ResolutionMethod], int] = {}
        for (_, kind), link in self._s.offer_components.items():
            key = (kind, link.resolution.method)
            counts[key] = counts.get(key, 0) + 1
        return counts

    async def top_unresolved(self, limit: int) -> list[UnresolvedText]:
        counts: dict[tuple[ComponentKind, str], int] = {}
        for (_, kind), link in self._s.offer_components.items():
            if link.resolution.method is ResolutionMethod.UNRESOLVED:
                key = (kind, link.raw_text.lower())
                counts[key] = counts.get(key, 0) + 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0][1]))
        return [UnresolvedText(kind, raw, n) for (kind, raw), n in ordered[:limit]]


class InMemoryJobQueue:
    def __init__(self, state: StoreState) -> None:
        self._s = state

    async def enqueue(self, job: Job) -> bool:
        if job.dedup_key in self._s.dedup_keys:
            return False
        if job.id in self._s.jobs:
            raise ValueError(f"duplicate job id {job.id}")
        self._s.dedup_keys.add(job.dedup_key)
        self._s.jobs[job.id] = replace(job, status=JobStatus.PENDING)
        self._s.job_seq[job.id] = self._s.next_seq
        self._s.next_seq += 1
        return True

    async def claim(self, types: Collection[JobType], *, limit: int, now: datetime) -> list[Job]:
        due = [
            job
            for job in self._s.jobs.values()
            if job.status is JobStatus.PENDING
            and job.available_at <= now
            and (not types or job.type in types)
        ]
        due.sort(key=lambda job: (job.available_at, self._s.job_seq[job.id]))
        claimed: list[Job] = []
        for job in due[:limit]:
            updated = replace(job, status=JobStatus.RUNNING, attempts=job.attempts + 1)
            self._s.jobs[job.id] = updated
            claimed.append(updated)
        return claimed

    async def complete(self, job_id: JobId, result: JobResult, *, now: datetime) -> None:
        job = self._s.jobs[job_id]
        self._s.jobs[job_id] = replace(job, status=JobStatus.DONE, result=result, finished_at=now)

    async def fail(
        self,
        job_id: JobId,
        *,
        error: str,
        retry_at: datetime | None,
        result: JobResult | None = None,
        now: datetime,
    ) -> None:
        job = self._s.jobs[job_id]
        if retry_at is not None:
            updated = replace(
                job, status=JobStatus.PENDING, available_at=retry_at, last_error=error
            )
        else:
            updated = replace(
                job, status=JobStatus.FAILED, last_error=error, result=result, finished_at=now
            )
        self._s.jobs[job_id] = updated

    async def get(self, job_id: JobId) -> Job | None:
        return self._s.jobs.get(job_id)

    async def count_unfinished(self, run_id: RunId) -> int:
        return sum(
            1 for job in self._s.jobs.values() if job.run_id == run_id and job.status.is_unfinished
        )

    async def list_for_run(self, run_id: RunId) -> list[Job]:
        jobs = [job for job in self._s.jobs.values() if job.run_id == run_id]
        return sorted(jobs, key=lambda job: self._s.job_seq[job.id])

    async def requeue_failed(self, run_id: RunId, *, now: datetime) -> int:
        count = 0
        for job in list(self._s.jobs.values()):
            if job.run_id == run_id and job.status in (JobStatus.FAILED, JobStatus.RUNNING):
                self._s.jobs[job.id] = replace(
                    job,
                    status=JobStatus.PENDING,
                    attempts=0,
                    available_at=now,
                    result=None,
                    finished_at=None,
                )
                count += 1
        return count

    async def requeue_orphaned(self, *, now: datetime) -> int:
        count = 0
        for job in list(self._s.jobs.values()):
            if job.status is JobStatus.RUNNING:
                self._s.jobs[job.id] = replace(job, status=JobStatus.PENDING, available_at=now)
                count += 1
        return count


class InMemoryUnitOfWork:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._state: StoreState | None = None
        self._committed = False

    def _working(self) -> StoreState:
        if self._state is None:
            raise RuntimeError("use the unit of work inside 'async with'")
        return self._state

    @property
    def offers(self) -> InMemoryOfferRepository:
        return InMemoryOfferRepository(self._working())

    @property
    def searches(self) -> InMemorySavedSearchRepository:
        return InMemorySavedSearchRepository(self._working())

    @property
    def search_offers(self) -> InMemorySearchOfferRepository:
        return InMemorySearchOfferRepository(self._working())

    @property
    def extractions(self) -> InMemoryExtractionRepository:
        return InMemoryExtractionRepository(self._working())

    @property
    def runs(self) -> InMemoryScrapeRunRepository:
        return InMemoryScrapeRunRepository(self._working())

    @property
    def jobs(self) -> InMemoryJobQueue:
        return InMemoryJobQueue(self._working())

    @property
    def extraction_states(self) -> InMemoryExtractionStateRepository:
        return InMemoryExtractionStateRepository(self._working())

    @property
    def extraction_batches(self) -> InMemoryExtractionBatchRepository:
        return InMemoryExtractionBatchRepository(self._working())

    @property
    def profile_status(self) -> InMemoryProfileStatusRepository:
        return InMemoryProfileStatusRepository(self._working())

    @property
    def components(self) -> InMemoryComponentRepository:
        return InMemoryComponentRepository(self._working())

    async def __aenter__(self) -> Self:
        if self._state is not None:
            raise RuntimeError("a unit of work is single-use")
        self._state = copy.deepcopy(self._store.state)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._store.state = copy.deepcopy(self._working())
        self._store.commits += 1
        self._committed = True

    async def rollback(self) -> None:
        """Discard uncommitted writes; the unit of work sees committed state again."""
        if self._state is not None:
            self._state = copy.deepcopy(self._store.state)
        self._committed = False

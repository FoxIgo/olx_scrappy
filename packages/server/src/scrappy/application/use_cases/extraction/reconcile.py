"""ReconcileExtractions: one tick of the extractor loop (ADR 0010 sections 1, 2, 4, 5, 8).

Per tick (ADR 0010 section 9: the parallel pool supersedes the sequential chain):

1. Submit QUEUED batches (bisect halves, or batches whose submit was interrupted).
2. Start one **lane** per profile of the pool (``--profile`` override: just that one), all
   concurrently. A lane is unavailable when blocked by quota, out of daily requests (its own
   or its quota group's) or failing its health check; it then does nothing this tick while
   the other lanes continue.
3. A lane counts the backlog for its profile and chooses the mode: ``batch`` (claim up to
   ``batch.max_size`` -> persist the batch as QUEUED with the leases -> persist SUBMITTING ->
   POST -> SUBMITTED) or ``sync`` (claim small chunks from the shared backlog, call the
   extractor with the profile's concurrency limit and rate limit, ingest each answer). Lanes
   never take the same offer: claiming leases it (ADR 0010 section 3).
4. When a profile turns out unusable mid-tick (QUOTA / UNAVAILABLE answers) its claimed
   offers are released without penalty and only that lane stops.
5. Forced work pinned to a profile outside the pool (``extract force --profile``) gets a
   lane of its own, restricted to the pinned offers.

Never does network I/O inside a unit of work.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from scrappy.application.extraction.batch import BatchItem, BatchStatus, ExtractionBatch
from scrappy.application.extraction.ingest import (
    IngestContext,
    IngestResult,
    IngestStatus,
    ingest_outcome,
)
from scrappy.application.extraction.prepare import prepare_extraction_input
from scrappy.application.extraction.profile_status import ProfileStatus, next_reset
from scrappy.application.policy import ExtractionPolicy
from scrappy.application.ports.extraction_backends import (
    BatchBackendError,
    BatchRequestItem,
    ExtractionMode,
    ExtractionProfile,
    ExtractionProfiles,
)
from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.application.ports.repositories import BacklogQuery
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from scrappy.application.use_cases.extraction.common import (
    Monotonic,
    ProfileSelector,
    RequestPacer,
    Sleep,
)
from scrappy.domain.category import CategoryCatalog
from scrappy.domain.extraction import ExtractionState, ExtractionTarget, TokenUsage
from scrappy.domain.offer import OfferId

MAX_NOTES = 20


@dataclass(slots=True)
class ReconcileReport:
    profile: str | None = None
    """The profile that did the (main) work, if any."""
    mode: str | None = None
    """``sync`` / ``batch`` / None when nothing was done."""
    backlog: int = 0
    """Backlog size seen at the start of the tick (for the chosen profile)."""
    stored: int = 0
    failed: int = 0
    released: int = 0
    stale: int = 0
    stored_by_profile: dict[str, int] = field(default_factory=dict[str, int])
    """Stored extractions per lane (profile name)."""
    retry_in: float | None = None
    """When ``unavailable``: seconds until the soonest quota block lifts, if any lane has one."""
    batches_submitted: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    notes: list[str] = field(default_factory=list[str])
    unavailable: bool = False
    """True when there was work but no profile could take it."""

    @property
    def processed(self) -> int:
        return self.stored + self.failed + self.released + self.stale

    @property
    def did_work(self) -> bool:
        return self.processed > 0 or self.batches_submitted > 0

    def note(self, text: str) -> None:
        if len(self.notes) < MAX_NOTES:
            self.notes.append(text)

    def count(self, result: IngestResult, profile: str | None = None) -> None:
        match result.status:
            case IngestStatus.STORED:
                self.stored += 1
                if profile is not None:
                    self.stored_by_profile[profile] = self.stored_by_profile.get(profile, 0) + 1
            case IngestStatus.FAILED:
                self.failed += 1
            case IngestStatus.RELEASED:
                self.released += 1
            case IngestStatus.STALE:
                self.stale += 1


class _ProfileUnusable(Exception):
    """The profile answered QUOTA / UNAVAILABLE: stop using it this tick."""


class _Budget:
    """How many offers the tick may still claim in total, shared by all lanes
    (``scrappy extract --inline --max N``). ``None`` = unlimited."""

    def __init__(self, limit: int | None) -> None:
        self.left = limit

    @property
    def exhausted(self) -> bool:
        return self.left is not None and self.left <= 0

    def take(self, wanted: int) -> int:
        if self.left is None:
            return wanted
        got = max(0, min(wanted, self.left))
        self.left -= got
        return got

    def refund(self, count: int) -> None:
        if self.left is not None:
            self.left += count


@dataclass(slots=True)
class _Lane:
    profile: ExtractionProfile
    pinned_only: bool
    outcome: str = "idle"
    """``idle`` (no work), ``worked``, ``unusable`` (blocked / unavailable / stopped)."""
    retry_in: timedelta | None = None


class ReconcileExtractions:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        profiles: ExtractionProfiles,
        categories: CategoryProvider,
        clock: Clock,
        ids: IdGenerator,
        policy: ExtractionPolicy,
        selector: ProfileSelector | None = None,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._uow = uow
        self._profiles = profiles
        self._categories = categories
        self._clock = clock
        self._ids = ids
        self._policy = policy
        self.selector = selector or ProfileSelector(
            profiles=profiles, uow=uow, clock=clock, health_ttl=policy.health_ttl
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._owner = f"sync:{worker_id or ids.new_id()}"
        self._pacers: dict[str, RequestPacer] = {}
        self._inflight: dict[str, int] = {}
        # calls in flight per quota key: lanes sharing a daily limit cannot overshoot it
        self._backlog_since: dict[str, datetime] = {}

    # ------------------------------------------------------------------ entry point
    async def __call__(
        self,
        *,
        profile: str | None = None,
        flush: bool = False,
        stop: asyncio.Event | None = None,
        limit: int | None = None,
    ) -> ReconcileReport:
        """One tick. ``flush`` submits a batch even below ``batch.min_size``
        (``scrappy extract --inline``). ``limit`` caps how many offers this tick claims
        in total, across profiles (``scrappy extract --inline --max N``)."""
        report = ReconcileReport()
        catalog = await self._categories.catalog()
        await self.submit_queued(report, catalog)

        if profile is not None:
            lanes = [_Lane(self._profiles.get(profile), pinned_only=False)]
        else:
            pool = list(self._profiles.pool)
            lanes = [_Lane(self._profiles.get(name), pinned_only=False) for name in pool]
            lanes += [
                _Lane(self._profiles.get(name), pinned_only=True)
                for name in self._profiles.names()
                if name not in pool
            ]
        budget = _Budget(limit)
        active = lanes
        for _ in range(len(lanes) + 1):
            released = report.released
            await asyncio.gather(
                *(
                    self._run_lane(lane, catalog, report, budget, flush=flush, stop=stop)
                    for lane in active
                )
            )
            # A lane that stopped gave its claimed offers back (no penalty). The other lanes
            # may have found nothing to claim while those were leased: let them look again.
            if report.released == released or budget.exhausted or (stop and stop.is_set()):
                break
            active = [lane for lane in lanes if lane.outcome != "unusable"]
            if not active:
                break
        working = [lane for lane in lanes if lane.outcome != "idle"]
        worked = [lane.profile.name for lane in working if lane.outcome == "worked"]
        report.profile = "+".join(worked) or None
        report.unavailable = bool(working) and all(lane.outcome == "unusable" for lane in working)
        if report.unavailable:
            waits = [lane.retry_in for lane in working if lane.retry_in is not None]
            report.retry_in = min(waits).total_seconds() if waits else None
        return report

    async def _run_lane(
        self,
        lane: _Lane,
        catalog: CategoryCatalog,
        report: ReconcileReport,
        budget: _Budget,
        *,
        flush: bool,
        stop: asyncio.Event | None,
    ) -> None:
        """One profile's share of the tick. Never raises for a profile problem."""
        name = lane.profile.name
        query = self._query(catalog, lane.profile, pinned_only=lane.pinned_only)
        if not await self._count(query) or budget.exhausted:
            return
        lane.outcome = "unusable"
        availability = await self.selector.availability(name)
        if not availability.ok:
            what = "forced work pinned to" if lane.pinned_only else "profile"
            report.note(f"{what} {name} unavailable: {availability.reason}")
            lane.retry_in = availability.retry_in
            return
        try:
            await self._work(lane.profile, query, report, budget, flush=flush, stop=stop)
        except _ProfileUnusable as error:
            report.note(f"profile {name} stopped: {error}")
            lane.retry_in = (await self.selector.availability(name)).retry_in
        else:
            lane.outcome = "worked"

    # ------------------------------------------------------------------ helpers
    def _query(
        self, catalog: CategoryCatalog, profile: ExtractionProfile, *, pinned_only: bool = False
    ) -> BacklogQuery:
        return BacklogQuery(
            catalog=catalog,
            prompt_version=profile.prompt_version,
            now=self._clock.now(),
            profile=profile.name,
            pinned_only=pinned_only,
        )

    async def _count(self, query: BacklogQuery) -> int:
        async with self._uow() as uow:
            return await uow.extraction_states.count_backlog(query)

    def _pacer(self, profile: ExtractionProfile) -> RequestPacer:
        pacer = self._pacers.get(profile.name)
        if pacer is None:
            rate = profile.capabilities.rate_limit_per_minute
            pacer = (
                RequestPacer(rate, sleep=self._sleep, monotonic=self._monotonic)
                if self._monotonic is not None
                else RequestPacer(rate, sleep=self._sleep)
            )
            self._pacers[profile.name] = pacer
        return pacer

    def _context(self, profile: ExtractionProfile, catalog: CategoryCatalog) -> IngestContext:
        return IngestContext(
            profile=profile.name,
            provider=profile.provider,
            prompt_version=profile.prompt_version,
            catalog_fingerprint=catalog.fingerprint,
            owner=self._owner,
        )

    async def _work(
        self,
        profile: ExtractionProfile,
        query: BacklogQuery,
        report: ReconcileReport,
        budget: _Budget,
        *,
        flush: bool,
        stop: asyncio.Event | None,
    ) -> None:
        backlog = await self._count(query)
        now = self._clock.now()
        report.backlog = max(report.backlog, backlog)
        since = self._backlog_since.setdefault(profile.name, now)
        waited = now - since >= profile.batch.max_wait
        if profile.wants_batch(backlog, waited_long=waited, flush=flush):
            report.mode = report.mode or "batch"
            await self._submit_new_batches(profile, query, report, backlog, budget)
        elif profile.batch_backend is not None and profile.mode is ExtractionMode.BATCH:
            report.note(
                f"profile {profile.name}: {backlog} offer(s) wait for a batch "
                f"(min_size {profile.batch.min_size})"
            )
        else:
            report.mode = report.mode or "sync"
            await self._sync(profile, query, report, stop, budget)
        if await self._count(query) == 0:
            self._backlog_since.pop(profile.name, None)

    # ------------------------------------------------------------------ sync mode
    async def _sync(
        self,
        profile: ExtractionProfile,
        query: BacklogQuery,
        report: ReconcileReport,
        stop: asyncio.Event | None,
        budget: _Budget,
    ) -> None:
        total = self._policy.max_items_per_tick
        semaphore = asyncio.Semaphore(profile.capabilities.concurrency)
        chunk = max(2 * profile.capabilities.concurrency, 1)
        pacer = self._pacer(profile)
        processed = 0
        while processed < total:
            if stop is not None and stop.is_set():
                report.note("stop requested: remaining backlog left for the next run")
                return
            limit = min(chunk, total - processed)
            left = await self._requests_left(profile)
            if left is not None:
                if left <= 0:
                    raise _ProfileUnusable("daily request limit used up")
                limit = min(limit, left)
            limit = budget.take(limit)
            if limit == 0:
                return
            catalog = query.catalog
            now = self._clock.now()
            query = BacklogQuery(
                catalog, query.prompt_version, now, query.search, query.profile, query.pinned_only
            )
            async with self._uow() as uow:
                claimed = await uow.extraction_states.claim(
                    query, owner=self._owner, lease_until=now + self._policy.sync_lease, limit=limit
                )
                offers = await uow.offers.get_many(claimed)
                await uow.commit()
            budget.refund(limit - len(claimed))
            if not claimed:
                return
            inputs: list[ExtractionInput] = []
            for offer_id in claimed:
                offer = offers.get(offer_id)
                if offer is None or offer.content_hash is None:
                    continue
                inputs.append(
                    prepare_extraction_input(
                        offer, catalog, max_chars=self._policy.description_max_chars
                    )
                )

            async def call(request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
                async with semaphore:
                    await pacer.wait()
                    try:
                        return await profile.extractor.extract(request)
                    except Exception as error:  # adapters must not raise; stay robust
                        return ExtractionRejection(
                            f"extractor crashed: {type(error).__name__}: {error}",
                            retryable=True,
                            model=profile.model,
                        )

            key = profile.quota_key
            self._inflight[key] = self._inflight.get(key, 0) + len(inputs)
            try:
                answers = await asyncio.gather(*(call(r) for r in inputs))
                unusable = await self._store_sync(
                    profile, catalog, claimed, inputs, answers, report
                )
            finally:
                self._inflight[key] -= len(inputs)
            processed += len(claimed)
            if unusable is not None:
                await self._mark_unusable(profile, unusable)
                raise _ProfileUnusable(unusable.reason)

    async def _store_sync(
        self,
        profile: ExtractionProfile,
        catalog: CategoryCatalog,
        claimed: Sequence[OfferId],
        inputs: Sequence[ExtractionInput],
        answers: Sequence[ExtractionResult | ExtractionRejection],
        report: ReconcileReport,
    ) -> ExtractionRejection | None:
        now = self._clock.now()
        context = self._context(profile, catalog)
        unusable: ExtractionRejection | None = None
        answered = {request.offer_id for request in inputs}
        async with self._uow() as uow:
            for request, answer in zip(inputs, answers, strict=True):
                result = await ingest_outcome(
                    uow,
                    offer_id=request.offer_id,
                    content_hash=request.content_hash,
                    outcome=answer,
                    context=context,
                    catalog=catalog,
                    retry=self._policy.retry,
                    now=now,
                )
                report.count(result, profile.name)
                report.usage += answer.usage
                if result.status is IngestStatus.FAILED:
                    report.note(f"{request.offer_id}: {result.error}")
                if (
                    isinstance(answer, ExtractionRejection)
                    and not answer.rejection_kind.penalizes_offer
                ):
                    unusable = unusable or answer
            for offer_id in claimed:  # claimed but without content: give back
                if offer_id not in answered:
                    await self._release(uow, offer_id, self._owner, now)
            calls = len(inputs) - sum(
                1
                for a in answers
                if isinstance(a, ExtractionRejection)
                and a.rejection_kind is RejectionKind.UNAVAILABLE
            )
            if calls and profile.capabilities.daily_limit is not None:
                await self._count_requests(uow, profile, calls, now)
            await uow.commit()
        return unusable

    async def _requests_left(self, profile: ExtractionProfile) -> int | None:
        """Requests left today for the profile's quota key, minus calls already in flight
        (``None`` = no daily limit)."""
        status = await self.selector.status(profile.quota_key)
        left = status.remaining_today(
            profile.capabilities.daily_limit, self._clock.now(), profile.capabilities.quota_tz
        )
        return None if left is None else left - self._inflight.get(profile.quota_key, 0)

    async def _count_requests(
        self, uow: UnitOfWork, profile: ExtractionProfile, calls: int, now: datetime
    ) -> None:
        key = profile.quota_key
        status = await uow.profile_status.get(key) or ProfileStatus.new(key, now)
        status.count_requests(calls, now, profile.capabilities.quota_tz)
        await uow.profile_status.save(status)

    async def _mark_unusable(self, profile: ExtractionProfile, answer: ExtractionRejection) -> None:
        if answer.rejection_kind is RejectionKind.QUOTA:
            now = self._clock.now()
            if answer.day_exhausted:  # per-day quota: back at the provider's next midnight
                cooldown = next_reset(now, profile.capabilities.quota_tz) - now
                await self.selector.block(profile, answer.reason, cooldown, shared=True)
                return
            elif answer.retry_after_seconds is not None:  # per-minute quota: short pause
                cooldown = timedelta(seconds=answer.retry_after_seconds)
            else:
                cooldown = self._policy.quota_cooldown
            await self.selector.block(profile, answer.reason, cooldown)
        else:
            self.selector.mark_unhealthy(profile.name, answer.reason)

    @staticmethod
    async def _release(uow: UnitOfWork, offer_id: OfferId, owner: str, now: datetime) -> None:
        state = await uow.extraction_states.get(offer_id)
        if state is not None and state.lease_owner == owner:
            state.release(now)
            await uow.extraction_states.save(state)

    # ------------------------------------------------------------------ batch mode
    async def _submit_new_batches(
        self,
        profile: ExtractionProfile,
        query: BacklogQuery,
        report: ReconcileReport,
        backlog: int,
        budget: _Budget,
    ) -> None:
        catalog = query.catalog
        while backlog > 0 and not budget.exhausted:
            now = self._clock.now()
            async with self._uow() as uow:
                open_batches = await uow.extraction_batches.list_open(profile.name)
            if len(open_batches) >= profile.batch.max_open:
                report.note(
                    f"profile {profile.name}: {len(open_batches)} batch(es) open "
                    f"(max_open {profile.batch.max_open}); waiting"
                )
                return
            limit = profile.batch.max_size
            left = await self._requests_left(profile)
            if left is not None:
                if left <= 0:
                    raise _ProfileUnusable("daily request limit used up")
                limit = min(limit, left)
            limit = budget.take(limit)
            if limit == 0:
                return
            batch_id = self._ids.new_id()
            async with self._uow() as uow:
                claimed = await uow.extraction_states.claim(
                    BacklogQuery(
                        catalog,
                        query.prompt_version,
                        now,
                        query.search,
                        query.profile,
                        query.pinned_only,
                    ),
                    owner=f"batch:{batch_id}",
                    lease_until=now + profile.batch.lease,
                    limit=limit,
                )
                budget.refund(limit - len(claimed))
                if not claimed:
                    return
                offers = await uow.offers.get_many(claimed)
                items = tuple(
                    BatchItem(offer_id, content_hash)
                    for offer_id in claimed
                    if (content_hash := offers[offer_id].content_hash) is not None
                )
                batch = ExtractionBatch(
                    id=batch_id,
                    profile=profile.name,
                    provider=profile.provider,
                    model=profile.model,
                    prompt_version=profile.prompt_version,
                    catalog_fingerprint=catalog.fingerprint,
                    items=items,
                    created_at=now,
                )
                await uow.extraction_batches.save(batch)
                if profile.capabilities.daily_limit is not None:
                    await self._count_requests(uow, profile, len(items), now)
                await uow.commit()
            backlog -= len(claimed)
            await self._submit(batch, profile, catalog, report)

    async def submit_queued(self, report: ReconcileReport, catalog: CategoryCatalog) -> None:
        """POST every QUEUED batch whose profile is available."""
        async with self._uow() as uow:
            queued = [
                b
                for b in await uow.extraction_batches.list_open()
                if b.status is BatchStatus.QUEUED
            ]
        for batch in queued:
            try:
                profile = self._profiles.get(batch.profile)
            except KeyError:
                await self.abandon(batch.id, f"profile {batch.profile} is no longer configured")
                report.note(f"batch {batch.id} abandoned: profile {batch.profile} removed")
                continue
            if not (await self.selector.availability(profile.name)).ok:
                continue
            await self._submit(batch, profile, catalog, report)

    async def _submit(
        self,
        batch: ExtractionBatch,
        profile: ExtractionProfile,
        catalog: CategoryCatalog,
        report: ReconcileReport,
    ) -> None:
        backend = profile.batch_backend
        if backend is None:
            await self.abandon(batch.id, f"profile {profile.name} cannot batch")
            return
        if batch.catalog_fingerprint != catalog.fingerprint:
            await self.abandon(batch.id, "the category catalog changed before submission")
            report.note(f"batch {batch.id} abandoned: catalog changed")
            return
        now = self._clock.now()
        requests: list[BatchRequestItem] = []
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is None or current.status is not BatchStatus.QUEUED:
                return
            offers = await uow.offers.get_many([item.offer_id for item in current.items])
            kept: list[BatchItem] = []
            for item in current.items:
                offer = offers.get(item.offer_id)
                if offer is None or offer.content_hash != item.content_hash:
                    await self._release(uow, item.offer_id, current.lease_owner, now)
                    report.stale += 1
                    continue
                kept.append(item)
                requests.append(
                    BatchRequestItem(
                        item.custom_id,
                        prepare_extraction_input(
                            offer, catalog, max_chars=self._policy.description_max_chars
                        ),
                    )
                )
            current.items = tuple(kept)
            if not kept:
                current.finish(BatchStatus.ABANDONED, now, "every item changed before submission")
                await uow.extraction_batches.save(current)
                await uow.commit()
                return
            current.mark_submitting(now)  # persisted BEFORE the POST (ADR 0010 section 7)
            await uow.extraction_batches.save(current)
            await uow.commit()
        batch = current

        try:
            handle = await backend.submit(requests, batch_ref=batch.id)
        except BatchBackendError as error:
            await self.submit_failed(batch, profile, error.kind, error.reason)
            report.note(f"batch {batch.id} submit failed ({error.kind.value}): {error.reason}")
            if not error.kind.penalizes_offer:
                raise _ProfileUnusable(error.reason) from error
            return
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            await self.submit_failed(batch, profile, RejectionKind.TRANSIENT, reason)
            report.note(f"batch {batch.id} submit failed: {reason}")
            return
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is not None and current.status is BatchStatus.SUBMITTING:
                current.mark_submitted(handle)
                await uow.extraction_batches.save(current)
                await uow.commit()
        report.batches_submitted += 1

    async def submit_failed(
        self, batch: ExtractionBatch, profile: ExtractionProfile, kind: RejectionKind, reason: str
    ) -> None:
        """No penalty for the offers; a PERMANENT rejection of the request is bisected."""
        now = self._clock.now()
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is None or not current.is_open:
                return
            current.finish(BatchStatus.FAILED, now, f"submit: {kind.value}: {reason}")
            await uow.extraction_batches.save(current)
            if kind is RejectionKind.PERMANENT:
                await bisect_or_penalize(
                    uow, current, profile, self._ids, self._policy, reason, now
                )
            else:
                for item in current.items:
                    await self._release(uow, item.offer_id, current.lease_owner, now)
            await uow.commit()
        if kind is RejectionKind.QUOTA:
            await self.selector.block(profile, reason, self._policy.quota_cooldown)
        elif kind is RejectionKind.UNAVAILABLE:
            self.selector.mark_unhealthy(profile.name, reason)

    async def abandon(self, batch_id: str, reason: str) -> bool:
        """Local cancel (ADR 0010 section 7): release the leases, mark ``abandoned``, ignore
        any results that still arrive. Returns False when the batch was not open."""
        now = self._clock.now()
        async with self._uow() as uow:
            batch = await uow.extraction_batches.get(batch_id)
            if batch is None or not batch.is_open:
                return False
            batch.finish(BatchStatus.ABANDONED, now, reason)
            await uow.extraction_batches.save(batch)
            for item in batch.items:
                await self._release(uow, item.offer_id, batch.lease_owner, now)
            await uow.commit()
        return True


async def bisect_or_penalize(
    uow: UnitOfWork,
    batch: ExtractionBatch,
    profile: ExtractionProfile,
    ids: IdGenerator,
    policy: ExtractionPolicy,
    reason: str,
    now: datetime,
) -> list[ExtractionBatch]:
    """A whole batch failed (validation): split it in halves to isolate the bad item.

    The halves are new QUEUED batches that take over the leases (no penalty for anyone).
    A single-item batch that failed gets the penalty: that item is the culprit. Items whose
    lease another owner took over meanwhile are left alone.
    """
    owned: list[tuple[BatchItem, ExtractionState]] = []
    for item in batch.items:
        state = await uow.extraction_states.get(item.offer_id) or ExtractionState.new(
            item.offer_id, now
        )
        if state.lease_owner not in (None, batch.lease_owner) and state.is_leased(now):
            continue
        owned.append((item, state))
    if len(batch.items) == 1:
        for item, state in owned:
            target = ExtractionTarget(
                item.content_hash, batch.catalog_fingerprint, batch.prompt_version
            )
            state.record_failure(target, f"batch failed: {reason}", now, policy.retry)
            await uow.extraction_states.save(state)
        return []
    if len(owned) <= 1:  # the rest was taken over: no culprit can be named, no penalty
        for _, state in owned:
            state.release(now)
            await uow.extraction_states.save(state)
        return []
    middle = len(owned) // 2
    children: list[ExtractionBatch] = []
    for half in (owned[:middle], owned[middle:]):
        child = ExtractionBatch(
            id=ids.new_id(),
            profile=batch.profile,
            provider=batch.provider,
            model=batch.model,
            prompt_version=batch.prompt_version,
            catalog_fingerprint=batch.catalog_fingerprint,
            items=tuple(item for item, _ in half),
            created_at=now,
            parent_id=batch.id,
        )
        await uow.extraction_batches.save(child)
        for _, state in half:
            state.lease(child.lease_owner, now + profile.batch.lease, now)
            await uow.extraction_states.save(state)
        children.append(child)
    return children

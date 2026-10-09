"""PollBatches: follow open provider batches and ingest their results (ADR 0010 sections 4, 7).

* SUBMITTED -> ``poll``: RUNNING stays; COMPLETED -> results ingested through the shared
  validation path (stale-hash discard, failures with backoff, cost allocated by token
  share and marked estimated); FAILED -> leases released without penalty and the batch
  bisected (a failing single item gets the penalty); EXPIRED -> leases released, no penalty
  (the offers are back in the backlog and get resubmitted).
* SUBMITTING older than ``submitting_timeout`` (or every one, with ``recover=True`` at
  extractor start) -> ``find_submitted``: found = SUBMITTED, not found = QUEUED again.
* A batch whose profile disappeared or cannot batch any more is abandoned (local cancel).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

from scrappy.application.extraction.batch import BatchStatus, ExtractionBatch
from scrappy.application.extraction.ingest import IngestContext, IngestStatus, ingest_outcome
from scrappy.application.policy import ExtractionPolicy
from scrappy.application.ports.extraction_backends import (
    BatchBackendError,
    BatchItemResult,
    BatchPoll,
    BatchState,
    ExtractionProfile,
    ExtractionProfiles,
)
from scrappy.application.ports.extractor import (
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.extraction.common import ProfileSelector
from scrappy.application.use_cases.extraction.reconcile import (
    ReconcileExtractions,
    bisect_or_penalize,
)
from scrappy.domain.extraction import TokenUsage

MAX_NOTES = 20


@dataclass(slots=True)
class PollReport:
    polled: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    expired: int = 0
    recovered: int = 0
    stored: int = 0
    item_failures: int = 0
    stale: int = 0
    notes: list[str] = field(default_factory=list[str])

    @property
    def did_work(self) -> bool:
        return bool(self.completed or self.failed or self.expired or self.recovered)

    def note(self, text: str) -> None:
        if len(self.notes) < MAX_NOTES:
            self.notes.append(text)


class PollBatches:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        profiles: ExtractionProfiles,
        categories: CategoryProvider,
        clock: Clock,
        ids: IdGenerator,
        policy: ExtractionPolicy,
        reconcile: ReconcileExtractions,
    ) -> None:
        self._uow = uow
        self._profiles = profiles
        self._categories = categories
        self._clock = clock
        self._ids = ids
        self._policy = policy
        self._reconcile = reconcile

    @property
    def selector(self) -> ProfileSelector:
        return self._reconcile.selector

    async def open_batches(self) -> list[ExtractionBatch]:
        async with self._uow() as uow:
            return await uow.extraction_batches.list_open()

    async def __call__(self, *, recover: bool = False) -> PollReport:
        report = PollReport()
        for batch in await self.open_batches():
            try:
                profile = self._profiles.get(batch.profile)
            except KeyError:
                await self._reconcile.abandon(batch.id, f"profile {batch.profile} removed")
                report.note(f"batch {batch.id} abandoned: profile {batch.profile} removed")
                continue
            if profile.batch_backend is None:
                await self._reconcile.abandon(batch.id, f"profile {profile.name} cannot batch")
                report.note(f"batch {batch.id} abandoned: profile {profile.name} cannot batch")
                continue
            match batch.status:
                case BatchStatus.SUBMITTING:
                    await self._recover(batch, profile, report, force=recover)
                case BatchStatus.SUBMITTED:
                    await self._poll(batch, profile, report)
                case _:
                    pass  # QUEUED: submitted by the reconcile tick
        return report

    # ------------------------------------------------------------------ recovery
    async def _recover(
        self, batch: ExtractionBatch, profile: ExtractionProfile, report: PollReport, *, force: bool
    ) -> None:
        backend = profile.batch_backend
        assert backend is not None
        now = self._clock.now()
        started = batch.submitting_at or batch.created_at
        if not force and now - started < self._policy.submitting_timeout:
            return
        try:
            handle = await backend.find_submitted(
                batch_ref=batch.id,
                item_count=len(batch.items),
                custom_ids=[item.custom_id for item in batch.items],
                submitted_after=started - self._policy.submitting_timeout,
                submitted_before=now,
            )
        except BatchBackendError as error:
            report.note(f"batch {batch.id}: recovery lookup failed: {error.reason}")
            return
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is None or current.status is not BatchStatus.SUBMITTING:
                return
            if handle is None:
                current.requeue()
                report.note(f"batch {batch.id}: not found at the provider, queued again")
            else:
                current.mark_submitted(handle)
                report.note(
                    f"batch {batch.id}: recovered provider batch {handle.provider_batch_id}"
                )
            await uow.extraction_batches.save(current)
            await uow.commit()
        report.recovered += 1

    # ------------------------------------------------------------------ polling
    async def _poll(
        self, batch: ExtractionBatch, profile: ExtractionProfile, report: PollReport
    ) -> None:
        backend = profile.batch_backend
        assert backend is not None
        report.polled += 1
        try:
            poll = await backend.poll(batch.submitted)
        except BatchBackendError as error:
            report.note(f"batch {batch.id}: poll failed ({error.kind.value}): {error.reason}")
            if error.kind is RejectionKind.QUOTA:
                await self.selector.block(profile, error.reason, self._policy.quota_cooldown)
            return
        match poll.state:
            case BatchState.RUNNING:
                report.running += 1
            case BatchState.COMPLETED:
                try:
                    results = [r async for r in backend.results(batch.submitted)]
                except BatchBackendError as error:
                    report.note(f"batch {batch.id}: results failed: {error.reason}")
                    return
                await self._ingest(batch, profile, poll, results, report)
                report.completed += 1
            case BatchState.FAILED:
                await self._failed(batch, profile, poll.error or "batch failed", report)
                report.failed += 1
            case BatchState.EXPIRED:
                await self._expired(batch, report)
                report.expired += 1

    async def _failed(
        self, batch: ExtractionBatch, profile: ExtractionProfile, reason: str, report: PollReport
    ) -> None:
        now = self._clock.now()
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is None or current.status is not BatchStatus.SUBMITTED:
                return
            current.finish(BatchStatus.FAILED, now, reason)
            await uow.extraction_batches.save(current)
            children = await bisect_or_penalize(
                uow, current, profile, self._ids, self._policy, reason, now
            )
            await uow.commit()
        if children:
            report.note(
                f"batch {batch.id} failed ({reason}); resubmitting in halves "
                f"{', '.join(c.id for c in children)}"
            )
        else:
            report.note(f"batch {batch.id} failed ({reason}); its item was penalized")

    async def _expired(self, batch: ExtractionBatch, report: PollReport) -> None:
        now = self._clock.now()
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is None or current.status is not BatchStatus.SUBMITTED:
                return
            current.finish(BatchStatus.EXPIRED, now, "expired at the provider (no results)")
            await uow.extraction_batches.save(current)
            for item in current.items:
                state = await uow.extraction_states.get(item.offer_id)
                if state is not None and state.lease_owner == current.lease_owner:
                    state.release(now)
                    await uow.extraction_states.save(state)
            await uow.commit()
        report.note(f"batch {batch.id} expired; its offers are back in the backlog")

    async def _ingest(
        self,
        batch: ExtractionBatch,
        profile: ExtractionProfile,
        poll: BatchPoll,
        results: list[BatchItemResult],
        report: PollReport,
    ) -> None:
        catalog = await self._categories.catalog()
        now = self._clock.now()
        items = {item.custom_id: item for item in batch.items}
        by_item: dict[str, BatchItemResult] = {}
        for result in results:
            if result.custom_id in items:
                by_item[result.custom_id] = result
            else:
                report.note(f"batch {batch.id}: ignored unknown result {result.custom_id!r}")
        item_usage = sum((r.outcome.usage for r in by_item.values()), TokenUsage())
        total = poll.usage or item_usage
        cost = total.cost_usd
        estimated = cost is not None and any(
            r.outcome.usage.cost_usd is None for r in by_item.values()
        )
        context = IngestContext(
            profile=batch.profile,
            provider=batch.provider,
            prompt_version=batch.prompt_version,
            catalog_fingerprint=batch.catalog_fingerprint,
            owner=batch.lease_owner,
            batch_id=batch.id,
            cost_estimated=estimated,
        )
        quota: ExtractionRejection | None = None
        succeeded = failed = stale = 0
        async with self._uow() as uow:
            current = await uow.extraction_batches.get(batch.id)
            if current is None or current.status is not BatchStatus.SUBMITTED:
                return
            for custom_id, item in items.items():
                result = by_item.get(custom_id)
                outcome = (
                    result.outcome
                    if result is not None
                    else ExtractionRejection(
                        "missing from the batch results", retryable=True, model=batch.model
                    )
                )
                outcome = _with_allocated_cost(outcome, item_usage, cost)
                ingested = await ingest_outcome(
                    uow,
                    offer_id=item.offer_id,
                    content_hash=item.content_hash,
                    outcome=outcome,
                    context=context,
                    catalog=catalog,
                    retry=self._policy.retry,
                    now=now,
                )
                match ingested.status:
                    case IngestStatus.STORED:
                        succeeded += 1
                    case IngestStatus.STALE:
                        stale += 1
                    case IngestStatus.FAILED | IngestStatus.RELEASED:
                        failed += 1
                        if (
                            isinstance(outcome, ExtractionRejection)
                            and outcome.rejection_kind is RejectionKind.QUOTA
                        ):
                            quota = quota or outcome
            current.usage = total
            current.succeeded, current.failed, current.stale = succeeded, failed, stale
            current.finish(BatchStatus.COMPLETED, now)
            await uow.extraction_batches.save(current)
            await uow.commit()
        report.stored += succeeded
        report.item_failures += failed
        report.stale += stale
        if quota is not None:
            await self.selector.block(profile, quota.reason, self._policy.quota_cooldown)


def _with_allocated_cost(
    outcome: ExtractionResult | ExtractionRejection, total_items: TokenUsage, cost: Decimal | None
) -> ExtractionResult | ExtractionRejection:
    """Give an item its token share of the batch cost when the provider has no item cost."""
    usage = outcome.usage
    if cost is None or usage.cost_usd is not None:
        return outcome
    share = (
        cost * Decimal(usage.total_tokens) / Decimal(total_items.total_tokens)
        if total_items.total_tokens
        else Decimal(0)
    )
    return replace(outcome, usage=TokenUsage(usage.prompt_tokens, usage.completion_tokens, share))

"""``ExtractionBatch``: our record of one provider batch (ADR 0010 sections 4 and 7).

Lifecycle::

    QUEUED ─(commit)─► SUBMITTING ─POST ok─► SUBMITTED ─poll─► COMPLETED (ingest)
      │                  │                                 ├─► FAILED   (bisect)
      │                  ├─ crash: find_submitted() or     └─► EXPIRED  (released)
      │                  │   back to QUEUED
      │                  └─ submit error ─► FAILED (bisect or released)
      └─ abandon (local cancel) ─► ABANDONED

* QUEUED: claimed offers are leased to the batch (owner ``batch:<id>``); nothing was sent.
  Created by a reconcile tick, or as one half of a failed batch (bisect).
* SUBMITTING is persisted **before** the POST: a row stuck in it after a crash may or may
  not exist at the provider, so it is reconciled with ``find_submitted`` before resubmitting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from scrappy.application.ports.extraction_backends import SubmittedBatch, batch_custom_id
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash, OfferId
from scrappy.domain.shared import InvalidValueError, require_aware, require_aware_or_none


class BatchStatus(StrEnum):
    QUEUED = "queued"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    ABANDONED = "abandoned"

    @property
    def is_open(self) -> bool:
        return self in (BatchStatus.QUEUED, BatchStatus.SUBMITTING, BatchStatus.SUBMITTED)


OPEN_BATCH_STATUSES = frozenset(s for s in BatchStatus if s.is_open)


@dataclass(frozen=True, slots=True)
class BatchItem:
    offer_id: OfferId
    content_hash: ContentHash

    @property
    def custom_id(self) -> str:
        return batch_custom_id(self.offer_id, self.content_hash)


def lease_owner_for(batch_id: str) -> str:
    return f"batch:{batch_id}"


@dataclass(eq=False, slots=True)
class ExtractionBatch:
    id: str
    profile: str
    provider: str
    model: str
    prompt_version: str
    catalog_fingerprint: str
    items: tuple[BatchItem, ...]
    created_at: datetime
    status: BatchStatus = BatchStatus.QUEUED
    parent_id: str | None = None
    """Set for the halves of a bisected failed batch."""
    provider_batch_id: str | None = None
    submitting_at: datetime | None = None
    submitted_at: datetime | None = None
    finished_at: datetime | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    """Batch-level tokens and exact cost (when reported)."""
    succeeded: int = 0
    failed: int = 0
    stale: int = 0
    """Results discarded because the offer changed (or was taken over) meanwhile."""
    error: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        require_aware_or_none(self.submitting_at, "submitting_at")
        require_aware_or_none(self.submitted_at, "submitted_at")
        require_aware_or_none(self.finished_at, "finished_at")
        if not self.id:
            raise InvalidValueError("batch id must not be empty")
        offers = [item.offer_id for item in self.items]
        if len(set(offers)) != len(offers):
            raise InvalidValueError("a batch lists each offer once")

    @property
    def lease_owner(self) -> str:
        return lease_owner_for(self.id)

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    @property
    def submitted(self) -> SubmittedBatch:
        if self.provider_batch_id is None or self.submitted_at is None:
            raise InvalidValueError(f"batch {self.id} was not submitted")
        return SubmittedBatch(self.provider_batch_id, self.submitted_at, len(self.items))

    def mark_submitting(self, now: datetime) -> None:
        self._expect(BatchStatus.QUEUED)
        self.status = BatchStatus.SUBMITTING
        self.submitting_at = now

    def mark_submitted(self, handle: SubmittedBatch) -> None:
        self._expect(BatchStatus.SUBMITTING)
        self.status = BatchStatus.SUBMITTED
        self.provider_batch_id = handle.provider_batch_id
        self.submitted_at = handle.submitted_at

    def requeue(self) -> None:
        """A SUBMITTING row that never reached the provider: POST it again later."""
        self._expect(BatchStatus.SUBMITTING)
        self.status = BatchStatus.QUEUED
        self.submitting_at = None

    def finish(self, status: BatchStatus, now: datetime, error: str | None = None) -> None:
        if status.is_open:
            raise InvalidValueError("finish needs a final status")
        if not self.is_open:
            raise InvalidValueError(f"batch {self.id} is already {self.status.value}")
        self.status = status
        self.finished_at = now
        if error is not None:
            self.error = error[:1000]

    def _expect(self, status: BatchStatus) -> None:
        if self.status is not status:
            raise InvalidValueError(
                f"batch {self.id} is {self.status.value}, expected {status.value}"
            )

"""Job model for the durable pipeline queue (ADR 0006).

Jobs are immutable values; the :class:`~scrappy.application.ports.JobQueue` stores them and
returns updated copies. Dedup keys (see :func:`dedup_key`) are **unique forever** in the
queue: enqueueing a key that already exists, in any status, is a no-op. Each key therefore
encodes its own scope:

=================  ============================================  ==========================
job                key                                           effect
=================  ============================================  ==========================
DiscoverPage       ``discover:{run_id}:{page_cursor}``           each page once per run;
                                                                 pagination loops stop
EnrichOffer        ``enrich:{offer_id}:{run_id}``                (ADR 0006) one offer page
                                                                 per offer per run
EnrichOffer        ``enrich:{offer_id}:refresh:{tag}``           explicit refresh (no run)
ExtractOffer       ``extract:{offer_id}:{content_hash}:{cat}``   one LLM call per content
                                                                 and catalog version
ExtractOffer       ``extract:{offer_id}:{content_hash}:{cat}:``  explicit re-extraction
                   ``{tag}``
=================  ============================================  ==========================

``{cat}`` is ``CategoryCatalog.fingerprint``: after a schema version bump the same content
must be extractable again, so the key has to change with the catalog.

**ExtractOffer is legacy** (ADR 0010): extraction is no longer a job. The type and payload
stay decodable for rows stored before; migration 0002 marked the unfinished ones OBSOLETE
and no handler is registered for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from scrappy.application.ports.listing_source import PageRef
from scrappy.domain.offer import ContentHash, OfferId
from scrappy.domain.run import RunMetrics
from scrappy.domain.search import SearchName
from scrappy.domain.shared import InvalidValueError, RunId, require_aware, require_aware_or_none


@dataclass(frozen=True, slots=True)
class JobId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise InvalidValueError("JobId must not be empty")

    def __str__(self) -> str:
        return self.value


class JobType(StrEnum):
    DISCOVER_PAGE = "discover_page"
    ENRICH_OFFER = "enrich_offer"
    EXTRACT_OFFER = "extract_offer"
    """Legacy (ADR 0010): only decoded from old rows, never enqueued or handled."""


class JobStatus(StrEnum):
    PENDING = "pending"
    """Waiting until ``available_at``."""
    RUNNING = "running"
    """Claimed by a worker."""
    DONE = "done"
    FAILED = "failed"
    """Out of retries or failed permanently. ``ResumeRun`` can re-queue it."""
    OBSOLETE = "obsolete"
    """Superseded work that will never run (legacy ExtractOffer jobs, ADR 0010)."""

    @property
    def is_unfinished(self) -> bool:
        return self in (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class DiscoverPagePayload:
    search: SearchName
    page: PageRef


@dataclass(frozen=True, slots=True)
class EnrichOfferPayload:
    offer_id: OfferId
    request_tag: str | None = None
    """Set for an explicit refresh outside a run; scopes the dedup key."""


@dataclass(frozen=True, slots=True)
class ExtractOfferPayload:
    """Legacy (ADR 0010): kept so old ``extract_offer`` rows still decode."""

    offer_id: OfferId
    content_hash: ContentHash
    """The content this job was created for; the job is skipped if the offer changed since."""
    catalog_version: str
    """``CategoryCatalog.fingerprint`` when the job was created (dedup scope only)."""
    force: bool = False
    """Re-extract even if ``needs_extraction`` says no (e.g. better model)."""
    request_tag: str | None = None
    """Set for explicit re-extraction requests; scopes the dedup key."""


type JobPayload = DiscoverPagePayload | EnrichOfferPayload | ExtractOfferPayload


def job_type_of(payload: JobPayload) -> JobType:
    match payload:
        case DiscoverPagePayload():
            return JobType.DISCOVER_PAGE
        case EnrichOfferPayload():
            return JobType.ENRICH_OFFER
        case ExtractOfferPayload():
            return JobType.EXTRACT_OFFER


def dedup_key(payload: JobPayload, run_id: RunId | None) -> str:
    """The queue's idempotency key for a job (table in the module docstring)."""
    match payload:
        case DiscoverPagePayload(page=page):
            if run_id is None:
                raise InvalidValueError("DiscoverPage jobs belong to a run")
            return f"discover:{run_id}:{page.cursor}"
        case EnrichOfferPayload(offer_id=offer_id, request_tag=tag):
            if run_id is not None:
                return f"enrich:{offer_id}:{run_id}"
            if tag is None:
                raise InvalidValueError("an EnrichOffer job outside a run needs a request_tag")
            return f"enrich:{offer_id}:refresh:{tag}"
        case ExtractOfferPayload(
            offer_id=offer_id, content_hash=content_hash, catalog_version=catalog, request_tag=tag
        ):
            key = f"extract:{offer_id}:{content_hash}:{catalog}"
            return key if tag is None else f"{key}:{tag}"


@dataclass(frozen=True, slots=True)
class JobResult:
    """What a finished job contributes to its run (ADR 0005 metrics).

    Stored on the job; a run's metrics are the sum over its jobs, so re-running a job
    replaces its contribution instead of double-counting it.
    """

    metrics: RunMetrics = field(default_factory=RunMetrics)
    notes: tuple[str, ...] = ()
    """Short human-readable remarks (rejection reasons, skips) for the run report."""


@dataclass(frozen=True, slots=True)
class Job:
    id: JobId
    payload: JobPayload
    dedup_key: str
    run_id: RunId | None
    created_at: datetime
    available_at: datetime
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    """Incremented by every claim."""
    last_error: str | None = None
    result: JobResult | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        require_aware(self.available_at, "available_at")
        require_aware_or_none(self.finished_at, "finished_at")
        if self.attempts < 0:
            raise InvalidValueError("attempts must be >= 0")

    @property
    def type(self) -> JobType:
        return job_type_of(self.payload)

    @classmethod
    def new(
        cls,
        job_id: JobId,
        payload: JobPayload,
        *,
        run_id: RunId | None,
        now: datetime,
        available_at: datetime | None = None,
    ) -> Job:
        return cls(
            id=job_id,
            payload=payload,
            dedup_key=dedup_key(payload, run_id),
            run_id=run_id,
            created_at=now,
            available_at=available_at or now,
        )

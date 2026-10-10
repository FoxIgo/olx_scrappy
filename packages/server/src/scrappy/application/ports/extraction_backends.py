"""Extraction profiles and the batch capability port (ADR 0010 sections 5, 7 and 8).

The reconciler (``application/use_cases/extraction``) works only with these types. It asks a
profile what it can do (:class:`ProfileCapabilities`) and **never** branches on provider
names; ``ExtractionProfile.provider`` is recorded as provenance only.

Every profile has a synchronous :class:`~scrappy.application.ports.extractor.AttributeExtractor`.
Profiles whose provider can batch also carry a :class:`BatchExtractionBackend`.

Contract for batch adapter authors (OpenRouter batch, Gemini batch, ...)
-----------------------------------------------------------------------
**Submission.** ``submit(items, batch_ref=...)`` gets up to ``BatchSettings.max_size``
:class:`BatchRequestItem`. Each carries the fully prepared
:class:`~scrappy.application.ports.extractor.ExtractionInput` and its ``custom_id``:

    ``<source>:<external_id>@<content_hash>``  e.g. ``olx_pl:1098526767@3fa9...`` (64 hex)

(see :func:`batch_custom_id` / :func:`parse_custom_id`). Render each item exactly like the
sync adapter does (shared ``prompt.build_messages`` + ``schema_builder.ExtractionSchema``),
with the profile's structured-output level decided **once per batch** (no per-call
downgrade; OpenRouter/Gemini require one ``response_format`` for every item). ``batch_ref``
is our local batch id: use it as a marker if the provider has a metadata/name field.
Return :class:`SubmittedBatch` with the provider's id as soon as the provider accepted the
request (HTTP 2xx). The application has already persisted the batch as ``submitting``
before calling ``submit``; a crash between the POST and that return is repaired with
``find_submitted``.

**Errors on submit/poll/results** are raised as :class:`BatchBackendError` with a
:class:`~scrappy.application.ports.extractor.RejectionKind`:

* 402 (balance/estimate too high) -> ``QUOTA`` (the profile is blocked for a cooldown, the
  claimed offers are released without penalty);
* 429 -> ``TRANSIENT`` with ``retry_after`` from ``Retry-After`` when present;
* 5xx, timeouts, connection errors -> ``TRANSIENT`` (submit: offers released, no penalty);
* 401/403 or "model has no batch endpoint" (400) -> ``UNAVAILABLE``;
* other 4xx (malformed request, 413 payload too large, 422) -> ``PERMANENT``. On submit
  this releases the offers without penalty and the batch is bisected like a failed one.

**Polling.** ``poll(batch)`` maps provider statuses onto :class:`BatchState`:
``validating``/``in_progress``/``finalizing``/``cancelling`` -> RUNNING, ``completed`` ->
COMPLETED, ``failed`` -> FAILED (batch-level validation failure; put the provider's
``error.message`` in ``error``), ``expired`` -> EXPIRED, ``cancelled`` -> FAILED. Report
batch-level token usage and the **exact** batch cost in ``usage`` when known (OpenRouter:
``usage.cost``). A 402 on GET (finalized cost above balance; results are kept) -> raise
``BatchBackendError(QUOTA)``; the application polls again later.

**Results.** ``results(batch)`` is only called after ``poll`` returned COMPLETED. Yield one
:class:`BatchItemResult` per returned item (order irrelevant), with ``custom_id`` exactly as
submitted and the outcome mapped like the sync adapter would:

* a parsable answer -> ``ExtractionResult`` (validate with ``ExtractionSchema.validate``;
  ``model`` = the profile model, ``prompt_version`` = the shared ``PROMPT_VERSION``,
  ``usage`` = the item's token counts with ``cost_usd=None`` unless the provider reports a
  per-item cost; the application allocates the batch cost by token share and marks it
  ``cost_estimated``);
* invalid output -> ``ExtractionRejection(kind=INVALID_OUTPUT)`` (no corrective retry in a
  batch: the offer returns to the backlog with backoff);
* item ``error_type`` ``rate_limit_exceeded`` / ``provider_overloaded`` /
  ``provider_unavailable`` / ``server`` / ``timeout`` -> ``TRANSIENT``; ``payment_required``
  -> ``QUOTA``; ``authentication`` / ``permission_denied`` -> ``UNAVAILABLE``; anything else
  (``context_length_exceeded``, ``content_policy_violation``, ``refusal``, ``invalid_*``)
  -> ``PERMANENT``. ``response.status_code != 200`` is mapped by HTTP status like the sync
  adapter. Items the provider did not return at all are treated as TRANSIENT failures by
  the application; do not invent them.

**Cancel.** ``cancel`` is best effort and may be a no-op returning ``False`` (OpenRouter
has no cancel endpoint). The application's local cancel (``AbandonBatch``) always releases
the leases, marks the batch ``abandoned`` and ignores later results, whatever this returns.

**Crash recovery.** ``find_submitted`` looks for a provider batch created for our
``batch_ref`` between ``submitted_after`` and ``submitted_before`` with ``item_count``
requests (OpenRouter: ``GET /batches?created_after=..`` and match model + request count +
time window, optionally the ``custom_id`` set). Return ``None`` when nothing matches: the
batch is then resubmitted. Never create a batch here.

All methods are async, do network I/O and are called **outside** any unit of work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Protocol

from scrappy.application.extraction.profile_status import quota_tz
from scrappy.application.ports.extractor import (
    AttributeExtractor,
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash, OfferId
from scrappy.domain.shared import InvalidValueError

GROUP_KEY_PREFIX = "group:"
"""Prefix of the profile-status rows that hold a quota group's shared counter."""


class StructuredOutput(StrEnum):
    """How strictly the provider enforces the answer shape (ADR 0010 section 8)."""

    JSON_SCHEMA = "json_schema"
    """``response_format: json_schema`` (strict)."""
    JSON_OBJECT = "json_object"
    """``response_format: json_object``; the schema is in the prompt."""
    PROMPT_ONLY = "prompt_only"
    """No ``response_format``; the schema is in the prompt; our validation decides."""

    def downgraded(self) -> StructuredOutput | None:
        match self:
            case StructuredOutput.JSON_SCHEMA:
                return StructuredOutput.JSON_OBJECT
            case StructuredOutput.JSON_OBJECT:
                return StructuredOutput.PROMPT_ONLY
            case StructuredOutput.PROMPT_ONLY:
                return None


class ExtractionMode(StrEnum):
    SYNC = "sync"
    BATCH = "batch"
    AUTO = "auto"
    """Batch when the backlog is at least ``BatchSettings.min_size``, else sync."""


@dataclass(frozen=True, slots=True)
class ProfileCapabilities:
    supports_batch: bool = False
    """True when the profile carries a :class:`BatchExtractionBackend`."""
    structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA
    """Configured level (the effective one after probing is in :class:`ProfileHealth`)."""
    concurrency: int = 1
    """Parallel sync calls (1 for a single local GPU)."""
    rate_limit_per_minute: float | None = None
    """Max sync call starts per minute (free tiers)."""
    daily_limit: int | None = None
    """Max requests per day; when used up, the profile is unavailable until midnight."""
    quota_timezone: str = "UTC"
    """IANA timezone whose midnight resets ``daily_limit`` (Google: America/Los_Angeles)."""
    quota_group: str | None = None
    """Profiles of one group share ONE daily counter (``daily_limit`` / ``quota_timezone``
    are then the group's). OpenRouter ``:free`` models share an account-wide daily limit."""

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise InvalidValueError("concurrency must be >= 1")
        if self.rate_limit_per_minute is not None and self.rate_limit_per_minute <= 0:
            raise InvalidValueError("rate_limit must be > 0")
        if self.daily_limit is not None and self.daily_limit < 1:
            raise InvalidValueError("daily_limit must be >= 1")
        quota_tz(self.quota_timezone)

    @property
    def quota_tz(self) -> tzinfo:
        return quota_tz(self.quota_timezone)


@dataclass(frozen=True, slots=True)
class BatchSettings:
    """Submission policy (ADR 0010 section 4)."""

    min_size: int = 20
    """``auto`` uses batch from this backlog size; ``batch`` waits for it (or ``max_wait``)."""
    max_size: int = 200
    """Items per batch (OpenRouter returns results inline: keep bodies small)."""
    max_open: int = 3
    """Open (queued/submitting/submitted) batches per profile."""
    max_wait: timedelta = timedelta(minutes=30)
    """``batch`` mode submits a smaller batch once the backlog waited this long."""
    lease: timedelta = timedelta(hours=26)
    """How long batch items stay claimed (provider window is 24 h)."""

    def __post_init__(self) -> None:
        if not 1 <= self.min_size <= self.max_size:
            raise InvalidValueError("need 1 <= batch.min_size <= batch.max_size")
        if self.max_open < 1:
            raise InvalidValueError("batch.max_open must be >= 1")


@dataclass(frozen=True, slots=True)
class ProfileHealth:
    ok: bool
    detail: str
    """Human-readable: what was checked, or what is wrong and how to fix it."""
    model_available: bool | None = None
    effective_structured_output: StructuredOutput | None = None
    """Set when a probe ran (it may have downgraded the configured level)."""


class ProfileHealthCheck(Protocol):
    async def check(self, *, probe: bool = False) -> ProfileHealth:
        """Endpoint reachable, model listed (``GET {base_url}/models``), key present.

        With ``probe=True`` (and the profile's ``probe`` flag on) the adapter may send ONE
        tiny structured request and downgrade its effective structured-output level
        (json_schema -> json_object -> prompt_only) when the provider rejects it. Never
        raises; problems are reported with ``ok=False``."""
        ...


@dataclass(frozen=True, slots=True)
class BatchRequestItem:
    custom_id: str
    input: ExtractionInput


@dataclass(frozen=True, slots=True)
class SubmittedBatch:
    """The provider's handle of a batch (stored on our ``extraction_batches`` row)."""

    provider_batch_id: str
    submitted_at: datetime
    item_count: int


class BatchState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class BatchPoll:
    state: BatchState
    total: int = 0
    completed: int = 0
    failed: int = 0
    error: str | None = None
    """Batch-level error message (FAILED)."""
    usage: TokenUsage | None = None
    """Batch-level tokens and the exact batch cost, when the provider reports them."""


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    custom_id: str
    outcome: ExtractionResult | ExtractionRejection


class BatchBackendError(Exception):
    def __init__(
        self, reason: str, *, kind: RejectionKind, retry_after: timedelta | None = None
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind
        self.retry_after = retry_after


class BatchExtractionBackend(Protocol):
    async def submit(
        self, items: Sequence[BatchRequestItem], *, batch_ref: str
    ) -> SubmittedBatch: ...

    async def poll(self, batch: SubmittedBatch) -> BatchPoll: ...

    def results(self, batch: SubmittedBatch) -> AsyncIterator[BatchItemResult]: ...

    async def cancel(self, batch: SubmittedBatch) -> bool:
        """Best effort; ``False`` when the provider cannot cancel (local cancel only)."""
        ...

    async def find_submitted(
        self,
        *,
        batch_ref: str,
        item_count: int,
        custom_ids: Sequence[str],
        submitted_after: datetime,
        submitted_before: datetime,
    ) -> SubmittedBatch | None: ...


@dataclass(frozen=True, slots=True)
class ExtractionProfile:
    """One named profile of ``config/extraction.yaml``, with its adapters attached."""

    name: str
    provider: str
    """Provenance only; the reconciler never branches on it."""
    model: str
    prompt_version: str
    """Version of the prompt the adapters render (part of the backlog rule)."""
    extractor: AttributeExtractor
    health: ProfileHealthCheck
    mode: ExtractionMode = ExtractionMode.SYNC
    capabilities: ProfileCapabilities = field(default_factory=ProfileCapabilities)
    batch: BatchSettings = field(default_factory=BatchSettings)
    batch_backend: BatchExtractionBackend | None = None
    probe: bool = True
    """Allow a one-request structured-output probe at extractor start / ``--probe``."""

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidValueError("profile name must not be empty")
        if self.capabilities.supports_batch != (self.batch_backend is not None):
            raise InvalidValueError(
                f"profile {self.name}: supports_batch must match the presence of a backend"
            )

    @property
    def quota_key(self) -> str:
        """Key of the persisted daily counter / daily block: the group's, else the profile's."""
        group = self.capabilities.quota_group
        return self.name if group is None else f"{GROUP_KEY_PREFIX}{group}"

    def wants_batch(self, backlog: int, *, waited_long: bool = False, flush: bool = False) -> bool:
        """Mode decision for one tick (ADR 0010 section 5). Without a batch backend, never."""
        if self.batch_backend is None:
            return False
        match self.mode:
            case ExtractionMode.SYNC:
                return False
            case ExtractionMode.AUTO:
                return backlog >= self.batch.min_size
            case ExtractionMode.BATCH:
                return backlog >= self.batch.min_size or waited_long or flush


class ExtractionProfiles(Protocol):
    """The configured profiles (``config/extraction.yaml``)."""

    @property
    def default(self) -> str: ...

    @property
    def pool(self) -> Sequence[str]:
        """The profiles that run IN PARALLEL, one lane each (ADR 0010 section 9)."""
        ...

    def names(self) -> Sequence[str]: ...

    def get(self, name: str) -> ExtractionProfile:
        """Raises ``KeyError`` for an unknown name."""
        ...


@dataclass(frozen=True, slots=True)
class StaticExtractionProfiles:
    """Plain implementation of :class:`ExtractionProfiles` (built in ``main.py``/tests)."""

    profiles: Mapping[str, ExtractionProfile]
    default_profile: str
    pool_names: tuple[str, ...] = ()
    """The parallel pool; empty means just the default profile."""

    def __post_init__(self) -> None:
        if self.default_profile not in self.profiles:
            raise InvalidValueError(f"default profile {self.default_profile} is not defined")
        unknown = [n for n in self.pool_names if n not in self.profiles]
        if unknown:
            raise InvalidValueError(f"pool lists unknown profile(s): {', '.join(unknown)}")

    @property
    def default(self) -> str:
        return self.default_profile

    @property
    def pool(self) -> Sequence[str]:
        return list(dict.fromkeys(self.pool_names)) or [self.default_profile]

    def names(self) -> Sequence[str]:
        return list(self.profiles)

    def get(self, name: str) -> ExtractionProfile:
        return self.profiles[name]


def batch_custom_id(offer_id: OfferId, content_hash: ContentHash) -> str:
    """``<source>:<external_id>@<content_hash>`` (ADR 0010 section 4)."""
    return f"{offer_id}@{content_hash}"


def parse_custom_id(custom_id: str) -> tuple[OfferId, ContentHash]:
    """Inverse of :func:`batch_custom_id`; raises ``InvalidValueError`` when malformed."""
    offer, sep, digest = custom_id.rpartition("@")
    if not sep:
        raise InvalidValueError(f"malformed batch custom_id {custom_id!r}")
    return OfferId.parse(offer), ContentHash(digest)

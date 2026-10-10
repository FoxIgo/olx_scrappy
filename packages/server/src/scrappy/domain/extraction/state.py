"""Per-offer extraction bookkeeping for the reconciling extractor (ADR 0010 section 3).

Extraction is derived state: an offer is in the **backlog** when its latest extraction is
missing or out of date (:func:`needs_extraction`) and its :class:`ExtractionState` allows
work right now (:func:`extraction_due`): not leased, not in backoff, not parked.

The failure counters of a state always refer to one :class:`ExtractionTarget` (content
hash + catalog fingerprint + prompt version). When the target changes (the offer was edited,
a schema was bumped, the prompt changed) the old counters no longer apply, so a parked offer
comes back by itself. A manual retry (``reset``) or a forced re-extraction also clears them.

Tiering (ADR 0012): the rule pass records which content it ran on (``rules_hash``,
``rules_version``) and why that content needs the LLM (``escalation``). With a gated backlog
only escalated (or forced) offers go to the LLM.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from scrappy.domain.category import CategoryCatalog
from scrappy.domain.extraction.extraction import OfferExtraction, needs_extraction
from scrappy.domain.offer import ContentHash, Offer, OfferId
from scrappy.domain.shared import InvalidValueError, require_aware, require_aware_or_none

MAX_ERROR_CHARS = 500


@dataclass(frozen=True, slots=True)
class ExtractionTarget:
    """What an extraction attempt is for: this content, with this catalog and prompt."""

    content_hash: ContentHash
    catalog_fingerprint: str
    prompt_version: str

    @classmethod
    def of(cls, offer: Offer, catalog: CategoryCatalog, prompt_version: str) -> ExtractionTarget:
        if offer.content_hash is None:
            raise InvalidValueError(f"offer {offer.id} has no content yet")
        return cls(offer.content_hash, catalog.fingerprint, prompt_version)


@dataclass(frozen=True, slots=True)
class ExtractionRetryPolicy:
    """Exponential backoff per offer; parked after ``max_attempts`` failures."""

    max_attempts: int = 5
    base_delay: timedelta = timedelta(minutes=1)
    max_delay: timedelta = timedelta(hours=6)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise InvalidValueError("max_attempts must be >= 1")
        if self.base_delay <= timedelta(0) or self.max_delay < self.base_delay:
            raise InvalidValueError("need 0 < base_delay <= max_delay")

    def delay(self, attempts: int) -> timedelta:
        """Backoff after ``attempts`` failures (1 -> base, 2 -> 2x base, ...), capped."""
        exponent = min(max(attempts - 1, 0), 30)
        return min(self.max_delay, self.base_delay * (2**exponent))


@dataclass(eq=False, slots=True)
class ExtractionState:
    """Application-owned record per offer (not part of the Offer aggregate)."""

    offer_id: OfferId
    updated_at: datetime
    lease_owner: str | None = None
    """A batch id (``batch:<id>``) or a sync worker id (``sync:<id>``) holding the offer."""
    lease_until: datetime | None = None
    attempts: int = 0
    """Failed attempts for :attr:`target` (reset by success or a new target)."""
    last_error: str | None = None
    next_attempt_at: datetime | None = None
    parked: bool = False
    """Out of attempts for :attr:`target`: no automatic retries until the target changes or
    someone retries manually (``scrappy extract force --parked``)."""
    target: ExtractionTarget | None = None
    """The target the failure counters refer to."""
    forced: bool = False
    """Re-extract even if up to date (``scrappy extract force``); cleared by a success."""
    requested_profile: str | None = None
    """Only this profile may take the forced work (``extract force --profile``)."""
    rules_hash: ContentHash | None = None
    """Content the rule pass last ran on (ADR 0012 tier 0)."""
    rules_version: str | None = None
    """Rules version (+ catalog fingerprint) of that pass; another one re-runs the rules."""
    escalation: str | None = None
    """Why the content of ``rules_hash`` goes to the LLM (comma-separated reasons such as
    ``damage_unclear`` or ``top:gaming``); ``None``: the rule result stands."""

    def __post_init__(self) -> None:
        require_aware(self.updated_at, "updated_at")
        require_aware_or_none(self.lease_until, "lease_until")
        require_aware_or_none(self.next_attempt_at, "next_attempt_at")
        if self.attempts < 0:
            raise InvalidValueError("attempts must be >= 0")

    @classmethod
    def new(cls, offer_id: OfferId, now: datetime) -> ExtractionState:
        return cls(offer_id=offer_id, updated_at=now)

    # ------------------------------------------------------------------ queries
    def is_leased(self, now: datetime) -> bool:
        return self.lease_until is not None and self.lease_until > now

    def applies_to(self, target: ExtractionTarget) -> bool:
        return self.target == target

    def rules_done(self, content_hash: ContentHash, version: str) -> bool:
        return self.rules_hash == content_hash and self.rules_version == version

    def escalated_for(self, content_hash: ContentHash) -> bool:
        """Does this content go to the LLM under a gated backlog? (ADR 0012)"""
        return self.escalation is not None and self.rules_hash == content_hash

    @property
    def escalation_reasons(self) -> tuple[str, ...]:
        return tuple(self.escalation.split(",")) if self.escalation else ()

    def blocks(self, target: ExtractionTarget, now: datetime) -> bool:
        """True while backoff or parking (for this target) holds the offer back."""
        if not self.applies_to(target):
            return False
        if self.parked:
            return True
        return self.next_attempt_at is not None and self.next_attempt_at > now

    # ------------------------------------------------------------------ changes
    def lease(self, owner: str, until: datetime, now: datetime) -> None:
        if not owner:
            raise InvalidValueError("lease owner must not be empty")
        self.lease_owner = owner
        self.lease_until = require_aware(until, "until")
        self.updated_at = now

    def release(self, now: datetime) -> None:
        """Give the offer back without any penalty (expired/failed batch, shutdown)."""
        self.lease_owner = None
        self.lease_until = None
        self.updated_at = now

    def record_success(self, now: datetime) -> None:
        self.release(now)
        self.attempts = 0
        self.last_error = None
        self.next_attempt_at = None
        self.parked = False
        self.target = None
        self.forced = False
        self.requested_profile = None

    def record_failure(
        self,
        target: ExtractionTarget,
        error: str,
        now: datetime,
        policy: ExtractionRetryPolicy,
    ) -> None:
        """Count a failed attempt for ``target``: backoff, or park when out of attempts."""
        if not self.applies_to(target):
            self.target = target
            self.attempts = 0
            self.parked = False
        self.release(now)
        self.attempts += 1
        self.last_error = error[:MAX_ERROR_CHARS]
        if self.attempts >= policy.max_attempts:
            self.parked = True
            self.next_attempt_at = None
        else:
            self.next_attempt_at = now + policy.delay(self.attempts)

    def record_rules(
        self,
        content_hash: ContentHash,
        version: str,
        reasons: Iterable[str],
        now: datetime,
    ) -> None:
        """The rule pass ran on ``content_hash``; ``reasons`` (may be empty) send it to the LLM."""
        self.rules_hash = content_hash
        self.rules_version = version
        self.escalation = None
        self.updated_at = now
        for reason in reasons:
            self.escalate(reason, now)

    def escalate(self, reason: str, now: datetime) -> bool:
        """Send the rule-processed content to the LLM; False if already sent for ``reason``."""
        if self.rules_hash is None:
            raise InvalidValueError("escalate needs a rule pass first (record_rules)")
        if not reason or "," in reason:
            raise InvalidValueError(f"invalid escalation reason {reason!r}")
        if reason in self.escalation_reasons:
            return False
        self.escalation = ",".join((*self.escalation_reasons, reason))[:MAX_ERROR_CHARS]
        self.updated_at = now
        return True

    def reset(self, now: datetime, *, force: bool = False, profile: str | None = None) -> None:
        """Manual retry: forget failures; ``force`` also re-extracts an up-to-date offer."""
        self.attempts = 0
        self.last_error = None
        self.next_attempt_at = None
        self.parked = False
        self.target = None
        if force:
            self.forced = True
            self.requested_profile = profile
        self.updated_at = now


def extraction_due(
    offer: Offer,
    latest: OfferExtraction | None,
    state: ExtractionState | None,
    catalog: CategoryCatalog,
    prompt_version: str,
    now: datetime,
    *,
    gated: bool = False,
) -> bool:
    """Is the offer in the extraction backlog right now? (ADR 0010 sections 2 and 3)

    It must have content, not be leased, not be held back by backoff or parking for its
    current target, and either be out of date (:func:`needs_extraction`) or be forced.
    ``gated`` (ADR 0012 tiering): only forced offers and offers the rule pass escalated
    for their current content qualify.
    """
    if offer.content_hash is None:
        return False
    if state is not None and state.is_leased(now):
        return False
    forced = state is not None and state.forced
    if gated and not forced and not (state is not None and state.escalated_for(offer.content_hash)):
        return False
    if not forced and not needs_extraction(offer, latest, catalog, prompt_version):
        return False
    target = ExtractionTarget.of(offer, catalog, prompt_version)
    return not (state is not None and state.blocks(target, now))

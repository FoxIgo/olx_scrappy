"""The Offer aggregate: current state, change detection and snapshots (R4, R7, R9).

History rules (ADR 0005):

* A field whose new value is ``None`` (or ``OfferStatus.UNKNOWN``) was *not observed*;
  the stored value is kept and no change is recorded.
* A field seen for the first time (stored value unknown) is filled in silently. It is not a
  change, so creating an offer or enriching it for the first time writes no snapshot.
* Only a *tracked* field observed with a different known value produces a
  :class:`FieldChange`. Other fields (url, dates, images, seller) are refreshed silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrappy.domain.offer.liveness import LivenessEvaluation

from scrappy.domain.offer.observation import OfferObservation
from scrappy.domain.offer.values import (
    ContentHash,
    OfferId,
    OfferStatus,
    Params,
    Price,
    SellerRef,
    compute_content_hash,
)
from scrappy.domain.shared import FetchOutcome, InvalidValueError, RunId, require_aware


class TrackedField(StrEnum):
    """Fields whose changes are kept as history (R7)."""

    TITLE = "title"
    PRICE = "price"
    LOCATION = "location"
    DESCRIPTION = "description"
    PARAMS = "params"
    STATUS = "status"


type FieldValue = str | Price | Params | OfferStatus


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: TrackedField
    old: FieldValue
    new: FieldValue


@dataclass(frozen=True, slots=True)
class OfferSnapshot:
    """Changed fields only, written when an observation differs from the stored state."""

    offer_id: OfferId
    observed_at: datetime
    changes: tuple[FieldChange, ...]
    run_id: RunId | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.changes:
            raise InvalidValueError("a snapshot needs at least one change")


def snapshot_for(
    offer_id: OfferId,
    changes: list[FieldChange],
    observed_at: datetime,
    run_id: RunId | None = None,
) -> OfferSnapshot | None:
    """A snapshot when something changed, else ``None`` (R7: no change, no snapshot)."""
    if not changes:
        return None
    return OfferSnapshot(offer_id, observed_at, tuple(changes), run_id)


@dataclass(eq=False, slots=True)
class Offer:
    """Aggregate root. Global (not per search), identified by :class:`OfferId`."""

    id: OfferId
    url: str
    first_seen_at: datetime
    last_seen_at: datetime
    title: str | None = None
    price: Price | None = None
    location: str | None = None
    thumbnail_url: str | None = None
    posted_at: datetime | None = None
    refreshed_at: datetime | None = None
    has_delivery: bool = False
    description: str | None = None
    params: Params | None = None
    status: OfferStatus = OfferStatus.UNKNOWN
    seller: SellerRef | None = None
    image_urls: tuple[str, ...] = field(default_factory=tuple[str, ...])
    content_hash: ContentHash | None = None
    details_fetched_at: datetime | None = None
    """When detail-complete data was last observed (offer page, or a full search item)."""

    def __post_init__(self) -> None:
        require_aware(self.first_seen_at, "first_seen_at")
        require_aware(self.last_seen_at, "last_seen_at")

    # ------------------------------------------------------------------ creation
    @classmethod
    def from_observation(cls, observation: OfferObservation, at: datetime) -> Offer:
        """Create a new offer from its first observation. No changes are reported."""
        if observation.url is None:
            raise InvalidValueError("a new offer needs a URL")
        offer = cls(id=observation.offer_id, url=observation.url, first_seen_at=at, last_seen_at=at)
        offer.apply(observation, at)
        return offer

    @property
    def has_details(self) -> bool:
        return self.details_fetched_at is not None

    def evaluate_liveness(self, at: datetime | None = None) -> LivenessEvaluation:
        from scrappy.domain.offer.liveness import evaluate_liveness

        return evaluate_liveness(self, at=at)

    @property
    def liveness(self) -> LivenessEvaluation:
        return self.evaluate_liveness()

    def apply(self, observation: OfferObservation, at: datetime) -> list[FieldChange]:
        """Merge an observation into the current state; return tracked-field changes.

        This is the ``apply_observation`` rule of the domain model. Idempotent: applying
        the same observation twice returns no changes the second time.
        """
        require_aware(at, "at")
        if observation.offer_id != self.id:
            raise InvalidValueError(f"observation for {observation.offer_id} applied to {self.id}")
        changes: list[FieldChange] = []

        self.title = _merge(TrackedField.TITLE, self.title, observation.title, changes)
        self.price = _merge(TrackedField.PRICE, self.price, observation.price, changes)
        self.location = _merge(TrackedField.LOCATION, self.location, observation.location, changes)
        self.description = _merge(
            TrackedField.DESCRIPTION, self.description, observation.description, changes
        )
        self.params = _merge(TrackedField.PARAMS, self.params, observation.params, changes)
        self._set_status(observation.status, changes)

        if observation.url is not None:
            self.url = observation.url
        if observation.thumbnail_url is not None:
            self.thumbnail_url = observation.thumbnail_url
        if observation.posted_at is not None:
            self.posted_at = observation.posted_at
        if observation.refreshed_at is not None:
            self.refreshed_at = observation.refreshed_at
        if observation.seller is not None:
            self.seller = observation.seller
        if observation.image_urls is not None:
            self.image_urls = observation.image_urls
        self.has_delivery = observation.has_delivery

        if observation.is_detail_complete:
            self.details_fetched_at = at
        self.mark_seen(at)
        self._refresh_content_hash()
        return changes

    def record_unavailable(
        self, outcome: FetchOutcome, observed_status: OfferStatus | None, at: datetime
    ) -> list[FieldChange]:
        """Apply a GONE / NOT_FOUND detail fetch to this (known) offer (R9).

        A known offer whose page now 404s is treated as removed: NOT_FOUND only means
        "never existed" for ids we have never seen, which the caller handles by not
        creating an offer at all.
        """
        if outcome not in (FetchOutcome.GONE, FetchOutcome.NOT_FOUND):
            raise InvalidValueError(f"record_unavailable expects GONE/NOT_FOUND, got {outcome}")
        status = status_after_fetch(outcome, observed_status, offer_known=True)
        changes: list[FieldChange] = []
        self._set_status(status, changes)
        self.details_fetched_at = require_aware(at, "at")
        return changes

    def mark_seen(self, at: datetime) -> None:
        require_aware(at, "at")
        if at > self.last_seen_at:
            self.last_seen_at = at

    # ------------------------------------------------------------------ internals
    def _set_status(self, new: OfferStatus | None, changes: list[FieldChange]) -> None:
        if new is None or new is OfferStatus.UNKNOWN:
            return
        if self.status is not OfferStatus.UNKNOWN and self.status != new:
            changes.append(FieldChange(TrackedField.STATUS, self.status, new))
        self.status = new

    def _refresh_content_hash(self) -> None:
        if self.description is not None:
            self.content_hash = compute_content_hash(self.title, self.description, self.params)


def _merge[T: FieldValue](
    name: TrackedField, old: T | None, new: T | None, changes: list[FieldChange]
) -> T | None:
    if new is None:
        return old  # not observed: unknown, keep what we know
    if old is not None and old != new:
        changes.append(FieldChange(name, old, new))
    return new


# ---------------------------------------------------------------------- rules


def needs_details(offer: Offer | None, observation: OfferObservation) -> bool:
    """R8 re-fetch policy: does this offer need an offer-page fetch (EnrichOffer)?

    Must be evaluated *before* the observation is applied.

    * A detail-complete observation never needs one (the data is already here).
    * New offers, and offers never enriched successfully, need one.
    * Otherwise only when list-level data changed: price, title or refreshed date.
      Missing values never count as a change.
    """
    if observation.is_detail_complete:
        return False
    if offer is None or not offer.has_details:
        return True
    return (
        _differs(offer.price, observation.price)
        or _differs(offer.title, observation.title)
        or _differs(offer.refreshed_at, observation.refreshed_at)
    )


def _differs[T](stored: T | None, observed: T | None) -> bool:
    return stored is not None and observed is not None and stored != observed


def status_after_fetch(
    outcome: FetchOutcome, observed_status: OfferStatus | None, *, offer_known: bool
) -> OfferStatus | None:
    """Offer status implied by a detail-fetch outcome (R9); ``None`` means "no information".

    * OK: whatever the page says (``None`` if it did not say).
    * GONE: the page's status if it is SOLD or REMOVED, else REMOVED.
    * NOT_FOUND: REMOVED for an offer we knew (it existed, now it does not); ``None`` for an
      id we have never seen (it simply does not exist; nothing to store).
    * BLOCKED / TRANSIENT: ``None``; they say nothing about the offer.
    """
    match outcome:
        case FetchOutcome.OK:
            return observed_status
        case FetchOutcome.GONE:
            if observed_status in (OfferStatus.SOLD, OfferStatus.REMOVED):
                return observed_status
            return OfferStatus.REMOVED
        case FetchOutcome.NOT_FOUND:
            return OfferStatus.REMOVED if offer_known else None
        case FetchOutcome.BLOCKED | FetchOutcome.TRANSIENT:
            return None

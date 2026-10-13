"""What a source observed about one offer.

Every field except the identity is optional: ``None`` means *not observed / unknown*, never
"now empty" (ADR 0005, "missing is not changed"). Per-phase required fields are enforced by
the adapter's validation before an observation is built; rejected records never get here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from scrappy.domain.offer.values import OfferId, OfferStatus, Params, Price, SellerRef
from scrappy.domain.shared import InvalidValueError, require_aware_or_none


class ObservationLevel(StrEnum):
    LISTING = "listing"
    """Search-result card data (title, price, dates...). Details still need an offer page."""
    DETAILS = "details"
    """Detail-complete: description (and, if the site has them, params/status) observed.

    Produced by an offer page, or by a search page when the source returns full offer data
    (OLX's search API does). A detail-complete observation never needs an EnrichOffer job.
    """


LISTING_FIELDS: tuple[str, ...] = (
    "title",
    "price",
    "location",
    "thumbnail_url",
    "posted_at",
    "refreshed_at",
)
DETAIL_FIELDS: tuple[str, ...] = ("description", "params", "status", "seller", "image_urls")


@dataclass(frozen=True, slots=True)
class OfferObservation:
    offer_id: OfferId
    level: ObservationLevel
    url: str | None = None
    title: str | None = None
    price: Price | None = None
    location: str | None = None
    thumbnail_url: str | None = None
    posted_at: datetime | None = None
    refreshed_at: datetime | None = None
    promoted: bool = False
    has_delivery: bool = False
    description: str | None = None
    params: Params | None = None
    status: OfferStatus | None = None
    seller: SellerRef | None = None
    image_urls: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        require_aware_or_none(self.posted_at, "posted_at")
        require_aware_or_none(self.refreshed_at, "refreshed_at")
        if self.level is ObservationLevel.DETAILS and self.description is None:
            raise InvalidValueError("a DETAILS observation must include the description")

    @property
    def is_detail_complete(self) -> bool:
        return self.level is ObservationLevel.DETAILS

    def field_presence(self) -> dict[str, bool]:
        """Which fields were observed; feeds per-run fill-rate metrics (ADR 0005)."""
        names = LISTING_FIELDS + (DETAIL_FIELDS if self.is_detail_complete else ())
        return {name: getattr(self, name) is not None for name in names}

"""Offer aggregate, observations and the change/re-fetch rules (R4, R7, R8, R9)."""

from scrappy.domain.offer.observation import (
    DETAIL_FIELDS,
    LISTING_FIELDS,
    ObservationLevel,
    OfferObservation,
)
from scrappy.domain.offer.offer import (
    FieldChange,
    FieldValue,
    Offer,
    OfferSnapshot,
    TrackedField,
    needs_details,
    snapshot_for,
    status_after_fetch,
)
from scrappy.domain.offer.values import (
    ContentHash,
    OfferId,
    OfferStatus,
    Params,
    Price,
    PriceKind,
    SellerRef,
    compute_content_hash,
)

__all__ = [
    "DETAIL_FIELDS",
    "LISTING_FIELDS",
    "ContentHash",
    "FieldChange",
    "FieldValue",
    "ObservationLevel",
    "Offer",
    "OfferId",
    "OfferObservation",
    "OfferSnapshot",
    "OfferStatus",
    "Params",
    "Price",
    "PriceKind",
    "SellerRef",
    "TrackedField",
    "compute_content_hash",
    "needs_details",
    "snapshot_for",
    "status_after_fetch",
]

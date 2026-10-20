"""Evaluation of offer liveness (alive vs stale vs zombie/ghost listing).

Formulated to filter out ghost/abandoned listings on platforms like OLX.pl, where
offers are automatically renewed by the system long after the seller has stopped
logging in, and inactive listings stay online indefinitely with active 'Buy now' buttons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from scrappy.domain.offer.values import OfferStatus

if TYPE_CHECKING:
    from scrappy.domain.offer.offer import Offer


class LivenessStatus(StrEnum):
    ALIVE = "alive"
    """Seller is recently active, offer is fresh or maintained."""
    STALE = "stale"
    """Borderline activity (e.g. seller inactive for 1-2 weeks), risk of slow response."""
    ZOMBIE = "zombie"
    """Abandoned/ghost offer: auto-renewed while seller is inactive, or seller gone >1 month."""


@dataclass(frozen=True, slots=True)
class LivenessEvaluation:
    status: LivenessStatus
    score: int  # 0..100
    reasons: tuple[str, ...]

    @property
    def is_alive(self) -> bool:
        return self.status is LivenessStatus.ALIVE


def evaluate_liveness(offer: Offer, at: datetime | None = None) -> LivenessEvaluation:
    now = at or datetime.now(UTC)

    # 0. Immediate death for removed / sold offers
    if offer.status is not OfferStatus.ACTIVE:
        return LivenessEvaluation(
            status=LivenessStatus.ZOMBIE,
            score=0,
            reasons=(f"Offer is {offer.status.value}",),
        )

    reasons: list[str] = []
    score = 50  # baseline starting score

    # 1. Scraper fresh confirmation: Was it seen in our latest scrape?
    delta_scrape = now - offer.last_seen_at
    if delta_scrape > timedelta(days=2):
        score -= 35
        reasons.append(f"Not seen in scrape for {delta_scrape.days}d (likely removed)")
    elif delta_scrape > timedelta(hours=24):
        score -= 15
        reasons.append("Not seen in latest 24h scrape")
    else:
        reasons.append("Confirmed live in latest scrape")

    seller = offer.seller
    last_seen = seller.last_seen_at if seller else None
    refreshed_at = offer.refreshed_at
    posted_at = offer.posted_at

    # 2. Seller activity (highest weight)
    if last_seen is not None:
        delta_seen = now - last_seen
        if delta_seen <= timedelta(hours=24):
            score += 35
            reasons.append("Seller online in the last 24h")
        elif delta_seen <= timedelta(days=3):
            score += 25
            reasons.append("Seller online in the last 3 days")
        elif delta_seen <= timedelta(days=7):
            score += 15
            reasons.append("Seller online in the last 7 days")
        elif delta_seen <= timedelta(days=14):
            score += 0
            reasons.append("Seller inactive for 1-2 weeks")
        elif delta_seen <= timedelta(days=30):
            score -= 25
            reasons.append(f"Seller inactive for {delta_seen.days} days")
        else:
            score -= 45
            reasons.append(f"Seller abandoned account ({delta_seen.days} days ago)")
    elif seller and seller.is_online:
        score += 35
        reasons.append("Seller is currently online")
    else:
        score -= 20
        reasons.append("Seller activity unverified (no login timestamp)")

    # 2. Critical Zombie Detection: Auto-renewed while seller was inactive
    if (
        refreshed_at is not None
        and last_seen is not None
        and refreshed_at > last_seen + timedelta(hours=24)
    ):
        gap_days = max(1, (refreshed_at - last_seen).days)
        score -= 40
        reasons.append(f"Auto-renewed by platform {gap_days}d after seller became inactive")

    # 3. Listing age
    if posted_at is not None:
        age_days = (now - posted_at).days
        if age_days <= 7:
            score += 15
            reasons.append(f"New listing ({age_days}d old)")
        elif age_days <= 30:
            score += 5
        elif age_days > 180:
            score -= 25
            reasons.append(f"Listing older than 6 months ({age_days}d)")
        elif age_days > 90:
            score -= 15
            reasons.append(f"Listing older than 3 months ({age_days}d)")

    # 4. Delivery / Safe buy safety check
    if offer.has_delivery:
        if last_seen is not None and (now - last_seen) > timedelta(days=14):
            score -= 10
            reasons.append("Delivery enabled on inactive account (frozen funds risk)")
        else:
            score += 10
            reasons.append("Delivery available")

    # 5. Throwaway account detection
    if (
        seller
        and seller.created_at is not None
        and posted_at is not None
        and abs((posted_at - seller.created_at).total_seconds()) < 3600
        and last_seen is not None
        and (last_seen - seller.created_at).total_seconds() < 3600 * 2
        and (now - seller.created_at) > timedelta(days=14)
    ):
        score -= 15
        reasons.append("Throwaway seller account (created only to post and abandoned)")

    # Clamp score to 0..100
    score = max(0, min(100, score))

    if score >= 65:
        status = LivenessStatus.ALIVE
    elif score >= 35:
        status = LivenessStatus.STALE
    else:
        status = LivenessStatus.ZOMBIE

    return LivenessEvaluation(status=status, score=score, reasons=tuple(reasons))

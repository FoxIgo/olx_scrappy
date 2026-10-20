from datetime import UTC, datetime, timedelta

from scrappy.domain.offer import (
    LivenessStatus,
    Offer,
    OfferStatus,
    SellerRef,
    evaluate_liveness,
)
from tests.unit.builders import at, details, listing

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def make_offer(
    *,
    posted_at: datetime | None = None,
    refreshed_at: datetime | None = None,
    has_delivery: bool = False,
    seller: SellerRef | None = None,
    last_seen_at: datetime = NOW,
) -> Offer:
    offer = Offer.from_observation(listing("1"), at(0))
    offer.apply(details("1"), at(1))
    offer.posted_at = posted_at
    offer.refreshed_at = refreshed_at
    offer.has_delivery = has_delivery
    offer.seller = seller
    offer.last_seen_at = last_seen_at
    return offer


class TestLivenessEvaluation:
    def test_active_seller_fresh_listing_is_alive(self) -> None:
        seller = SellerRef(
            external_id="123",
            name="John",
            created_at=NOW - timedelta(days=100),
            last_seen_at=NOW - timedelta(hours=2),
            is_online=True,
        )
        offer = make_offer(
            posted_at=NOW - timedelta(days=2),
            refreshed_at=NOW - timedelta(days=1),
            has_delivery=True,
            seller=seller,
        )
        evaluation = evaluate_liveness(offer, at=NOW)
        assert evaluation.status is LivenessStatus.ALIVE
        assert evaluation.is_alive
        assert evaluation.score >= 70
        assert any("24h" in r for r in evaluation.reasons)

    def test_zombie_auto_renewed_listing_is_zombie(self) -> None:
        # User last seen in March, ad auto-renewed in October (211 days later)
        seller = SellerRef(
            external_id="2551325898",
            name="Bipo",
            created_at=datetime(2026, 3, 4, 15, 15, tzinfo=UTC),
            last_seen_at=datetime(2026, 3, 4, 15, 23, tzinfo=UTC),
            is_online=False,
        )
        offer = make_offer(
            posted_at=datetime(2026, 3, 5, 11, 20, tzinfo=UTC),
            refreshed_at=datetime(2026, 10, 1, 12, 6, tzinfo=UTC),
            has_delivery=True,
            seller=seller,
        )
        evaluation = evaluate_liveness(offer, at=NOW)
        assert evaluation.status is LivenessStatus.ZOMBIE
        assert not evaluation.is_alive
        assert evaluation.score < 35
        # Reasons should clearly highlight auto-renew and abandoned account
        assert any("Auto-renewed" in r for r in evaluation.reasons)
        assert any("abandoned" in r for r in evaluation.reasons)

    def test_stale_listing_borderline(self) -> None:
        seller = SellerRef(
            external_id="123",
            name="Alice",
            created_at=NOW - timedelta(days=200),
            last_seen_at=NOW - timedelta(days=10),
            is_online=False,
        )
        offer = make_offer(
            posted_at=NOW - timedelta(days=25),
            refreshed_at=NOW - timedelta(days=12),
            seller=seller,
        )
        evaluation = evaluate_liveness(offer, at=NOW)
        assert evaluation.status is LivenessStatus.STALE

    def test_throwaway_account_penalty(self) -> None:
        created = NOW - timedelta(days=40)
        seller = SellerRef(
            external_id="fake",
            created_at=created,
            last_seen_at=created + timedelta(minutes=15),
            is_online=False,
        )
        offer = make_offer(
            posted_at=created + timedelta(minutes=5),
            refreshed_at=created + timedelta(minutes=5),
            seller=seller,
        )
        evaluation = evaluate_liveness(offer, at=NOW)
        assert evaluation.status is LivenessStatus.ZOMBIE
        assert any("Throwaway" in r for r in evaluation.reasons)

    def test_removed_offer_is_zombie(self) -> None:
        offer = make_offer()
        offer.status = OfferStatus.REMOVED
        evaluation = evaluate_liveness(offer, at=NOW)
        assert evaluation.status is LivenessStatus.ZOMBIE
        assert evaluation.score == 0

    def test_not_seen_in_recent_scrapes_is_penalized(self) -> None:
        seller = SellerRef(
            external_id="123",
            name="John",
            created_at=NOW - timedelta(days=100),
            last_seen_at=NOW - timedelta(hours=2),
            is_online=True,
        )
        # Offer last seen by scraper 3 days ago (vanished from search)
        offer = make_offer(
            seller=seller,
            last_seen_at=NOW - timedelta(days=3),
        )
        evaluation = evaluate_liveness(offer, at=NOW)
        assert any("Not seen in scrape" in r for r in evaluation.reasons)
        assert evaluation.score < 65

from dataclasses import replace

import pytest

from scrappy.domain.offer import (
    FieldChange,
    Offer,
    OfferStatus,
    Params,
    Price,
    TrackedField,
    needs_details,
    snapshot_for,
    status_after_fetch,
)
from scrappy.domain.shared import FetchOutcome, InvalidValueError, RunId
from tests.unit.builders import at, details, listing, oid


def enriched_offer() -> Offer:
    offer = Offer.from_observation(listing("1"), at(0))
    offer.apply(details("1"), at(1))
    return offer


class TestCreation:
    def test_new_offer_from_listing(self) -> None:
        offer = Offer.from_observation(listing("1"), at(0))
        assert offer.title == "Laptop GTX 1650"
        assert offer.status is OfferStatus.UNKNOWN
        assert offer.first_seen_at == offer.last_seen_at == at(0)
        assert not offer.has_details
        assert offer.content_hash is None  # no description yet

    def test_new_offer_needs_url(self) -> None:
        with pytest.raises(InvalidValueError):
            Offer.from_observation(listing("1", url=None), at(0))

    def test_detail_complete_first_observation_sets_details_and_hash(self) -> None:
        offer = Offer.from_observation(details("1"), at(0))
        assert offer.has_details
        assert offer.status is OfferStatus.ACTIVE
        assert offer.content_hash is not None


class TestApplyObservation:
    def test_first_enrichment_fills_fields_without_changes(self) -> None:
        offer = Offer.from_observation(listing("1"), at(0))
        changes = offer.apply(details("1"), at(1))
        assert changes == []  # first observation of description/params/status: not a change
        assert offer.details_fetched_at == at(1)
        assert offer.status is OfferStatus.ACTIVE

    def test_price_change_is_reported(self) -> None:
        offer = enriched_offer()
        changes = offer.apply(listing("1", price=Price.fixed(900)), at(2))
        assert changes == [FieldChange(TrackedField.PRICE, Price.fixed(1000), Price.fixed(900))]
        assert offer.price == Price.fixed(900)

    def test_price_kind_change_is_a_change(self) -> None:
        offer = enriched_offer()
        changes = offer.apply(listing("1", price=Price.exchange()), at(2))
        assert [c.field for c in changes] == [TrackedField.PRICE]

    def test_missing_is_not_changed(self) -> None:
        """ADR 0005: a parser that stops finding the price must not record price -> null."""
        offer = enriched_offer()
        observation = replace(details("1"), price=None, title=None, params=None, status=None)
        changes = offer.apply(observation, at(2))
        assert changes == []
        assert offer.price == Price.fixed(1000)
        assert offer.title == "Laptop GTX 1650"
        assert offer.params == Params.of({"state": "used"})
        assert offer.status is OfferStatus.ACTIVE

    def test_unknown_status_is_not_a_change(self) -> None:
        offer = enriched_offer()
        assert offer.apply(details("1", status=OfferStatus.UNKNOWN), at(2)) == []
        assert offer.status is OfferStatus.ACTIVE

    def test_several_tracked_fields(self) -> None:
        offer = enriched_offer()
        changes = offer.apply(
            details("1", description="New text", params={"state": "new"}, status=OfferStatus.SOLD),
            at(2),
        )
        assert {c.field for c in changes} == {
            TrackedField.DESCRIPTION,
            TrackedField.PARAMS,
            TrackedField.STATUS,
        }

    def test_untracked_fields_update_silently(self) -> None:
        offer = enriched_offer()
        assert offer.has_delivery is False
        changes = offer.apply(
            listing("1", refreshed_at=at(5), url="https://new.test/1", has_delivery=True), at(6)
        )
        assert changes == []
        assert offer.refreshed_at == at(5)
        assert offer.url == "https://new.test/1"
        assert offer.has_delivery is True

    def test_idempotent(self) -> None:
        offer = enriched_offer()
        observation = details("1", description="Changed")
        assert offer.apply(observation, at(2))
        assert offer.apply(observation, at(3)) == []

    def test_content_hash_follows_content_only(self) -> None:
        offer = enriched_offer()
        original = offer.content_hash
        offer.apply(listing("1", price=Price.fixed(1)), at(2))
        assert offer.content_hash == original  # price is not content
        offer.apply(listing("1", title="Laptop GTX 1650 Ti"), at(3))
        assert offer.content_hash != original  # title is

    def test_last_seen_never_goes_back(self) -> None:
        offer = enriched_offer()
        offer.apply(listing("1"), at(10))
        offer.apply(listing("1"), at(5))
        assert offer.last_seen_at == at(10)

    def test_wrong_offer_rejected(self) -> None:
        with pytest.raises(InvalidValueError):
            enriched_offer().apply(listing("2"), at(2))


class TestSnapshots:
    def test_no_changes_no_snapshot(self) -> None:
        assert snapshot_for(oid("1"), [], at(0)) is None

    def test_snapshot_holds_changes(self) -> None:
        change = FieldChange(TrackedField.TITLE, "a", "b")
        snapshot = snapshot_for(oid("1"), [change], at(0), RunId("r1"))
        assert snapshot is not None
        assert snapshot.changes == (change,)
        assert snapshot.run_id == RunId("r1")


class TestNeedsDetails:
    def test_new_offer(self) -> None:
        assert needs_details(None, listing("1"))

    def test_never_enriched(self) -> None:
        assert needs_details(Offer.from_observation(listing("1"), at(0)), listing("1"))

    def test_unchanged(self) -> None:
        assert not needs_details(enriched_offer(), listing("1"))

    @pytest.mark.parametrize(
        "observation",
        [
            listing("1", price=Price.fixed(999)),
            listing("1", title="Other title"),
            listing("1", refreshed_at=at(99)),
        ],
    )
    def test_list_data_changed(self, observation: object) -> None:
        offer = enriched_offer()
        offer.refreshed_at = at(1)
        assert needs_details(offer, observation)  # type: ignore[arg-type]

    def test_missing_list_fields_do_not_trigger(self) -> None:
        offer = enriched_offer()
        offer.refreshed_at = at(1)
        missing = replace(listing("1"), price=None, title=None, refreshed_at=None)
        assert not needs_details(offer, missing)

    def test_detail_complete_observation_never_needs_details(self) -> None:
        assert not needs_details(None, details("1"))
        assert not needs_details(enriched_offer(), details("1", price=Price.fixed(1)))


class TestStatusAfterFetch:
    @pytest.mark.parametrize(
        ("outcome", "observed", "known", "expected"),
        [
            (FetchOutcome.OK, OfferStatus.ACTIVE, True, OfferStatus.ACTIVE),
            (FetchOutcome.OK, None, True, None),
            (FetchOutcome.GONE, None, True, OfferStatus.REMOVED),
            (FetchOutcome.GONE, OfferStatus.SOLD, True, OfferStatus.SOLD),
            (FetchOutcome.GONE, OfferStatus.ACTIVE, True, OfferStatus.REMOVED),
            (FetchOutcome.NOT_FOUND, None, True, OfferStatus.REMOVED),
            (FetchOutcome.NOT_FOUND, None, False, None),
            (FetchOutcome.BLOCKED, None, True, None),
            (FetchOutcome.TRANSIENT, None, True, None),
        ],
    )
    def test_table(
        self,
        outcome: FetchOutcome,
        observed: OfferStatus | None,
        known: bool,
        expected: OfferStatus | None,
    ) -> None:
        assert status_after_fetch(outcome, observed, offer_known=known) is expected

    def test_record_unavailable_on_active_offer(self) -> None:
        offer = enriched_offer()
        changes = offer.record_unavailable(FetchOutcome.GONE, OfferStatus.SOLD, at(5))
        assert changes == [FieldChange(TrackedField.STATUS, OfferStatus.ACTIVE, OfferStatus.SOLD)]
        assert offer.details_fetched_at == at(5)

    def test_record_unavailable_on_never_enriched_offer_is_not_a_change(self) -> None:
        offer = Offer.from_observation(listing("1"), at(0))
        assert offer.record_unavailable(FetchOutcome.NOT_FOUND, None, at(1)) == []
        assert offer.status is OfferStatus.REMOVED

    def test_record_unavailable_rejects_other_outcomes(self) -> None:
        with pytest.raises(InvalidValueError):
            enriched_offer().record_unavailable(FetchOutcome.BLOCKED, None, at(1))

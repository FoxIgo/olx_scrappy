"""Unit tests for the VerifyOffers use case."""

from __future__ import annotations

import pytest

from scrappy.application.ports.listing_source import OfferDetailsResult
from scrappy.domain.offer import Offer, OfferStatus, TrackedField
from scrappy.domain.shared import FetchOutcome
from tests.unit.application.harness import App
from tests.unit.builders import at, details, listing, oid
from tests.unit.fakes import ScriptedListingSource


@pytest.fixture
def app() -> App:
    return App()


@pytest.fixture
def source(app: App) -> ScriptedListingSource:
    return app.add_source("olx_pl")


async def seed_offer(app: App, external_id: str, source: str = "olx_pl") -> Offer:
    offer = Offer.from_observation(listing(external_id, source=source), at(0))
    offer.apply(details(external_id, source=source), at(1))
    async with app.store.uow() as uow:
        await uow.offers.save(offer)
        await uow.commit()
    return offer


class TestVerifyOffers:
    async def test_active_offer_confirmed_live(
        self, app: App, source: ScriptedListingSource
    ) -> None:
        await seed_offer(app, "1")
        source.script_details(oid("1"), OfferDetailsResult.ok(details("1")))

        result = await app.verify_offers.verify_one(oid("1"))

        assert result.is_active is True
        assert result.current_status is OfferStatus.ACTIVE
        assert result.previous_status is OfferStatus.ACTIVE
        assert result.changed is False
        assert result.outcome == "active"
        assert result.message == "Confirmed active on source"

        async with app.store.uow() as uow:
            loaded = await uow.offers.get(oid("1"))
            assert loaded is not None
            assert loaded.status is OfferStatus.ACTIVE

    async def test_gone_offer_marked_removed_and_snapshot_recorded(
        self, app: App, source: ScriptedListingSource
    ) -> None:
        await seed_offer(app, "1")
        source.script_details(
            oid("1"),
            OfferDetailsResult.gone(OfferStatus.REMOVED, "HTTP 410: Ad is gone"),
        )

        result = await app.verify_offers.verify_one(oid("1"))

        assert result.is_active is False
        assert result.current_status is OfferStatus.REMOVED
        assert result.previous_status is OfferStatus.ACTIVE
        assert result.changed is True
        assert result.outcome == "removed"

        async with app.store.uow() as uow:
            loaded = await uow.offers.get(oid("1"))
            assert loaded is not None
            assert loaded.status is OfferStatus.REMOVED
            snapshots = await uow.offers.list_snapshots(oid("1"))
            assert len(snapshots) == 1
            status_changes = [c for c in snapshots[0].changes if c.field is TrackedField.STATUS]
            assert len(status_changes) == 1
            assert status_changes[0].old is OfferStatus.ACTIVE
            assert status_changes[0].new is OfferStatus.REMOVED

    async def test_not_found_outcome_marks_removed(
        self, app: App, source: ScriptedListingSource
    ) -> None:
        await seed_offer(app, "1")
        source.script_details(oid("1"), OfferDetailsResult.not_found("404 Not Found"))

        result = await app.verify_offers.verify_one(oid("1"))

        assert result.is_active is False
        assert result.current_status is OfferStatus.REMOVED
        assert result.changed is True

        async with app.store.uow() as uow:
            loaded = await uow.offers.get(oid("1"))
            assert loaded is not None
            assert loaded.status is OfferStatus.REMOVED

    async def test_transient_error_preserves_status(
        self, app: App, source: ScriptedListingSource
    ) -> None:
        await seed_offer(app, "1")
        source.script_details(
            oid("1"),
            OfferDetailsResult.failed(FetchOutcome.BLOCKED, "Blocked 429"),
        )

        result = await app.verify_offers.verify_one(oid("1"))

        assert result.is_active is True
        assert result.current_status is OfferStatus.ACTIVE
        assert result.changed is False
        assert result.outcome == "error"

        async with app.store.uow() as uow:
            loaded = await uow.offers.get(oid("1"))
            assert loaded is not None
            assert loaded.status is OfferStatus.ACTIVE
            snapshots = await uow.offers.list_snapshots(oid("1"))
            assert len(snapshots) == 0

    async def test_offer_not_in_database(self, app: App) -> None:
        result = await app.verify_offers.verify_one(oid("404"))
        assert result.is_active is False
        assert result.outcome == "not_found"
        assert result.changed is False

    async def test_unknown_source(self, app: App) -> None:
        offer = Offer.from_observation(listing("1", source="unknown_src"), at(0))
        async with app.store.uow() as uow:
            await uow.offers.save(offer)
            await uow.commit()

        result = await app.verify_offers.verify_one(oid("1", source="unknown_src"))
        assert result.outcome == "error"
        assert result.message is not None
        assert "unknown source" in result.message

    async def test_verify_many(self, app: App, source: ScriptedListingSource) -> None:
        await seed_offer(app, "1")
        await seed_offer(app, "2")
        source.script_details(oid("1"), OfferDetailsResult.ok(details("1")))
        source.script_details(oid("2"), OfferDetailsResult.gone(OfferStatus.REMOVED, "Gone"))

        results = await app.verify_offers.verify_many([oid("1"), oid("2")])

        assert len(results) == 2
        assert results[0].is_active is True
        assert results[1].is_active is False

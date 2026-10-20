"""VerifyOffers: check freshness / live status of stored offers against their source."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from scrappy.application.ports.listing_source import ListingSources, OfferDetailsRequest
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.offer import OfferId, OfferStatus, snapshot_for
from scrappy.domain.shared import FetchOutcome


@dataclass(frozen=True, slots=True)
class VerifyOfferResult:
    offer_id: OfferId
    title: str | None
    previous_status: OfferStatus
    current_status: OfferStatus
    outcome: str
    is_active: bool
    changed: bool
    url: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.offer_id),
            "title": self.title,
            "url": self.url,
            "previous_status": self.previous_status.value,
            "current_status": self.current_status.value,
            "outcome": self.outcome,
            "is_active": self.is_active,
            "changed": self.changed,
            "message": self.message,
        }


class VerifyOffers:
    """Verify stored offers against their source (e.g. OLX) live on-demand.

    Checks whether each offer is still active on the source, updates offer status in
    the database (marking sold/removed offers as unavailable), and creates snapshot
    records when status changes.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        sources: ListingSources,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._sources = sources
        self._clock = clock

    async def verify_one(self, offer_id: OfferId) -> VerifyOfferResult:
        results = await self.verify_many([offer_id])
        return results[0]

    async def verify_many(self, offer_ids: Sequence[OfferId]) -> list[VerifyOfferResult]:
        results: list[VerifyOfferResult] = []
        for oid in offer_ids:
            res = await self._verify_single(oid)
            results.append(res)
        return results

    async def _verify_single(self, offer_id: OfferId) -> VerifyOfferResult:
        now = self._clock.now()

        async with self._uow() as uow:
            offer = await uow.offers.get(offer_id)

        if offer is None:
            return VerifyOfferResult(
                offer_id=offer_id,
                title=None,
                previous_status=OfferStatus.UNKNOWN,
                current_status=OfferStatus.UNKNOWN,
                outcome="not_found",
                is_active=False,
                changed=False,
                message="offer not found in database",
            )

        old_status = offer.status
        source = self._sources.get(offer_id.source)
        if source is None:
            return VerifyOfferResult(
                offer_id=offer_id,
                title=offer.title,
                url=offer.url,
                previous_status=old_status,
                current_status=old_status,
                outcome="error",
                is_active=old_status is OfferStatus.ACTIVE,
                changed=False,
                message=f"unknown source {offer_id.source}",
            )

        request = OfferDetailsRequest(offer_id, offer.url)
        try:
            details = await source.fetch_offer_details(request)
        except Exception as exc:
            return VerifyOfferResult(
                offer_id=offer_id,
                title=offer.title,
                url=offer.url,
                previous_status=old_status,
                current_status=old_status,
                outcome="error",
                is_active=old_status is OfferStatus.ACTIVE,
                changed=False,
                message=f"fetch error: {exc}",
            )

        # 1. Transient error or rate limit
        if details.outcome.is_retryable:
            return VerifyOfferResult(
                offer_id=offer_id,
                title=offer.title,
                url=offer.url,
                previous_status=old_status,
                current_status=old_status,
                outcome="error",
                is_active=old_status is OfferStatus.ACTIVE,
                changed=False,
                message=details.message or details.outcome.value,
            )

        # 2. Offer rejected during parsing
        if details.rejection is not None:
            return VerifyOfferResult(
                offer_id=offer_id,
                title=offer.title,
                url=offer.url,
                previous_status=old_status,
                current_status=old_status,
                outcome="error",
                is_active=old_status is OfferStatus.ACTIVE,
                changed=False,
                message=details.rejection.reason,
            )

        # 3. GONE or NOT_FOUND on source (404, 410, status != active)
        if details.outcome in (FetchOutcome.GONE, FetchOutcome.NOT_FOUND):
            changes = offer.record_unavailable(details.outcome, details.observed_status, now)
            snapshot = snapshot_for(offer_id, changes, now, run_id=None)
            async with self._uow() as uow:
                if snapshot is not None:
                    await uow.offers.add_snapshot(snapshot)
                await uow.offers.save(offer)
                await uow.commit()

            return VerifyOfferResult(
                offer_id=offer_id,
                title=offer.title,
                url=offer.url,
                previous_status=old_status,
                current_status=offer.status,
                outcome=offer.status.value,
                is_active=False,
                changed=old_status is not offer.status,
                message=details.message or f"Offer is {offer.status.value}",
            )

        # 4. OK observation (confirmed active on source)
        if details.observation is not None:
            changes = offer.apply(details.observation, now)
            snapshot = snapshot_for(offer_id, changes, now, run_id=None)
            async with self._uow() as uow:
                if snapshot is not None:
                    await uow.offers.add_snapshot(snapshot)
                await uow.offers.save(offer)
                await uow.commit()

            return VerifyOfferResult(
                offer_id=offer_id,
                title=offer.title,
                url=offer.url,
                previous_status=old_status,
                current_status=offer.status,
                outcome=offer.status.value,
                is_active=offer.status is OfferStatus.ACTIVE,
                changed=old_status is not offer.status or bool(changes),
                message="Confirmed active on source",
            )

        # 5. Unexpected outcome
        return VerifyOfferResult(
            offer_id=offer_id,
            title=offer.title,
            url=offer.url,
            previous_status=old_status,
            current_status=old_status,
            outcome="unknown",
            is_active=old_status is OfferStatus.ACTIVE,
            changed=False,
            message=details.message or "no observation returned",
        )

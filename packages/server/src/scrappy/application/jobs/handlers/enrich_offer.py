"""EnrichOffer: fetch one offer page, update state and status."""

from __future__ import annotations

from scrappy.application.jobs.errors import PermanentJobError, RetryableJobError
from scrappy.application.jobs.handlers.common import rejection_notes, source_for
from scrappy.application.jobs.model import EnrichOfferPayload, Job, JobResult
from scrappy.application.ports.listing_source import ListingSources, OfferDetailsRequest
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.offer import Offer, snapshot_for
from scrappy.domain.run import PhaseMetrics, RunMetrics
from scrappy.domain.shared import FetchOutcome


class EnrichOfferHandler:
    """Flow (ADR 0006, R3, R7, R9):

    * OK + observation: apply (snapshot if tracked fields changed). A changed content hash
      puts the offer in the extraction backlog by itself (ADR 0010); nothing is enqueued.
      An unknown offer (explicit refresh of a new id) is created from the observation.
    * OK + rejection: counted as rejected; the offer is left as is (it stays without
      details, so the next run tries again). Not retried: parsing is deterministic.
    * GONE / NOT_FOUND: a known offer gets its status updated (NOT_FOUND of a known offer
      means REMOVED); an unknown id is simply not stored.
    * BLOCKED / TRANSIENT: :class:`RetryableJobError`, nothing written.
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

    async def handle(self, job: Job) -> JobResult:
        payload = job.payload
        if not isinstance(payload, EnrichOfferPayload):
            raise PermanentJobError(f"EnrichOfferHandler cannot handle job {job.id}")
        offer_id = payload.offer_id
        source = source_for(self._sources, offer_id.source)

        async with self._uow() as uow:
            known = await uow.offers.get(offer_id)
        request = OfferDetailsRequest(offer_id, known.url if known else None)

        details = await source.fetch_offer_details(request)
        metrics = PhaseMetrics().with_outcome(details.outcome)

        if details.outcome.is_retryable:
            raise RetryableJobError(
                f"offer {offer_id}: {details.outcome.value}"
                + (f" ({details.message})" if details.message else ""),
                retry_after=details.retry_after,
                result=JobResult(RunMetrics(enrichment=metrics)),
            )

        if details.rejection is not None:
            return JobResult(
                RunMetrics(enrichment=metrics.with_rejected()),
                tuple(rejection_notes((details.rejection,))),
            )

        observation = details.observation
        if observation is not None and observation.offer_id != offer_id:
            note = f"source returned {observation.offer_id} for {offer_id}"
            return JobResult(RunMetrics(enrichment=metrics.with_rejected()), (note,))

        now = self._clock.now()
        notes: list[str] = []

        async with self._uow() as uow:
            offer = await uow.offers.get(offer_id)
            if observation is not None:
                metrics = metrics.with_accepted(observation.field_presence())
                if offer is None:
                    if observation.url is None:
                        return JobResult(
                            RunMetrics(enrichment=metrics),
                            (f"{offer_id}: cannot store a new offer without URL",),
                        )
                    offer = Offer.from_observation(observation, now)
                    changes = []
                else:
                    changes = offer.apply(observation, now)
            elif offer is None:
                # NOT_FOUND / GONE for an id we never stored: nothing to update.
                return JobResult(
                    RunMetrics(enrichment=metrics), (f"{offer_id}: {details.outcome.value}",)
                )
            else:
                assert details.outcome in (FetchOutcome.GONE, FetchOutcome.NOT_FOUND)
                changes = offer.record_unavailable(details.outcome, details.observed_status, now)
                notes.append(f"{offer_id}: {details.outcome.value} -> {offer.status.value}")

            snapshot = snapshot_for(offer_id, changes, now, job.run_id)
            if snapshot is not None:
                await uow.offers.add_snapshot(snapshot)
            await uow.offers.save(offer)
            await uow.commit()

        return JobResult(RunMetrics(enrichment=metrics), tuple(notes))

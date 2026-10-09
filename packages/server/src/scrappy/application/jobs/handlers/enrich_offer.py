"""EnrichOffer: fetch one offer page, update state and status, enqueue extraction."""

from __future__ import annotations

from scrappy.application.jobs.errors import PermanentJobError, RetryableJobError
from scrappy.application.jobs.handlers.common import new_job, rejection_notes, source_for
from scrappy.application.jobs.model import EnrichOfferPayload, ExtractOfferPayload, Job, JobResult
from scrappy.application.policy import PipelinePolicy
from scrappy.application.ports.listing_source import ListingSources, OfferDetailsRequest
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.extraction import needs_extraction
from scrappy.domain.offer import Offer, snapshot_for
from scrappy.domain.run import PhaseMetrics, RunMetrics
from scrappy.domain.shared import FetchOutcome


class EnrichOfferHandler:
    """Flow (ADR 0006, R3, R7, R9):

    * OK + observation: apply (snapshot if tracked fields changed), then enqueue
      ExtractOffer when auto-extraction is on and ``needs_extraction`` says so.
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
        categories: CategoryProvider,
        clock: Clock,
        ids: IdGenerator,
        policy: PipelinePolicy,
    ) -> None:
        self._uow = uow
        self._sources = sources
        self._categories = categories
        self._clock = clock
        self._ids = ids
        self._policy = policy

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

        catalog = await self._categories.catalog()
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

            if (
                observation is not None
                and self._policy.extraction.auto
                and offer.content_hash is not None
            ):
                latest = await uow.extractions.latest(offer_id)
                if needs_extraction(offer, latest, catalog):
                    await uow.jobs.enqueue(
                        new_job(
                            self._ids,
                            ExtractOfferPayload(offer_id, offer.content_hash, catalog.fingerprint),
                            run_id=job.run_id,
                            now=now,
                        )
                    )
            await uow.commit()

        return JobResult(RunMetrics(enrichment=metrics), tuple(notes))

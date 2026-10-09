"""DiscoverPage: fetch one search page, upsert offers, link them, enqueue follow-ups."""

from __future__ import annotations

from scrappy.application.jobs.errors import PermanentJobError, RetryableJobError
from scrappy.application.jobs.handlers.common import (
    new_job,
    rejection_notes,
    source_for,
)
from scrappy.application.jobs.model import (
    DiscoverPagePayload,
    EnrichOfferPayload,
    ExtractOfferPayload,
    Job,
    JobResult,
)
from scrappy.application.policy import PipelinePolicy
from scrappy.application.ports.listing_source import ListingSources, SearchPageResult
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.extraction import needs_extraction
from scrappy.domain.offer import Offer, OfferId, OfferObservation, needs_details, snapshot_for
from scrappy.domain.run import DiscoveryCoverage, PhaseMetrics, RunMetrics
from scrappy.domain.search import SearchOffer
from scrappy.domain.shared import FetchOutcome


class DiscoverPageHandler:
    """Flow (ADR 0006, R4, R8, R10):

    1. Fetch the page (outside any transaction).
    2. Deduplicate observations by offer id (promoted offers repeat).
    3. For each offer: decide ``needs_details`` *before* applying, apply the observation,
       write a snapshot if tracked fields changed, upsert the search link (deriving
       relevance from an existing extraction, so an offer is never classified twice).
    4. Enqueue EnrichOffer for offers that need details; for detail-complete observations
       enqueue ExtractOffer directly when auto-extraction is on and content changed.
    5. Enqueue the next page unless the max-pages cap is reached (then: truncated).
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
        if not isinstance(payload, DiscoverPagePayload) or job.run_id is None:
            raise PermanentJobError(f"DiscoverPageHandler cannot handle job {job.id}")
        run_id = job.run_id

        async with self._uow() as uow:
            search = await uow.searches.get(payload.search)
            run = await uow.runs.get(run_id)
        if search is None or run is None:
            raise PermanentJobError(f"run {run_id} or search {payload.search} no longer exists")
        source = source_for(self._sources, search.source)

        page = await source.fetch_search_page(payload.page)
        metrics = PhaseMetrics().with_outcome(page.outcome)

        if page.outcome.is_retryable:
            raise RetryableJobError(
                f"search page {payload.page.number}: {page.outcome.value}"
                + (f" ({page.message})" if page.message else ""),
                retry_after=page.retry_after,
                result=JobResult(RunMetrics(discovery=metrics)),
            )
        if page.outcome is not FetchOutcome.OK:
            # NOT_FOUND / GONE for a search page: the result set ends here.
            note = f"search page {payload.page.number} answered {page.outcome.value}"
            return JobResult(
                RunMetrics(discovery=metrics, coverage=DiscoveryCoverage(pages=1)), (note,)
            )

        observations = _unique_by_offer(page)
        metrics = metrics.with_rejected(len(page.rejections))

        catalog = await self._categories.catalog()
        now = self._clock.now()
        auto_extract = self._policy.extraction.auto
        ids = [o.offer_id for o in observations]
        notes = rejection_notes(page.rejections)
        capped = False

        async with self._uow() as uow:
            offers = await uow.offers.get_many(ids)
            links = await uow.search_offers.get_many(search.name, ids)
            extractions = await uow.extractions.latest_many(ids)

            for observation in observations:
                offer_id = observation.offer_id
                offer = offers.get(offer_id)
                enrich = needs_details(offer, observation)
                if offer is None:
                    if observation.url is None:
                        metrics = metrics.with_rejected()
                        notes.append(f"{offer_id}: new offer without URL")
                        continue
                    offer = Offer.from_observation(observation, now)
                else:
                    changes = offer.apply(observation, now)
                    snapshot = snapshot_for(offer_id, changes, now, run_id)
                    if snapshot is not None:
                        await uow.offers.add_snapshot(snapshot)
                await uow.offers.save(offer)
                metrics = metrics.with_accepted(observation.field_presence())

                link = links.get(offer_id)
                if link is None:
                    link = SearchOffer.first_seen(search.name, offer_id, now)
                    link.update_relevance(search, extractions.get(offer_id))
                else:
                    link.mark_seen(now)
                await uow.search_offers.save(link)

                if enrich:
                    await uow.jobs.enqueue(
                        new_job(self._ids, EnrichOfferPayload(offer_id), run_id=run_id, now=now)
                    )
                elif (
                    auto_extract
                    and offer.content_hash is not None
                    and needs_extraction(offer, extractions.get(offer_id), catalog)
                ):
                    await uow.jobs.enqueue(
                        new_job(
                            self._ids,
                            ExtractOfferPayload(offer_id, offer.content_hash, catalog.fingerprint),
                            run_id=run_id,
                            now=now,
                        )
                    )

            next_page = page.next_page
            if next_page is not None:
                if payload.page.number >= self._policy.discovery.max_pages:
                    capped = True
                    notes.append(
                        f"stopped at the max-pages cap ({self._policy.discovery.max_pages})"
                    )
                else:
                    await uow.jobs.enqueue(
                        new_job(
                            self._ids,
                            DiscoverPagePayload(search.name, next_page),
                            run_id=run_id,
                            now=now,
                        )
                    )
            await uow.commit()

        coverage = DiscoveryCoverage(
            pages=1, total_reported=page.total_results, truncated=page.truncated or capped
        )
        return JobResult(RunMetrics(discovery=metrics, coverage=coverage), tuple(notes))


def _unique_by_offer(page: SearchPageResult) -> list[OfferObservation]:
    """First occurrence wins, except that a detail-complete one replaces a listing one."""
    unique: dict[OfferId, OfferObservation] = {}
    for observation in page.observations:
        seen = unique.get(observation.offer_id)
        if seen is None or (observation.is_detail_complete and not seen.is_detail_complete):
            unique[observation.offer_id] = observation
    return list(unique.values())

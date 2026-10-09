"""ExtractOffer: prepared input -> AttributeExtractor -> validate -> store -> relevance."""

from __future__ import annotations

from scrappy.application.extraction.prepare import prepare_extraction_input
from scrappy.application.jobs.errors import PermanentJobError, RetryableJobError
from scrappy.application.jobs.model import ExtractOfferPayload, Job, JobResult
from scrappy.application.policy import PipelinePolicy
from scrappy.application.ports.extractor import AttributeExtractor, ExtractionRejection
from scrappy.application.ports.system import CategoryProvider, Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.extraction import OfferExtraction, TokenUsage, needs_extraction
from scrappy.domain.run import PhaseMetrics, RunMetrics
from scrappy.domain.shared import InvalidValueError


class ExtractOfferHandler:
    """Flow (ADR 0007):

    1. Skip if the offer's content changed since the job was created (a newer job exists)
       or, unless forced, if ``needs_extraction`` is false (idempotency: a re-run of a
       finished job makes no second LLM call).
    2. Prepare the input deterministically and call the extractor (no transaction open).
    3. Validate in the domain; a rejection is counted and the offer stays
       "extraction pending" (no extraction stored). Provider trouble is retried.
    4. Store the extraction with provenance and re-derive relevance on every search link
       of the offer (classification once per offer, relevance per search).
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        extractor: AttributeExtractor,
        categories: CategoryProvider,
        clock: Clock,
        policy: PipelinePolicy,
    ) -> None:
        self._uow = uow
        self._extractor = extractor
        self._categories = categories
        self._clock = clock
        self._policy = policy

    async def handle(self, job: Job) -> JobResult:
        payload = job.payload
        if not isinstance(payload, ExtractOfferPayload):
            raise PermanentJobError(f"ExtractOfferHandler cannot handle job {job.id}")
        offer_id = payload.offer_id
        catalog = await self._categories.catalog()

        async with self._uow() as uow:
            offer = await uow.offers.get(offer_id)
            latest = await uow.extractions.latest(offer_id)
        if offer is None:
            raise PermanentJobError(f"offer {offer_id} does not exist")
        if offer.content_hash != payload.content_hash:
            return JobResult(notes=(f"{offer_id}: content changed since enqueue, skipped",))
        if payload.force:
            already_done = (
                latest is not None
                and latest.provenance.content_hash == payload.content_hash
                and latest.provenance.extracted_at >= job.created_at
            )
            if already_done:
                return JobResult(notes=(f"{offer_id}: forced extraction already done",))
        elif not needs_extraction(offer, latest, catalog):
            return JobResult(notes=(f"{offer_id}: extraction up to date, skipped",))

        request = prepare_extraction_input(
            offer, catalog, max_chars=self._policy.extraction.description_max_chars
        )
        answer = await self._extractor.extract(request)

        if isinstance(answer, ExtractionRejection):
            result = _rejected(answer.usage, f"{offer_id}: extraction rejected: {answer.reason}")
            if answer.retryable:
                raise RetryableJobError(answer.reason, result=result)
            return result

        try:
            extraction = OfferExtraction.validated(
                offer_id=offer_id,
                category=answer.category,
                raw_attributes=answer.attributes,
                catalog=catalog,
                model=answer.model,
                prompt_version=answer.prompt_version,
                content_hash=payload.content_hash,
                extracted_at=self._clock.now(),
                usage=answer.usage,
                notes=answer.notes,
            )
        except InvalidValueError as error:
            return _rejected(answer.usage, f"{offer_id}: invalid extraction: {error}")

        async with self._uow() as uow:
            await uow.extractions.add(extraction)
            for link in await uow.search_offers.list_for_offer(offer_id):
                search = await uow.searches.get(link.search)
                if search is None:
                    continue
                link.update_relevance(search, extraction)
                await uow.search_offers.save(link)
            await uow.commit()

        presence = {
            f"{extraction.category}.{name}": value is not None
            for name, value in extraction.attributes.items()
        }
        metrics = PhaseMetrics().with_accepted(presence)
        return JobResult(RunMetrics(extraction=metrics, usage=extraction.usage))


def _rejected(usage: TokenUsage, note: str) -> JobResult:
    return JobResult(RunMetrics(extraction=PhaseMetrics().with_rejected(), usage=usage), (note,))

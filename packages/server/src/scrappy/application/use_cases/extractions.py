"""RequeueExtractions: (re-)extract from stored data, no scraping (ADR 0006, ADR 0007)."""

from __future__ import annotations

from dataclasses import dataclass

from scrappy.application.jobs.handlers.common import new_job
from scrappy.application.jobs.model import ExtractOfferPayload
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import needs_extraction
from scrappy.domain.offer import OfferId


@dataclass(frozen=True, slots=True)
class RequeueExtractionsResult:
    considered: int
    enqueued: int
    already_queued: int


class RequeueExtractions:
    """Enqueue ExtractOffer jobs (``run_id=None``) for stored offers.

    * ``category=None, force=False``: every offer that ``needs_extraction`` (never
      extracted, content changed, or its category's schema version changed). This is
      ``scrappy extract --pending``; with ``pipeline.extract.auto=false`` it is the only
      trigger.
    * ``category=laptop``: only offers currently classified as ``laptop``. After bumping
      the laptop schema version in config they all need extraction again.
    * ``force=True``: re-extract regardless (e.g. a better model). Needs a request tag;
      one is derived from the clock when not given.

    Idempotent per ``request_tag``: keys are ``extract:{offer}:{hash}:{catalog}[:{tag}]``.
    Without a tag the key equals the automatic one, so offers already queued for the same
    content and catalog are not queued twice.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        categories: CategoryProvider,
        clock: Clock,
        ids: IdGenerator,
        batch_size: int = 500,
    ) -> None:
        self._uow = uow
        self._categories = categories
        self._clock = clock
        self._ids = ids
        self._batch_size = batch_size

    async def __call__(
        self,
        *,
        category: CategoryName | None = None,
        force: bool = False,
        request_tag: str | None = None,
    ) -> RequeueExtractionsResult:
        catalog = await self._categories.catalog()
        now = self._clock.now()
        if force and request_tag is None:
            request_tag = "force-" + now.strftime("%Y%m%dT%H%M%S%f")
        considered = enqueued = already = 0
        after: OfferId | None = None

        while True:
            async with self._uow() as uow:
                offers = await uow.offers.list_with_content(after=after, limit=self._batch_size)
                if not offers:
                    break
                latest = await uow.extractions.latest_many([o.id for o in offers])
                for offer in offers:
                    current = latest.get(offer.id)
                    if category is not None and (current is None or current.category != category):
                        continue
                    if offer.content_hash is None:
                        continue
                    if not force and not needs_extraction(offer, current, catalog):
                        continue
                    considered += 1
                    payload = ExtractOfferPayload(
                        offer.id,
                        offer.content_hash,
                        catalog.fingerprint,
                        force=force,
                        request_tag=request_tag,
                    )
                    if await uow.jobs.enqueue(new_job(self._ids, payload, run_id=None, now=now)):
                        enqueued += 1
                    else:
                        already += 1
                await uow.commit()
            after = offers[-1].id
        return RequeueExtractionsResult(considered, enqueued, already)

"""ForceReextract: re-extract offers that are up to date, or retry parked ones (ADR 0010).

Replaces ``RequeueExtractions``: there is nothing to queue any more (the backlog is a
query), so this only marks extraction state:

* ``force`` (default): the selected offers re-enter the backlog even though their latest
  extraction is current (better model, prompt experiment). With ``profile`` the forced work
  is pinned to that profile: the extractor processes it with that profile only.
* ``parked_only``: a manual retry of offers parked after repeated failures; their failure
  counters are reset (they are out of date anyway, so no force is needed).

Selection: ``category`` (of the latest extraction) and provenance filters such as
``model=openai/gpt-4o-mini``, ``profile!=local`` or ``model~nano`` (AND-ed).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.extraction_backends import ExtractionProfiles
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import ExtractionState, OfferExtraction
from scrappy.domain.offer import OfferId

PROVENANCE_FIELDS = ("model", "profile", "provider", "prompt_version", "category")
PROVENANCE_OPS = ("=", "!=", "~")


@dataclass(frozen=True, slots=True)
class ProvenanceFilter:
    field: str
    op: str
    value: str

    def __post_init__(self) -> None:
        if self.field not in PROVENANCE_FIELDS:
            allowed = ", ".join(PROVENANCE_FIELDS)
            raise InvalidRequestError(f"unknown field {self.field!r}; expected one of {allowed}")
        if self.op not in PROVENANCE_OPS:
            raise InvalidRequestError(f"unknown operator {self.op!r}; use =, != or ~")

    def matches(self, extraction: OfferExtraction) -> bool:
        provenance = extraction.provenance
        actual: str | None
        match self.field:
            case "model":
                actual = provenance.model
            case "profile":
                actual = provenance.profile
            case "provider":
                actual = provenance.provider
            case "prompt_version":
                actual = provenance.prompt_version
            case _:
                actual = str(extraction.category)
        if actual is None:
            return self.op == "!="
        left, right = actual.casefold(), self.value.casefold()
        if self.op == "~":
            return right in left
        return (left == right) == (self.op == "=")


@dataclass(frozen=True, slots=True)
class ForceReextractResult:
    considered: int
    marked: int


class ForceReextract:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        profiles: ExtractionProfiles,
        clock: Clock,
        page_size: int = 500,
    ) -> None:
        self._uow = uow
        self._profiles = profiles
        self._clock = clock
        self._page_size = page_size

    async def __call__(
        self,
        *,
        category: CategoryName | None = None,
        where: Sequence[ProvenanceFilter] = (),
        profile: str | None = None,
        parked_only: bool = False,
    ) -> ForceReextractResult:
        if profile is not None and profile not in self._profiles.names():
            known = ", ".join(self._profiles.names())
            raise InvalidRequestError(f"unknown profile {profile} (known: {known})")
        now = self._clock.now()
        considered = marked = 0
        after: OfferId | None = None
        while True:
            async with self._uow() as uow:
                offers = await uow.offers.list_with_content(after=after, limit=self._page_size)
                if not offers:
                    break
                ids = [o.id for o in offers]
                latest = await uow.extractions.latest_many(ids)
                states = await uow.extraction_states.get_many(ids)
                for offer in offers:
                    current = latest.get(offer.id)
                    if (category is not None or where) and current is None:
                        continue
                    if (
                        category is not None
                        and current is not None
                        and current.category != category
                    ):
                        continue
                    if current is not None and not all(f.matches(current) for f in where):
                        continue
                    state = states.get(offer.id)
                    if parked_only and (state is None or not state.parked):
                        continue
                    considered += 1
                    state = state or ExtractionState.new(offer.id, now)
                    state.reset(now, force=not parked_only, profile=profile)
                    await uow.extraction_states.save(state)
                    marked += 1
                await uow.commit()
            after = offers[-1].id
        return ForceReextractResult(considered, marked)

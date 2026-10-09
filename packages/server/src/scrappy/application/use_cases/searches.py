"""Saved-search use cases: AddSavedSearch, SetRelevanceOverride."""

from __future__ import annotations

from dataclasses import dataclass

from scrappy.application.errors import ConflictError, InvalidRequestError, NotFoundError
from scrappy.application.ports.listing_source import ListingSources
from scrappy.application.ports.system import CategoryProvider, Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.category import OTHER_CATEGORY, CategoryName
from scrappy.domain.offer import OfferId
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import SourceId


@dataclass(frozen=True, slots=True)
class AddSavedSearchResult:
    search: SavedSearch
    created: bool
    """False if an identical search already existed (idempotent retry)."""


class AddSavedSearch:
    """Create a named search (R10). The source recipe must accept the URL
    (``validate_search_url``). Idempotent for an identical definition; a different
    definition under an existing name is a :class:`ConflictError`."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        categories: CategoryProvider,
        sources: ListingSources,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._categories = categories
        self._sources = sources
        self._clock = clock

    async def __call__(
        self, name: SearchName, source: SourceId, url: str, category: CategoryName
    ) -> AddSavedSearchResult:
        listing_source = self._sources.get(source)
        if listing_source is None:
            raise InvalidRequestError(f"unknown source {source}")
        listing_source.validate_search_url(url)  # raises InvalidRequestError (R10)
        catalog = await self._categories.catalog()
        if category == OTHER_CATEGORY or catalog.get(category) is None:
            raise InvalidRequestError(f"unknown category {category}")

        async with self._uow() as uow:
            existing = await uow.searches.get(name)
            if existing is not None:
                if existing.same_definition(source, url, category):
                    return AddSavedSearchResult(existing, created=False)
                raise ConflictError(f"a different search named {name} already exists")
            search = SavedSearch(name, source, url, category, created_at=self._clock.now())
            await uow.searches.save(search)
            await uow.commit()
        return AddSavedSearchResult(search, created=True)


class SetRelevanceOverride:
    """Manually mark an offer relevant / irrelevant for one search; ``None`` clears it."""

    def __init__(self, *, uow: UnitOfWorkFactory) -> None:
        self._uow = uow

    async def __call__(
        self, search: SearchName, offer_id: OfferId, value: bool | None
    ) -> SearchOffer:
        async with self._uow() as uow:
            link = await uow.search_offers.get(search, offer_id)
            if link is None:
                raise NotFoundError(f"offer {offer_id} was not found by search {search}")
            link.set_override(value)
            await uow.search_offers.save(link)
            await uow.commit()
        return link

"""Repository ports (write side). Reached through ``UnitOfWork``; see its transaction rules.

General contract for adapter authors
------------------------------------
* ``save`` is an upsert keyed by the entity identity; saving the same state twice is a
  no-op. Entities are plain mutable dataclasses: an adapter must not hand out objects that
  write through on mutation; changes are persisted only by ``save``.
* ``get`` returns ``None`` when absent; nothing raises for "not found".
* Returned objects are fresh copies; mutating them does not affect storage until ``save``.
* Datetimes are timezone-aware and must round-trip as such (store UTC).

Why ``SearchOffer`` has its own repository instead of living inside ``Offer`` or
``SavedSearch``: the link has its own lifecycle (seen dates, relevance, manual override),
is written by different stages than the offer, and is read per search with filters.
Folding it into either aggregate would load every link with every offer/search.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import Offer, OfferId, OfferSnapshot
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import RunId


class OfferRepository(Protocol):
    async def get(self, offer_id: OfferId) -> Offer | None: ...

    async def get_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, Offer]:
        """Only the offers that exist are in the result."""
        ...

    async def save(self, offer: Offer) -> None: ...

    async def add_snapshot(self, snapshot: OfferSnapshot) -> None:
        """Append to the offer's history (never updated or deduplicated)."""
        ...

    async def list_snapshots(self, offer_id: OfferId) -> list[OfferSnapshot]:
        """Oldest first."""
        ...

    async def list_with_content(self, *, after: OfferId | None, limit: int) -> list[Offer]:
        """Keyset page over offers that have a ``content_hash`` (extractable), ordered by
        ``(source, external_id)`` as strings; ``after`` excludes itself."""
        ...


class SavedSearchRepository(Protocol):
    async def get(self, name: SearchName) -> SavedSearch | None: ...

    async def save(self, search: SavedSearch) -> None: ...

    async def list_all(self) -> list[SavedSearch]:
        """Ordered by name."""
        ...


class SearchOfferRepository(Protocol):
    async def get(self, search: SearchName, offer_id: OfferId) -> SearchOffer | None: ...

    async def get_many(
        self, search: SearchName, offer_ids: Collection[OfferId]
    ) -> dict[OfferId, SearchOffer]: ...

    async def save(self, link: SearchOffer) -> None:
        """Upsert keyed by ``(search, offer_id)``."""
        ...

    async def list_for_offer(self, offer_id: OfferId) -> list[SearchOffer]:
        """All searches that found the offer, ordered by search name."""
        ...


class ExtractionRepository(Protocol):
    async def add(self, extraction: OfferExtraction) -> None:
        """Append; history is kept. The latest one (by ``extracted_at``, then insertion
        order) is the current one."""
        ...

    async def latest(self, offer_id: OfferId) -> OfferExtraction | None: ...

    async def latest_many(
        self, offer_ids: Collection[OfferId]
    ) -> dict[OfferId, OfferExtraction]: ...


class ScrapeRunRepository(Protocol):
    async def get(self, run_id: RunId) -> ScrapeRun | None: ...

    async def save(self, run: ScrapeRun) -> None: ...

    async def find_running(self, search: SearchName) -> ScrapeRun | None:
        """The search's RUNNING run, if any (at most one by construction)."""
        ...

    async def list_for_search(self, search: SearchName, *, limit: int) -> list[ScrapeRun]:
        """Newest ``started_at`` first."""
        ...

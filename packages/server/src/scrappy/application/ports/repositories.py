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
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from scrappy.application.extraction.batch import ExtractionBatch
from scrappy.application.extraction.profile_status import ProfileStatus
from scrappy.domain.category import CategoryCatalog
from scrappy.domain.extraction import ExtractionState, OfferExtraction
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

    async def list_running(self) -> list[ScrapeRun]:
        """Every RUNNING run, oldest ``started_at`` first."""
        ...


# ---------------------------------------------------------------------------- extraction


@dataclass(frozen=True, slots=True)
class BacklogQuery:
    """Which offers are in the extraction backlog (ADR 0010 section 2).

    An offer qualifies when :func:`scrappy.domain.extraction.extraction_due` is true for it
    (with its latest extraction, its state, ``catalog``, ``prompt_version`` and ``now``),
    and it passes the scope and routing filters below.
    """

    catalog: CategoryCatalog
    prompt_version: str
    now: datetime
    search: SearchName | None = None
    """Only offers linked to this search."""
    profile: str | None = None
    """Routing of forced work pinned to a profile (``extract force --profile``). With a
    profile, offers pinned to another profile are excluded. ``None``: no routing filter."""
    pinned_only: bool = False
    """Only offers pinned to ``profile``."""
    gated: bool = False
    """Tiering (ADR 0012): only forced offers and offers escalated by the rule pass for their
    current content (``extraction_due(..., gated=True)``)."""


class ExtractionStateRepository(Protocol):
    """Per-offer extraction state + the backlog query (ADR 0010 section 3).

    Backlog order (``backlog`` and ``claim``): offers' ``last_seen_at`` newest first, then
    ``(source, external_id)`` ascending as strings. The rule is applied exactly as the
    domain's ``extraction_due`` (a SQL adapter may pre-filter coarsely, then apply it).
    """

    async def get(self, offer_id: OfferId) -> ExtractionState | None: ...

    async def get_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, ExtractionState]: ...

    async def save(self, state: ExtractionState) -> None:
        """Upsert keyed by ``offer_id``."""
        ...

    async def backlog(self, query: BacklogQuery, *, limit: int | None = None) -> list[OfferId]: ...

    async def count_backlog(self, query: BacklogQuery) -> int: ...

    async def claim(
        self, query: BacklogQuery, *, owner: str, lease_until: datetime, limit: int
    ) -> list[OfferId]:
        """Lease up to ``limit`` backlog offers to ``owner`` until ``lease_until`` (creating
        state rows as needed); return them in backlog order. Atomic per offer: an offer whose
        lease is still valid (another owner committed it) is never handed out twice
        (SQL: a conditional ``UPDATE ... WHERE lease_until IS NULL OR lease_until <= now`` /
        ``INSERT ... ON CONFLICT DO NOTHING``, checking the row count)."""
        ...

    async def release_owner(self, owner: str, *, now: datetime) -> int:
        """Clear every lease held by ``owner`` (no penalty). Returns the count."""
        ...

    async def list_parked(self) -> list[ExtractionState]:
        """States with ``parked`` set, newest ``updated_at`` first (callers check whether the
        parked target is still the offer's current one)."""
        ...

    async def rules_backlog(self, version: str, *, limit: int | None = None) -> list[OfferId]:
        """Offers with content whose rule pass is missing or not ``rules_done(content_hash,
        version)`` (ADR 0012 tier 0). Same order as ``backlog``."""
        ...


class ExtractionBatchRepository(Protocol):
    async def get(self, batch_id: str) -> ExtractionBatch | None: ...

    async def save(self, batch: ExtractionBatch) -> None:
        """Upsert keyed by ``id``; the item list is replaced by the batch's items."""
        ...

    async def list_open(self, profile: str | None = None) -> list[ExtractionBatch]:
        """QUEUED / SUBMITTING / SUBMITTED batches, oldest first (creation order)."""
        ...

    async def list_recent(self, *, limit: int) -> list[ExtractionBatch]:
        """Any status, newest first (creation order)."""
        ...


class ProfileStatusRepository(Protocol):
    async def get(self, profile: str) -> ProfileStatus | None: ...

    async def save(self, status: ProfileStatus) -> None: ...

    async def list_all(self) -> list[ProfileStatus]:
        """Ordered by profile name."""
        ...

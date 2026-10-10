"""SQL repositories of the reconciling extractor (ADR 0010): extraction state, batches,
profile status. Reference behaviour: ``tests/unit/fakes/store.py``.

Backlog query
-------------
SQL pre-filters candidates coarsely (content present, lease free, and either forced or the
latest extraction is missing / for other content / for another prompt version / for another
or unknown catalog fingerprint). Python then applies the domain rule
``extraction_due`` (backoff, parking, the legacy schema-version rule) and the profile
routing, exactly like the in-memory fake. Order: ``offers.last_seen_at`` newest first, then
``(source, external_id)``.

Claim
-----
Per offer, a conditional ``UPDATE extraction_state SET lease_* WHERE <key> AND (lease_until IS
NULL OR lease_until <= now)``; if no state row exists yet, ``INSERT ... ON CONFLICT DO
NOTHING``. Only offers whose statement affected a row are returned. On SQLite the whole unit
of work is one ``BEGIN IMMEDIATE`` transaction (single writer); on PostgreSQL the row-level
re-check of the UPDATE (READ COMMITTED re-evaluates the WHERE after a lock wait) and the
unique key keep two extractors from leasing the same offer.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, and_, delete, or_, select, true, tuple_, update
from sqlalchemy.ext.asyncio import AsyncConnection

from scrappy.application.extraction.batch import OPEN_BATCH_STATUSES, ExtractionBatch
from scrappy.application.extraction.profile_status import ProfileStatus
from scrappy.application.ports.repositories import BacklogQuery
from scrappy.domain.extraction import ExtractionState, extraction_due
from scrappy.domain.offer import OfferId
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence._sql import chunks, insert_ignore, upsert
from scrappy.infrastructure.persistence.repositories import (
    SqlExtractionRepository,
    latest_extraction_cte,
)
from scrappy.infrastructure.persistence.tables import (
    extraction_batch_items,
    extraction_batches,
    extraction_profile_status,
    extraction_state,
    offers,
    search_offers,
)

_KEYS = ("source", "external_id")


def _key(offer_id: OfferId) -> tuple[str, str]:
    return (offer_id.source.value, offer_id.external_id)


def _routed(state: ExtractionState | None, query: BacklogQuery) -> bool:
    pinned = state.requested_profile if state is not None and state.forced else None
    if query.pinned_only:
        return pinned is not None and pinned == query.profile
    return query.profile is None or pinned is None or pinned == query.profile


class SqlExtractionStateRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, offer_id: OfferId) -> ExtractionState | None:
        return (await self.get_many([offer_id])).get(offer_id)

    async def get_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, ExtractionState]:
        result: dict[OfferId, ExtractionState] = {}
        keys = sorted({_key(i) for i in offer_ids})
        for part in chunks(keys):
            stmt = select(extraction_state).where(
                tuple_(extraction_state.c.source, extraction_state.c.external_id).in_(part)
            )
            for row in (await self._conn.execute(stmt)).mappings():
                state = m.state_from(row, extraction_state.c)
                result[state.offer_id] = state
        return result

    async def save(self, state: ExtractionState) -> None:
        await upsert(self._conn, extraction_state, m.state_values(state), list(_KEYS))

    async def backlog(self, query: BacklogQuery, *, limit: int | None = None) -> list[OfferId]:
        latest = latest_extraction_cte()
        s = extraction_state.c
        joined: Any = offers.outerjoin(
            latest,
            and_(latest.c.source == offers.c.source, latest.c.external_id == offers.c.external_id),
        ).outerjoin(
            extraction_state,
            and_(s.source == offers.c.source, s.external_id == offers.c.external_id),
        )
        stmt = select(offers).select_from(joined)
        if query.search is not None:
            linked = select(search_offers.c.source, search_offers.c.external_id).where(
                search_offers.c.search == query.search.value
            )
            stmt = stmt.where(tuple_(offers.c.source, offers.c.external_id).in_(linked))
        if query.gated:
            stmt = stmt.where(
                or_(
                    s.forced == true(),
                    and_(s.escalation.is_not(None), s.rules_hash == offers.c.content_hash),
                )
            )
        stmt = stmt.where(
            offers.c.content_hash.is_not(None),
            or_(s.lease_until.is_(None), s.lease_until <= query.now),
            or_(
                s.forced == true(),
                latest.c.seq.is_(None),
                latest.c.content_hash != offers.c.content_hash,
                latest.c.prompt_version != query.prompt_version,
                latest.c.catalog_fingerprint.is_(None),
                latest.c.catalog_fingerprint != query.catalog.fingerprint,
            ),
        ).order_by(offers.c.last_seen_at.desc(), offers.c.source, offers.c.external_id)
        candidates = [
            m.offer_from(row, offers.c) for row in (await self._conn.execute(stmt)).mappings()
        ]
        if not candidates:
            return []
        ids = [o.id for o in candidates]
        extractions = await SqlExtractionRepository(self._conn).latest_many(ids)
        states = await self.get_many(ids)
        result: list[OfferId] = []
        for offer in candidates:
            state = states.get(offer.id)
            if not _routed(state, query):
                continue
            if extraction_due(
                offer,
                extractions.get(offer.id),
                state,
                query.catalog,
                query.prompt_version,
                query.now,
                gated=query.gated,
            ):
                result.append(offer.id)
                if limit is not None and len(result) >= limit:
                    break
        return result

    async def count_backlog(self, query: BacklogQuery) -> int:
        return len(await self.backlog(query))

    async def claim(
        self, query: BacklogQuery, *, owner: str, lease_until: datetime, limit: int
    ) -> list[OfferId]:
        if limit < 1:
            return []
        claimed: list[OfferId] = []
        for offer_id in await self.backlog(query, limit=limit):
            source, external_id = _key(offer_id)
            s = extraction_state.c
            result = await self._conn.execute(
                update(extraction_state)
                .where(
                    s.source == source,
                    s.external_id == external_id,
                    or_(s.lease_until.is_(None), s.lease_until <= query.now),
                )
                .values(lease_owner=owner, lease_until=lease_until, updated_at=query.now)
            )
            if cast("CursorResult[Any]", result).rowcount:
                claimed.append(offer_id)
                continue
            state = ExtractionState.new(offer_id, query.now)
            state.lease(owner, lease_until, query.now)
            if await insert_ignore(self._conn, extraction_state, m.state_values(state), _KEYS):
                claimed.append(offer_id)
        return claimed

    async def release_owner(self, owner: str, *, now: datetime) -> int:
        result = await self._conn.execute(
            update(extraction_state)
            .where(extraction_state.c.lease_owner == owner)
            .values(lease_owner=None, lease_until=None, updated_at=now)
        )
        return cast("CursorResult[Any]", result).rowcount

    async def rules_backlog(self, version: str, *, limit: int | None = None) -> list[OfferId]:
        s = extraction_state.c
        joined: Any = offers.outerjoin(
            extraction_state,
            and_(s.source == offers.c.source, s.external_id == offers.c.external_id),
        )
        stmt = (
            select(offers.c.source, offers.c.external_id)
            .select_from(joined)
            .where(
                offers.c.content_hash.is_not(None),
                or_(
                    s.rules_hash.is_(None),
                    s.rules_hash != offers.c.content_hash,
                    s.rules_version.is_(None),
                    s.rules_version != version,
                ),
            )
            .order_by(offers.c.last_seen_at.desc(), offers.c.source, offers.c.external_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.offer_id_of(row, offers.c) for row in rows]

    async def list_parked(self) -> list[ExtractionState]:
        stmt = (
            select(extraction_state)
            .where(extraction_state.c.parked == true())
            .order_by(
                extraction_state.c.updated_at.desc(),
                extraction_state.c.source,
                extraction_state.c.external_id,
            )
        )
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.state_from(row, extraction_state.c) for row in rows]


class SqlExtractionBatchRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def _load(self, rows: Sequence[m.Row]) -> list[ExtractionBatch]:
        if not rows:
            return []
        ids = [row[extraction_batches.c.id] for row in rows]
        items: dict[str, list[m.Row]] = {batch_id: [] for batch_id in ids}
        for part in chunks(ids):
            stmt = (
                select(extraction_batch_items)
                .where(extraction_batch_items.c.batch_id.in_(part))
                .order_by(extraction_batch_items.c.batch_id, extraction_batch_items.c.position)
            )
            for item in (await self._conn.execute(stmt)).mappings():
                items[item[extraction_batch_items.c.batch_id]].append(item)
        return [
            m.batch_from(
                row,
                extraction_batches.c,
                items[row[extraction_batches.c.id]],
                extraction_batch_items.c,
            )
            for row in rows
        ]

    async def get(self, batch_id: str) -> ExtractionBatch | None:
        stmt = select(extraction_batches).where(extraction_batches.c.id == batch_id)
        rows = list((await self._conn.execute(stmt)).mappings())
        loaded = await self._load(rows)
        return loaded[0] if loaded else None

    async def save(self, batch: ExtractionBatch) -> None:
        await upsert(self._conn, extraction_batches, m.batch_values(batch), ["id"])
        await self._conn.execute(
            delete(extraction_batch_items).where(extraction_batch_items.c.batch_id == batch.id)
        )
        values = m.batch_item_values(batch)
        if values:
            await self._conn.execute(extraction_batch_items.insert(), values)

    async def list_open(self, profile: str | None = None) -> list[ExtractionBatch]:
        stmt = select(extraction_batches).where(
            extraction_batches.c.status.in_(sorted(s.value for s in OPEN_BATCH_STATUSES))
        )
        if profile is not None:
            stmt = stmt.where(extraction_batches.c.profile == profile)
        stmt = stmt.order_by(extraction_batches.c.seq)
        return await self._load(list((await self._conn.execute(stmt)).mappings()))

    async def list_recent(self, *, limit: int) -> list[ExtractionBatch]:
        stmt = select(extraction_batches).order_by(extraction_batches.c.seq.desc()).limit(limit)
        return await self._load(list((await self._conn.execute(stmt)).mappings()))


class SqlProfileStatusRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, profile: str) -> ProfileStatus | None:
        stmt = select(extraction_profile_status).where(
            extraction_profile_status.c.profile == profile
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return None if row is None else m.profile_status_from(row, extraction_profile_status.c)

    async def save(self, status: ProfileStatus) -> None:
        await upsert(
            self._conn, extraction_profile_status, m.profile_status_values(status), ["profile"]
        )

    async def list_all(self) -> list[ProfileStatus]:
        stmt = select(extraction_profile_status).order_by(extraction_profile_status.c.profile)
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.profile_status_from(row, extraction_profile_status.c) for row in rows]


__all__ = [
    "SqlExtractionBatchRepository",
    "SqlExtractionStateRepository",
    "SqlProfileStatusRepository",
]

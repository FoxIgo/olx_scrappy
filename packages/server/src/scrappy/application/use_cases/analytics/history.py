"""``q history`` and ``q health``."""

from __future__ import annotations

from datetime import datetime

from scrappy.application.errors import InvalidRequestError, NotFoundError
from scrappy.application.ports.analytics import AnalyticsQueries, OfferRow, OfferScope
from scrappy.application.ports.system import CategoryProvider
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics.common import (
    Answer,
    Json,
    QueryScope,
    ScopeResolver,
    offer_price_view,
    seen_at,
)
from scrappy.application.use_cases.analytics.offers import change_value
from scrappy.application.use_cases.extraction.status import (
    ExtractionStatus,
    ExtractionStatusReport,
)
from scrappy.domain.category import Category
from scrappy.domain.offer import OfferId, OfferStatus, TrackedField
from scrappy.domain.run import Phase, RunStatus, ScrapeRun
from scrappy.domain.search import SearchName
from scrappy.domain.shared import InvalidValueError


class History:
    def __init__(
        self, *, uow: UnitOfWorkFactory, queries: AnalyticsQueries, resolver: ScopeResolver
    ):
        self._uow = uow
        self._queries = queries
        self._resolver = resolver

    async def __call__(
        self,
        scope: QueryScope,
        *,
        offer: str | None = None,
        since: datetime | None = None,
        field: str | None = None,
        limit: int = 100,
    ) -> Answer:
        tracked: TrackedField | None = None
        if field is not None:
            try:
                tracked = TrackedField(field)
            except ValueError:
                allowed = ", ".join(f.value for f in TrackedField)
                raise InvalidRequestError(f"unknown field {field!r}; expected: {allowed}") from None
        notes: list[str] = []
        titles: dict[str, str | None] = {}
        allowed_ids: set[OfferId] | None = None
        rows: list[OfferRow] = []
        if offer is not None:
            try:
                offer_id = OfferId.parse(offer)
            except InvalidValueError as error:
                raise InvalidRequestError(str(error)) from error
            async with self._uow() as uow:
                found = await uow.offers.get(offer_id)
            if found is None:
                raise NotFoundError(f"offer {offer_id} not found")
            titles[str(offer_id)] = found.title
            snapshots = await self._queries.snapshots(offer_ids=[offer_id], since=since)
        else:
            scoped = await self._resolver.rows(scope)
            rows = scoped.rows
            notes += scoped.notes
            allowed_ids = {r.offer_id for r in rows}
            titles = {str(r.offer_id): r.title for r in rows}
            snapshots = await self._queries.snapshots(since=since)

        changes: list[Json] = []
        for snapshot in snapshots:
            if allowed_ids is not None and snapshot.offer_id not in allowed_ids:
                continue
            for change in snapshot.changes:
                if tracked is not None and change.field is not tracked:
                    continue
                changes.append(
                    {
                        "offer": str(snapshot.offer_id),
                        "title": titles.get(str(snapshot.offer_id)),
                        "field": change.field.value,
                        "old": change_value(change.field, change.old),
                        "new": change_value(change.field, change.new),
                        "at": snapshot.observed_at,
                        "run_id": None if snapshot.run_id is None else str(snapshot.run_id),
                    }
                )
        truncated = len(changes) > limit
        if truncated:
            notes.append(f"showing the newest {limit} of {len(changes)} changes")

        new_offers: list[Json] = []
        if since is not None and offer is None:
            fresh = [r for r in rows if _first_seen(r, scope.search) >= since]
            fresh.sort(key=lambda r: (-seen_at(r, scope.search).timestamp(), str(r.offer_id)))
            new_offers = [
                {
                    "id": str(r.offer_id),
                    "title": r.title,
                    "price": offer_price_view(r),
                    "url": r.url,
                    "first_seen_at": r.first_seen_at,
                }
                for r in fresh[:limit]
            ]
            if len(fresh) > limit:
                truncated = True
                notes.append(f"showing {limit} of {len(fresh)} new offers")
        elif offer is None:
            notes.append("pass --since DATE to also list offers first seen after it")
        shown = changes[:limit]
        data: Json = {"changes": shown, "new_offers": new_offers}
        return Answer(data, len(shown), truncated, notes)


class Health:
    def __init__(
        self,
        *,
        queries: AnalyticsQueries,
        categories: CategoryProvider,
        uow: UnitOfWorkFactory,
        extraction: ExtractionStatus | None = None,
    ) -> None:
        self._queries = queries
        self._categories = categories
        self._uow = uow
        self._extraction = extraction

    async def __call__(self, *, search: SearchName | None = None, runs: int = 5) -> Answer:
        if runs < 1:
            raise InvalidRequestError("runs must be >= 1")
        catalog = await self._categories.catalog()
        async with self._uow() as uow:
            searches = await uow.searches.list_all()
        if search is not None:
            searches = [s for s in searches if s.name == search]
            if not searches:
                raise NotFoundError(f"search {search} not found")
        notes: list[str] = []

        recent = await self._queries.recent_runs(search, runs)
        run_views = [_run_view(r) for r in recent]
        for run in recent[:1]:
            if run.status in (RunStatus.FAILED, RunStatus.DEGRADED, RunStatus.PARTIAL):
                notes.append(f"latest run {run.id} of {run.search} is {run.status.value}")
        if not recent:
            notes.append("no runs yet")

        coverage = await self._queries.extraction_coverage(search)
        unextracted = coverage.offers - coverage.extracted
        if unextracted:
            notes.append(f"{unextracted} offer(s) have no extraction yet")
        extraction: Json = {
            "offers": coverage.offers,
            "extracted": coverage.extracted,
            "without_extraction": unextracted,
        }
        if self._extraction is not None:
            report = await self._extraction(search=search)
            extraction.update(extraction_view(report, scoped=search is not None))
            notes += extraction_notes(report, scoped=search is not None)

        category_names = {s.category for s in searches}
        fills: list[Json] = []
        for category in catalog:
            if search is not None and category.name not in category_names:
                continue
            fills += await self._fill(category, search)

        stale: list[Json] = []
        for saved in searches:
            latest = await self._queries.recent_runs(saved.name, 1)
            if not latest:
                continue
            started = latest[0].started_at
            rows = await self._queries.offer_rows(
                OfferScope(search=saved.name, statuses=frozenset({OfferStatus.ACTIVE}))
            )
            count = sum(1 for r in rows if seen_at(r, saved.name) < started)
            stale.append(
                {"search": str(saved.name), "last_run_started_at": started, "stale_offers": count}
            )
            if count:
                notes.append(
                    f"{count} active offer(s) of {saved.name} were not seen in its latest run"
                )
        data: Json = {
            "runs": run_views,
            "extraction": extraction,
            "attribute_null_rates": fills,
            "stale": stale,
        }
        return Answer(data, len(run_views), notes=notes)

    async def _fill(self, category: Category, search: SearchName | None) -> list[Json]:
        names = [spec.name for spec in category.attributes]
        if not names:
            return []
        result: list[Json] = []
        for fill in await self._queries.attribute_fill(category.name, names, search):
            null = fill.extracted - fill.filled
            result.append(
                {
                    "category": str(fill.category),
                    "attribute": fill.attribute,
                    "extracted": fill.extracted,
                    "null": null,
                    "null_rate": None if fill.extracted == 0 else round(null / fill.extracted, 3),
                }
            )
        return result


MAX_PARKED_SHOWN = 10


def _backlog(report: ExtractionStatusReport, scoped: bool) -> int:
    if scoped and report.search_backlog is not None:
        return report.search_backlog
    return report.backlog


def extraction_view(report: ExtractionStatusReport, *, scoped: bool) -> Json:
    """The extractor's state for ``q health`` (ADR 0010 section 6)."""
    return {
        "backlog": _backlog(report, scoped),
        "open_batches": [
            {
                "id": b.id,
                "profile": b.profile,
                "status": b.status.value,
                "items": len(b.items),
                "created_at": b.created_at,
                "age_minutes": round((report.at - b.created_at).total_seconds() / 60, 1),
            }
            for b in report.open_batches
        ],
        "parked": len(report.parked),
        "parked_offers": [
            {
                "offer": str(s.offer_id),
                "attempts": s.attempts,
                "last_error": s.last_error,
                "since": s.updated_at,
            }
            for s in report.parked[:MAX_PARKED_SHOWN]
        ],
        "profiles": [
            {
                "name": v.profile.name,
                "provider": v.profile.provider,
                "model": v.profile.model,
                "mode": v.profile.mode.value,
                "default": v.is_default,
                "in_pool": v.in_pool,
                "blocked": v.blocked,
                "blocked_until": v.status.blocked_until,
                "reason": v.status.reason,
                "requests_today": v.status.requests_on(report.at, v.profile.capabilities.quota_tz),
                "daily_limit": v.profile.capabilities.daily_limit,
            }
            for v in report.profiles
        ],
    }


def extraction_notes(report: ExtractionStatusReport, *, scoped: bool) -> list[str]:
    notes: list[str] = []
    backlog = _backlog(report, scoped)
    if backlog:
        notes.append(
            f"{backlog} offer(s) wait for extraction; the worker's extractor loop "
            "(or `scrappy extract --inline`) processes them"
        )
    if report.parked:
        notes.append(
            f"{len(report.parked)} offer(s) parked after repeated extraction failures; "
            "`scrappy extract force --parked` retries them"
        )
    for view in report.profiles:
        if view.blocked:
            notes.append(f"extraction profile {view.profile.name} is blocked: {view.status.reason}")
    return notes


def _first_seen(row: OfferRow, search: SearchName | None) -> datetime:
    if search is not None:
        for link in row.links:
            if link.search == search:
                return link.first_seen_at
    return row.first_seen_at


def _run_view(run: ScrapeRun) -> Json:
    metrics = run.metrics
    return {
        "id": str(run.id),
        "search": str(run.search),
        "status": run.status.value,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "phases": {
            phase.value: {
                "accepted": metrics.phase(phase).accepted,
                "rejected": metrics.phase(phase).rejected,
            }
            for phase in Phase
        },
        "failed_jobs": metrics.failed_jobs,
        "coverage": {
            "pages": metrics.coverage.pages,
            "total_reported": metrics.coverage.total_reported,
            "truncated": metrics.coverage.truncated,
        },
        "llm_tokens": metrics.usage.total_tokens,
        "llm_cost_usd": metrics.usage.cost_usd,
        "warnings": list(run.warnings),
        "reasons": list(run.reasons),
        "errors": list(run.errors[:3]),
    }


__all__ = ["Health", "History", "extraction_notes", "extraction_view"]

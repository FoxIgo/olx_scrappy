"""Use cases of the agent query interface (``scrappy q``, ADR 0009). Read-only."""

from __future__ import annotations

from dataclasses import dataclass

from scrappy.application.ports.analytics import AnalyticsQueries
from scrappy.application.ports.system import CategoryProvider
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics.aggregates import Deals, Facets, Stats
from scrappy.application.use_cases.analytics.catalog_views import Overview, Schema
from scrappy.application.use_cases.analytics.common import Answer, QueryScope, ScopeResolver
from scrappy.application.use_cases.analytics.history import Health, History
from scrappy.application.use_cases.analytics.offers import (
    ExportOffers,
    ExportTable,
    OfferDetail,
    QueryOffers,
)
from scrappy.application.use_cases.analytics.sql import RunSql
from scrappy.application.use_cases.extraction.status import ExtractionStatus


@dataclass(frozen=True, slots=True)
class QueryUseCases:
    """Everything ``scrappy q`` needs, as one bundle."""

    overview: Overview
    schema: Schema
    offers: QueryOffers
    offer: OfferDetail
    export: ExportOffers
    facets: Facets
    stats: Stats
    deals: Deals
    history: History
    health: Health
    sql: RunSql


def build_query_use_cases(
    *,
    uow: UnitOfWorkFactory,
    queries: AnalyticsQueries,
    categories: CategoryProvider,
    extraction: ExtractionStatus | None = None,
) -> QueryUseCases:
    resolver = ScopeResolver(uow=uow, queries=queries, categories=categories)
    return QueryUseCases(
        overview=Overview(queries=queries, categories=categories, extraction=extraction),
        schema=Schema(queries=queries, categories=categories),
        offers=QueryOffers(resolver),
        offer=OfferDetail(uow=uow),
        export=ExportOffers(resolver),
        facets=Facets(resolver),
        stats=Stats(resolver),
        deals=Deals(resolver),
        history=History(uow=uow, queries=queries, resolver=resolver),
        health=Health(queries=queries, categories=categories, uow=uow, extraction=extraction),
        sql=RunSql(queries=queries),
    )


__all__ = ["Answer", "ExportTable", "QueryScope", "QueryUseCases", "build_query_use_cases"]

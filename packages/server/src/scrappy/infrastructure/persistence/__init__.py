"""Persistence adapters: SQLAlchemy Core (async) repositories, job queue, queries, migrations.

Typical wiring (``main.py``)::

    upgrade_to_head(url)                      # Alembic, sync, before the loop starts
    engine = create_engine(url)               # sqlite+aiosqlite:///... (WAL, FKs, busy timeout)
    uow = sql_unit_of_work_factory(engine)    # the UnitOfWorkFactory
    queries = SqlOfferQueries(engine)         # the OfferQueries port
    analytics = SqlAnalyticsQueries(engine)   # the AnalyticsQueries port (scrappy q)
"""

from scrappy.infrastructure.persistence.analytics import SqlAnalyticsQueries
from scrappy.infrastructure.persistence.engine import create_engine, sqlite_url
from scrappy.infrastructure.persistence.migrate import (
    upgrade_to_head,
    upgrade_to_head_async,
)
from scrappy.infrastructure.persistence.queries import SqlOfferQueries
from scrappy.infrastructure.persistence.unit_of_work import (
    SqlUnitOfWork,
    sql_unit_of_work_factory,
)

__all__ = [
    "SqlAnalyticsQueries",
    "SqlOfferQueries",
    "SqlUnitOfWork",
    "create_engine",
    "sql_unit_of_work_factory",
    "sqlite_url",
    "upgrade_to_head",
    "upgrade_to_head_async",
]

"""Alembic environment, driven programmatically (see ``migrate.py``; no alembic.ini).

Two ways in:

* ``config.attributes["connection"]`` holds a ready (sync-style) connection: used by
  ``upgrade_to_head_async`` which runs this inside ``AsyncConnection.run_sync``.
* otherwise ``sqlalchemy.url`` is a *sync* URL and an engine is created here.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, make_url
from sqlalchemy import create_engine as create_sync_engine

from scrappy.infrastructure.persistence.engine import configure_sqlite
from scrappy.infrastructure.persistence.tables import metadata

config = context.config


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url is not configured")
    engine = create_sync_engine(url)
    if make_url(url).get_backend_name() == "sqlite":
        configure_sqlite(engine)
    try:
        with engine.connect() as conn:
            _run(conn)
            conn.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline (--sql) migrations are not supported")
run_migrations_online()

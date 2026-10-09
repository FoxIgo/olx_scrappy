"""The application's own scenario tests, re-run unchanged against the SQL adapters.

``tests/unit/application`` exercises the use cases, job handlers, dispatcher, queue and the
reconciling extractor (extraction state, batches, profile status) against the in-memory
fakes. Here the very same test functions are collected again with the
fakes swapped for ``SqlStore`` (SQLite file, real migrations, real ``SqlUnitOfWork``,
``SqlJobQueue`` and ``SqlOfferQueries``): if they pass, the SQL adapters behave like the
reference implementation for everything the application relies on.

How: the unit test modules look ``App`` / ``InMemoryStore`` up in their own globals at call
time, so an autouse fixture patches those names; the test objects are re-exported below.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import ModuleType
from typing import cast

import pytest

from scrappy.application.use_cases.list_offers import ListOffers
from scrappy.infrastructure.persistence.queries import SqlOfferQueries
from tests.integration.persistence.sqlstore import SqlStore
from tests.unit.application import (
    test_extraction,
    test_failures,
    test_jobs,
    test_scenario,
    test_use_cases,
)
from tests.unit.application.harness import App
from tests.unit.fakes import InMemoryStore

_STORES: list[SqlStore] = []


def _new_store() -> SqlStore:
    store = SqlStore()
    _STORES.append(store)
    return store


@dataclass
class SqlApp(App):
    """The in-memory harness wired to a SQLite database."""

    store: InMemoryStore = field(default_factory=lambda: cast(InMemoryStore, _new_store()))

    def __post_init__(self) -> None:
        super().__post_init__()
        sql = cast(SqlStore, self.store)
        self.list_offers = ListOffers(
            uow=sql.uow, queries=SqlOfferQueries(sql.engine), categories=self.categories
        )


@pytest.fixture(autouse=True)
async def _sql_backed_unit_tests(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    for module in (test_scenario, test_failures, test_use_cases, test_extraction):
        monkeypatch.setattr(module, "App", SqlApp)
    for module in (test_jobs, test_use_cases):
        monkeypatch.setattr(module, "InMemoryStore", _new_store)
    yield
    while _STORES:
        await _STORES.pop().close()


def _export(module: ModuleType, *, only: tuple[str, ...] = ()) -> None:
    prefix = module.__name__.rsplit(".", 1)[-1]
    for name, obj in vars(module).items():
        if only and name not in only:
            continue
        if (name.startswith("test_") and callable(obj) and "fakes_implement" not in name) or (
            name.startswith("Test") and isinstance(obj, type) and obj.__module__ == module.__name__
        ):
            globals()[f"{name}__{prefix}"] = obj


_export(test_scenario)
_export(test_failures)
_export(test_use_cases)
_export(test_extraction)
_export(test_jobs, only=("TestInMemoryJobQueue",))

"""In-memory fakes of every application port.

They are also the reference behaviour for adapter authors (transactions, copies, job
dedup and claim order, query semantics). Keep them correct, not just convenient.
"""

from tests.unit.fakes.sources import InMemoryOfferQueries, ScriptedExtractor, ScriptedListingSource
from tests.unit.fakes.store import InMemoryStore, InMemoryUnitOfWork
from tests.unit.fakes.system import FakeClock, SequentialIds, StaticCategoryProvider

__all__ = [
    "FakeClock",
    "InMemoryOfferQueries",
    "InMemoryStore",
    "InMemoryUnitOfWork",
    "ScriptedExtractor",
    "ScriptedListingSource",
    "SequentialIds",
    "StaticCategoryProvider",
]

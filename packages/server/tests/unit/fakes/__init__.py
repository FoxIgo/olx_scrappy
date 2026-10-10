"""In-memory fakes of every application port.

They are also the reference behaviour for adapter authors (transactions, copies, job
dedup and claim order, query semantics). Keep them correct, not just convenient.
"""

from tests.unit.fakes.analytics import InMemoryAnalyticsQueries
from tests.unit.fakes.scoring import InMemoryScoringQueries, StaticScoringProvider
from tests.unit.fakes.sources import InMemoryOfferQueries, ScriptedExtractor, ScriptedListingSource
from tests.unit.fakes.store import InMemoryStore, InMemoryUnitOfWork
from tests.unit.fakes.system import FakeClock, SequentialIds, StaticCategoryProvider

__all__ = [
    "FakeClock",
    "InMemoryAnalyticsQueries",
    "InMemoryOfferQueries",
    "InMemoryScoringQueries",
    "InMemoryStore",
    "InMemoryUnitOfWork",
    "ScriptedExtractor",
    "ScriptedListingSource",
    "SequentialIds",
    "StaticCategoryProvider",
    "StaticScoringProvider",
]

"""Value objects and helpers shared by all domain modules."""

from scrappy.domain.shared.errors import DomainError, InvalidValueError
from scrappy.domain.shared.fetch import FetchOutcome
from scrappy.domain.shared.identifiers import RunId, SourceId, validate_slug
from scrappy.domain.shared.money import Money
from scrappy.domain.shared.time import require_aware, require_aware_or_none

__all__ = [
    "DomainError",
    "FetchOutcome",
    "InvalidValueError",
    "Money",
    "RunId",
    "SourceId",
    "require_aware",
    "require_aware_or_none",
    "validate_slug",
]

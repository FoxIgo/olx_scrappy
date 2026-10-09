"""LLM extraction results, provenance, the re-extraction rule, per-offer extraction state
and attribute predicates."""

from scrappy.domain.extraction.extraction import (
    ExtractionProvenance,
    OfferExtraction,
    TokenUsage,
    needs_extraction,
)
from scrappy.domain.extraction.predicate import AttributePredicate, Comparison
from scrappy.domain.extraction.state import (
    ExtractionRetryPolicy,
    ExtractionState,
    ExtractionTarget,
    extraction_due,
)

__all__ = [
    "AttributePredicate",
    "Comparison",
    "ExtractionProvenance",
    "ExtractionRetryPolicy",
    "ExtractionState",
    "ExtractionTarget",
    "OfferExtraction",
    "TokenUsage",
    "extraction_due",
    "needs_extraction",
]

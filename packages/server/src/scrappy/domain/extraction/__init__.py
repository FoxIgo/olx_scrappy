"""LLM extraction results, provenance, re-extraction rule and attribute predicates."""

from scrappy.domain.extraction.extraction import (
    ExtractionProvenance,
    OfferExtraction,
    TokenUsage,
    needs_extraction,
)
from scrappy.domain.extraction.predicate import AttributePredicate, Comparison

__all__ = [
    "AttributePredicate",
    "Comparison",
    "ExtractionProvenance",
    "OfferExtraction",
    "TokenUsage",
    "needs_extraction",
]

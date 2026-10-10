"""Scoring strategies: configurable interpretation of stored facts (ADR 0011)."""

from scrappy.domain.scoring.compute import FactValue, OfferScore, TermScore, score_offer
from scrappy.domain.scoring.facts import (
    COMPONENT_METRICS,
    SOURCE_ALIASES,
    ComponentFactRef,
    parse_component_fact,
)
from scrappy.domain.scoring.model import Strategy, Term, Transform, validate_against_category

__all__ = [
    "COMPONENT_METRICS",
    "SOURCE_ALIASES",
    "ComponentFactRef",
    "FactValue",
    "OfferScore",
    "Strategy",
    "Term",
    "TermScore",
    "Transform",
    "parse_component_fact",
    "score_offer",
    "validate_against_category",
]

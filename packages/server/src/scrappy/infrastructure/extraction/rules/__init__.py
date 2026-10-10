"""Rule-based extraction (ADR 0012 tier 0): site params + regex, no LLM."""

from scrappy.infrastructure.extraction.rules.extractor import (
    RULES_VERSION,
    LaptopRules,
    RuleBasedExtractor,
    Uncertain,
)

__all__ = ["RULES_VERSION", "LaptopRules", "RuleBasedExtractor", "Uncertain"]

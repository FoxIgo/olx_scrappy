"""``AttributeExtractor``: the LLM as a pure function (R11, R14, ADR 0007).

Contract for adapter authors
----------------------------
* Input is fully prepared by the application (``prepare_extraction_input``); the adapter
  only renders a prompt from it. No tools, no browsing, no follow-up requests.
* The description is **untrusted** text. Output is data only, validated against the schema
  of the chosen category (structured output + pydantic generated from
  :class:`~scrappy.domain.category.Category`). Unknown values must be ``null``.
* ``category`` must be one of ``input.categories`` or ``other``. ``attributes`` must
  contain only keys of that category's schema (``{}`` for ``other``).
* Invalid output: retry once inside the adapter, then return
  ``ExtractionRejection(retryable=False)``. Provider/network problems (timeouts, 429, 5xx):
  return ``ExtractionRejection(retryable=True)``. Do not raise for either.
* Always report token usage, also for rejections, so cost is complete (R14).
* The application validates the result again in the domain
  (``OfferExtraction.validated``); a mismatch there also counts as a rejection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from scrappy.domain.category import Category, CategoryName
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash, OfferId, Price


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    offer_id: OfferId
    content_hash: ContentHash
    title: str
    description: str
    """HTML stripped, whitespace normalized, truncated to the configured maximum."""
    description_truncated: bool
    params: tuple[tuple[str, str], ...]
    """Site parameters (key, value), sorted by key."""
    price: Price | None
    categories: tuple[Category, ...]
    """Candidate categories with their schemas; the answer may also be ``other``."""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    category: CategoryName
    attributes: Mapping[str, object]
    """Raw values as parsed from the model output (JSON types); validated by the domain."""
    model: str
    prompt_version: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionRejection:
    reason: str
    retryable: bool
    """True for provider/network trouble; False for invalid output after the retry."""
    model: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)


class AttributeExtractor(Protocol):
    async def extract(self, request: ExtractionInput) -> ExtractionResult | ExtractionRejection: ...

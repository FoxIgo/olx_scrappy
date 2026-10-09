"""LLM extraction results with provenance, and the re-extraction rule (R11, ADR 0007)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from scrappy.domain.category import (
    OTHER_CATEGORY,
    AttributeValue,
    CategoryCatalog,
    CategoryName,
)
from scrappy.domain.offer import ContentHash, Offer, OfferId
from scrappy.domain.shared import InvalidValueError, require_aware


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal | None = None
    """Estimated cost if the provider reports it (no cap, R14, but always recorded)."""

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0 or self.completion_tokens < 0:
            raise InvalidValueError("token counts must be >= 0")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        if self.cost_usd is None and other.cost_usd is None:
            cost = None
        else:
            cost = (self.cost_usd or Decimal(0)) + (other.cost_usd or Decimal(0))
        return TokenUsage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            cost,
        )


@dataclass(frozen=True, slots=True)
class ExtractionProvenance:
    """Where an extraction came from; makes "which offers to re-extract" answerable."""

    model: str
    prompt_version: str
    schema_version: int | None
    """Version of the classified category's schema; ``None`` for ``other``."""
    content_hash: ContentHash
    extracted_at: datetime
    catalog_fingerprint: str | None = None
    """``CategoryCatalog.fingerprint`` the input was built with. ``None`` for extractions
    stored before ADR 0010 (the per-category schema version rule applies to those)."""
    profile: str | None = None
    """Extraction profile (``config/extraction.yaml``) that produced it (ADR 0010 section 8)."""
    provider: str | None = None
    """Provider adapter of that profile (``openrouter``, ``openai_compatible``, ...)."""
    batch_id: str | None = None
    """Local ``extraction_batches`` id when it came from a provider batch."""
    cost_estimated: bool = False
    """True when ``usage.cost_usd`` is an allocation (batch cost split by token share)."""

    def __post_init__(self) -> None:
        require_aware(self.extracted_at, "extracted_at")


@dataclass(frozen=True, slots=True)
class OfferExtraction:
    """One validated LLM answer for an offer. The latest one is current; history is kept."""

    offer_id: OfferId
    category: CategoryName
    attributes: Mapping[str, AttributeValue | None]
    provenance: ExtractionProvenance
    usage: TokenUsage = field(default_factory=TokenUsage)
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", dict(self.attributes))  # defensive copy
        if self.category == OTHER_CATEGORY and self.attributes:
            raise InvalidValueError("'other' extractions carry no attributes")
        if (self.category == OTHER_CATEGORY) != (self.provenance.schema_version is None):
            raise InvalidValueError("schema_version is None exactly for 'other'")

    @classmethod
    def validated(
        cls,
        *,
        offer_id: OfferId,
        category: CategoryName,
        raw_attributes: Mapping[str, object],
        catalog: CategoryCatalog,
        model: str,
        prompt_version: str,
        content_hash: ContentHash,
        extracted_at: datetime,
        usage: TokenUsage | None = None,
        notes: str | None = None,
        catalog_fingerprint: str | None = None,
        profile: str | None = None,
        provider: str | None = None,
        batch_id: str | None = None,
        cost_estimated: bool = False,
    ) -> OfferExtraction:
        """Build an extraction after validating the category and attributes.

        Raises :class:`InvalidValueError` for an unknown category or attributes that do not
        match its schema; the caller treats that as a rejected LLM output (ADR 0007).
        """
        if category == OTHER_CATEGORY:
            attributes: dict[str, AttributeValue | None] = {}
            schema_version = None
        else:
            definition = catalog.get(category)
            if definition is None:
                raise InvalidValueError(f"LLM returned unknown category {category}")
            attributes = definition.validate_attributes(raw_attributes)
            schema_version = definition.version
        return cls(
            offer_id=offer_id,
            category=category,
            attributes=attributes,
            provenance=ExtractionProvenance(
                model=model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                content_hash=content_hash,
                extracted_at=extracted_at,
                catalog_fingerprint=catalog_fingerprint,
                profile=profile,
                provider=provider,
                batch_id=batch_id,
                cost_estimated=cost_estimated,
            ),
            usage=usage or TokenUsage(),
            notes=notes,
        )


def needs_extraction(
    offer: Offer,
    latest: OfferExtraction | None,
    catalog: CategoryCatalog,
    prompt_version: str | None = None,
) -> bool:
    """Is this offer's latest extraction missing or out of date? (ADR 0010 section 2)

    * Not before it has content (``content_hash`` needs a description).
    * Yes if never extracted, or the content changed since (R11 cost control).
    * Yes if the extraction was made with a different catalog (``catalog_fingerprint``) or,
      when ``prompt_version`` is given, a different prompt version.
    * Legacy extractions without a fingerprint (stored before ADR 0010) fall back to the
      old rule: re-extract when the classified category's schema version changed (a removed
      category counts as changed); ``other`` is not redone for schema changes.
    * The model is deliberately **not** part of the rule: switching or falling back to
      another profile must not re-extract everything. Use a forced re-extraction for that.
    """
    if offer.content_hash is None:
        return False
    if latest is None or latest.provenance.content_hash != offer.content_hash:
        return True
    provenance = latest.provenance
    if prompt_version is not None and provenance.prompt_version != prompt_version:
        return True
    if provenance.catalog_fingerprint is not None:
        return provenance.catalog_fingerprint != catalog.fingerprint
    if latest.category == OTHER_CATEGORY:
        return False
    current = catalog.get(latest.category)
    return current is None or current.version != provenance.schema_version

from decimal import Decimal
from typing import ClassVar

import pytest

from scrappy.domain.category import (
    OTHER_CATEGORY,
    AttributeSpec,
    AttributeType,
    AttributeValue,
    Category,
    CategoryCatalog,
    CategoryName,
)
from scrappy.domain.extraction import (
    AttributePredicate,
    Comparison,
    OfferExtraction,
    TokenUsage,
    needs_extraction,
)
from scrappy.domain.offer import Offer
from scrappy.domain.shared import InvalidValueError
from tests.unit.builders import LAPTOP, PHONE, at, catalog, details, laptop_category, listing


class TestAttributeSpec:
    @pytest.mark.parametrize(
        ("spec_type", "raw", "expected"),
        [
            (AttributeType.STRING, "  GTX 1650 ", "GTX 1650"),
            (AttributeType.INTEGER, 16, 16),
            (AttributeType.INTEGER, "16", 16),
            (AttributeType.INTEGER, 16.0, 16),
            (AttributeType.NUMBER, 15.6, Decimal("15.6")),
            (AttributeType.NUMBER, "15.6", Decimal("15.6")),
            (AttributeType.BOOLEAN, True, True),
            (AttributeType.BOOLEAN, "false", False),
        ],
    )
    def test_coerce(self, spec_type: AttributeType, raw: object, expected: object) -> None:
        assert AttributeSpec("a", spec_type).coerce(raw) == expected

    @pytest.mark.parametrize(
        ("spec_type", "raw"),
        [
            (AttributeType.STRING, ""),
            (AttributeType.INTEGER, 16.5),
            (AttributeType.INTEGER, True),
            (AttributeType.NUMBER, "abc"),
            (AttributeType.NUMBER, float("inf")),
            (AttributeType.BOOLEAN, 1),
        ],
    )
    def test_reject(self, spec_type: AttributeType, raw: object) -> None:
        with pytest.raises(InvalidValueError):
            AttributeSpec("a", spec_type).coerce(raw)

    def test_enum(self) -> None:
        spec = AttributeSpec("storage", AttributeType.ENUM, values=("ssd", "hdd"))
        assert spec.coerce("ssd") == "ssd"
        with pytest.raises(InvalidValueError):
            spec.coerce("nvme")
        with pytest.raises(InvalidValueError):
            AttributeSpec("storage", AttributeType.ENUM)


class TestCategory:
    def test_validate_fills_missing_with_none(self) -> None:
        result = laptop_category().validate_attributes({"ram_gb": "16"})
        assert result == {"gpu": None, "ram_gb": 16, "screen_in": None, "storage_type": None}

    def test_unknown_attribute_rejected(self) -> None:
        with pytest.raises(InvalidValueError):
            laptop_category().validate_attributes({"color": "red"})

    def test_other_is_reserved(self) -> None:
        with pytest.raises(InvalidValueError):
            Category(OTHER_CATEGORY, 1, ())

    def test_catalog(self) -> None:
        cat = catalog()
        assert cat.get(LAPTOP) is not None
        assert cat.is_known(OTHER_CATEGORY)
        assert not cat.is_known(CategoryName("tv"))
        assert [c.name for c in cat] == [LAPTOP, PHONE]


def enriched() -> Offer:
    offer = Offer.from_observation(listing("1"), at(0))
    offer.apply(details("1"), at(1))
    return offer


def extraction_for(
    offer: Offer, category: CategoryName = LAPTOP, version: int = 1
) -> OfferExtraction:
    assert offer.content_hash is not None
    return OfferExtraction.validated(
        offer_id=offer.id,
        category=category,
        raw_attributes={"ram_gb": 16} if category == LAPTOP else {},
        catalog=catalog(version),
        model="m",
        prompt_version="p1",
        content_hash=offer.content_hash,
        extracted_at=at(2),
    )


class TestOfferExtraction:
    def test_validated_records_schema_version(self) -> None:
        extraction = extraction_for(enriched(), version=3)
        assert extraction.provenance.schema_version == 3
        assert extraction.attributes["ram_gb"] == 16

    def test_other_has_no_schema_version_or_attributes(self) -> None:
        extraction = extraction_for(enriched(), OTHER_CATEGORY)
        assert extraction.provenance.schema_version is None
        assert dict(extraction.attributes) == {}

    def test_unknown_category_rejected(self) -> None:
        offer = enriched()
        assert offer.content_hash is not None
        with pytest.raises(InvalidValueError):
            OfferExtraction.validated(
                offer_id=offer.id,
                category=CategoryName("tv"),
                raw_attributes={},
                catalog=catalog(),
                model="m",
                prompt_version="p",
                content_hash=offer.content_hash,
                extracted_at=at(2),
            )


class TestNeedsExtraction:
    def test_no_content_yet(self) -> None:
        assert not needs_extraction(Offer.from_observation(listing("1"), at(0)), None, catalog())

    def test_never_extracted(self) -> None:
        assert needs_extraction(enriched(), None, catalog())

    def test_up_to_date(self) -> None:
        offer = enriched()
        assert not needs_extraction(offer, extraction_for(offer), catalog())

    def test_content_changed(self) -> None:
        offer = enriched()
        latest = extraction_for(offer)
        offer.apply(details("1", description="Different"), at(3))
        assert needs_extraction(offer, latest, catalog())

    def test_schema_version_changed(self) -> None:
        offer = enriched()
        assert needs_extraction(offer, extraction_for(offer, version=1), catalog(laptop_version=2))

    def test_category_removed_from_catalog(self) -> None:
        offer = enriched()
        assert needs_extraction(offer, extraction_for(offer), CategoryCatalog())

    def test_other_not_redone_for_schema_changes(self) -> None:
        offer = enriched()
        latest = extraction_for(offer, OTHER_CATEGORY)
        assert not needs_extraction(offer, latest, catalog(laptop_version=5))


class TestTokenUsage:
    def test_add(self) -> None:
        total = TokenUsage(10, 5) + TokenUsage(1, 1, Decimal("0.01"))
        assert total == TokenUsage(11, 6, Decimal("0.01"))
        assert total.total_tokens == 17
        assert (TokenUsage() + TokenUsage()).cost_usd is None


class TestAttributePredicate:
    attrs: ClassVar[dict[str, AttributeValue | None]] = {
        "gpu": "GeForce GTX 1650",
        "ram_gb": 16,
        "screen_in": Decimal("15.6"),
        "ok": True,
    }

    @pytest.mark.parametrize(
        ("predicate", "expected"),
        [
            (AttributePredicate("ram_gb", Comparison.GE, 16), True),
            (AttributePredicate("ram_gb", Comparison.GT, 16), False),
            (AttributePredicate("screen_in", Comparison.LT, Decimal("16")), True),
            (AttributePredicate("screen_in", Comparison.EQ, 15), False),
            (AttributePredicate("gpu", Comparison.CONTAINS, "gtx 1650"), True),
            (AttributePredicate("gpu", Comparison.EQ, "geforce gtx 1650"), True),
            (AttributePredicate("gpu", Comparison.NE, "RTX"), True),
            (AttributePredicate("gpu", Comparison.GT, "a"), False),
            (AttributePredicate("ram_gb", Comparison.EQ, "16"), False),
            (AttributePredicate("ok", Comparison.EQ, True), True),
            (AttributePredicate("ok", Comparison.EQ, 1), False),
            (AttributePredicate("missing", Comparison.NE, 1), False),
        ],
    )
    def test_matches(self, predicate: AttributePredicate, expected: bool) -> None:
        assert predicate.matches(self.attrs) is expected

    def test_null_never_matches(self) -> None:
        assert not AttributePredicate("gpu", Comparison.NE, "x").matches({"gpu": None})


class TestCatalogFingerprint:
    def test_stable_and_order_independent(self) -> None:
        a = catalog()
        b = CategoryCatalog(tuple(reversed(a.categories)))
        assert a.fingerprint == b.fingerprint
        assert len(a.fingerprint) == 12

    def test_changes_with_any_schema_version(self) -> None:
        assert catalog(laptop_version=1).fingerprint != catalog(laptop_version=2).fingerprint

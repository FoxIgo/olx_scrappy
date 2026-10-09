"""Test data builders shared by domain and application tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scrappy.domain.category import (
    AttributeSpec,
    AttributeType,
    Category,
    CategoryCatalog,
    CategoryName,
)
from scrappy.domain.offer import (
    ObservationLevel,
    OfferId,
    OfferObservation,
    OfferStatus,
    Params,
    Price,
)
from scrappy.domain.shared import SourceId

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LAPTOP = CategoryName("laptop")
PHONE = CategoryName("phone")
DEFAULT_PRICE = Price.fixed(1000)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def laptop_category(version: int = 1) -> Category:
    return Category(
        LAPTOP,
        version,
        (
            AttributeSpec("gpu", AttributeType.STRING, "GPU model"),
            AttributeSpec("ram_gb", AttributeType.INTEGER),
            AttributeSpec("screen_in", AttributeType.NUMBER),
            AttributeSpec("storage_type", AttributeType.ENUM, values=("ssd", "hdd", "emmc")),
        ),
    )


def catalog(laptop_version: int = 1) -> CategoryCatalog:
    phone = Category(PHONE, 1, (AttributeSpec("model", AttributeType.STRING),))
    return CategoryCatalog.of([laptop_category(laptop_version), phone])


def oid(external_id: str, source: str = "olx_pl") -> OfferId:
    return OfferId(SourceId(source), external_id)


def listing(
    external_id: str,
    *,
    source: str = "olx_pl",
    title: str | None = "Laptop GTX 1650",
    price: Price | None = DEFAULT_PRICE,
    refreshed_at: datetime | None = None,
    promoted: bool = False,
    url: str | None = "default",
) -> OfferObservation:
    return OfferObservation(
        offer_id=oid(external_id, source),
        level=ObservationLevel.LISTING,
        url=f"https://example.test/{source}/{external_id}" if url == "default" else url,
        title=title,
        price=price,
        refreshed_at=refreshed_at,
        promoted=promoted,
    )


def details(
    external_id: str,
    *,
    source: str = "olx_pl",
    title: str | None = "Laptop GTX 1650",
    price: Price | None = DEFAULT_PRICE,
    description: str = "Gaming laptop, GTX 1650, 16 GB RAM",
    params: dict[str, str] | None = None,
    status: OfferStatus | None = OfferStatus.ACTIVE,
    refreshed_at: datetime | None = None,
) -> OfferObservation:
    return OfferObservation(
        offer_id=oid(external_id, source),
        level=ObservationLevel.DETAILS,
        url=f"https://example.test/{source}/{external_id}",
        title=title,
        price=price,
        description=description,
        params=Params.of(params if params is not None else {"state": "used"}),
        status=status,
        refreshed_at=refreshed_at,
    )

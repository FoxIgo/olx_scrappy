from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from scrappy.domain.offer import (
    ObservationLevel,
    OfferId,
    OfferStatus,
    Price,
    PriceKind,
    SellerRef,
)
from scrappy.domain.shared import SourceId
from scrappy.infrastructure.scraping.sources.olx_pl.mapper import (
    RecordInvalid,
    map_api_offer,
)

from .conftest import fixture_json

PLUS2 = timezone(timedelta(hours=2))


def _set_price(item: dict[str, Any], **value: Any) -> dict[str, Any]:
    out = copy.deepcopy(item)
    price = next(p for p in out["params"] if p["key"] == "price")
    price["value"].update(value)
    return out


def test_golden_mapping_of_first_search_item(first_item: dict[str, Any]) -> None:
    obs = map_api_offer(first_item)

    assert obs.offer_id == OfferId(SourceId("olx_pl"), "1098526767")
    assert obs.level is ObservationLevel.DETAILS
    assert obs.url == first_item["url"]
    assert obs.title == "Laptop Gamingowy Asus TUF F15 GTX1650 16gb RAM"
    assert obs.price == Price.fixed("1300", "PLN")
    assert obs.location == "Bestwina, Śląskie"
    assert obs.posted_at == datetime(2026, 9, 15, 20, 21, 33, tzinfo=PLUS2)
    assert obs.refreshed_at == datetime(2026, 10, 8, 18, 27, 21, tzinfo=PLUS2)
    assert obs.posted_at is not None
    assert obs.posted_at.utcoffset() == timedelta(hours=2)
    assert obs.promoted is True  # promotion.top_ad
    assert obs.status is OfferStatus.ACTIVE
    assert obs.seller == SellerRef(external_id="24901353", name="Adam", is_business=False)
    assert obs.description == first_item["description"]
    assert obs.is_detail_complete


def test_params_exclude_price_and_use_labels(first_item: dict[str, Any]) -> None:
    obs = map_api_offer(first_item)
    assert obs.params is not None
    params = obs.params.as_dict()
    assert "price" not in params
    assert params["state"] == "Używane"
    assert params["ramsize_laptops"] == "16GB"
    assert params["screendiagonal_laptops"] == '15-15,9"'
    assert len(params) == 9
    assert list(params) == sorted(params)


def test_photos_resolve_size_templates(first_item: dict[str, Any]) -> None:
    obs = map_api_offer(first_item)
    assert obs.image_urls is not None
    assert len(obs.image_urls) == 3
    assert obs.image_urls[0] == (
        "https://ireland.apollo.olxcdn.com:443/v1/files/4q25lswak8ld1-PL/image;s=1000x700"
    )
    assert obs.thumbnail_url == (
        "https://ireland.apollo.olxcdn.com:443/v1/files/4q25lswak8ld1-PL/image;s=516x361"
    )
    assert all("{" not in url for url in obs.image_urls)


def test_no_photos_gives_empty_images_and_no_thumbnail(first_item: dict[str, Any]) -> None:
    first_item["photos"] = []
    obs = map_api_offer(first_item)
    assert obs.image_urls == ()
    assert obs.thumbnail_url is None


def test_arranged_price_is_negotiable_fixed(search_page1: dict[str, Any]) -> None:
    obs = map_api_offer(search_page1["data"][1])
    assert obs.price == Price.fixed("1400", "PLN", negotiable=True)


def test_exchange_price(first_item: dict[str, Any]) -> None:
    obs = map_api_offer(_set_price(first_item, value=0, type="exchange", label="Zamienię"))
    assert obs.price == Price.exchange()
    assert obs.price is not None
    assert obs.price.amount is None


def test_free_price_by_type_and_by_label(first_item: dict[str, Any]) -> None:
    by_type = map_api_offer(_set_price(first_item, value=0, type="free", label="x"))
    by_label = map_api_offer(_set_price(first_item, value=0, type="price", label="Za darmo"))
    assert by_type.price == by_label.price == Price.free()


def test_budget_price_with_amount_is_fixed(first_item: dict[str, Any]) -> None:
    obs = map_api_offer(_set_price(first_item, budget=True, value=999, type="price"))
    assert obs.price == Price.fixed("999", "PLN")


def test_decimal_amount_keeps_precision(first_item: dict[str, Any]) -> None:
    obs = map_api_offer(_set_price(first_item, value=1299.99))
    assert obs.price is not None
    assert obs.price.kind is PriceKind.FIXED
    assert str(obs.price.amount) == "1299.99 PLN"


def test_zero_price_without_kind_is_not_observed_and_rejected_when_required(
    first_item: dict[str, Any],
) -> None:
    item = _set_price(first_item, value=0, type="price")
    with pytest.raises(RecordInvalid, match="price"):
        map_api_offer(item)
    assert map_api_offer(item, require_price=False).price is None


def test_missing_price_param_is_rejected(first_item: dict[str, Any]) -> None:
    first_item["params"] = [p for p in first_item["params"] if p["key"] != "price"]
    with pytest.raises(RecordInvalid, match="price"):
        map_api_offer(first_item)


@pytest.mark.parametrize("field", ["id", "url", "title", "description", "status"])
def test_required_fields(first_item: dict[str, Any], field: str) -> None:
    del first_item[field]
    with pytest.raises(RecordInvalid, match=field):
        map_api_offer(first_item)


def test_naive_datetime_is_rejected(first_item: dict[str, Any]) -> None:
    first_item["created_time"] = "2026-09-15T20:21:33"
    with pytest.raises(RecordInvalid, match="created_time"):
        map_api_offer(first_item)


def test_empty_description_is_still_a_valid_observation(first_item: dict[str, Any]) -> None:
    first_item["description"] = ""
    assert map_api_offer(first_item).description == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("active", OfferStatus.ACTIVE),
        ("removed_by_user", OfferStatus.REMOVED),
        ("moderated", OfferStatus.REMOVED),
        ("sold", OfferStatus.SOLD),
    ],
)
def test_status_mapping(first_item: dict[str, Any], raw: str, expected: OfferStatus) -> None:
    first_item["status"] = raw
    assert map_api_offer(first_item).status is expected


def test_long_description_detail_fixture() -> None:
    data = fixture_json("api_offer_detail_long_description.json")["data"]
    obs = map_api_offer(data, require_price=False)
    assert obs.description is not None
    assert len(obs.description) == 3925
    assert "<br />" in obs.description  # raw, application strips HTML
    assert obs.price == Price.fixed("1290", "PLN")


def test_offer_without_user_has_no_seller(first_item: dict[str, Any]) -> None:
    del first_item["user"]
    del first_item["business"]
    assert map_api_offer(first_item).seller is None

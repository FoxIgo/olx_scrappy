"""Raw olx.pl payloads -> :class:`OfferObservation` (DETAILS level).

Mapping decisions
-----------------
* **Price** (ADR 0008 open issue 6). API: the ``params[key=="price"]`` entry; state: ``price``.

  ===================================================  ===============================
  OLX                                                  domain ``Price``
  ===================================================  ===============================
  ``type == "exchange"`` / label ``Zamienię``          ``EXCHANGE`` (no amount)
  ``type == "free"`` / label ``Za darmo``              ``FREE`` (no amount)
  ``type == "price"`` and value > 0                    ``FIXED``
  ``type == "arranged"`` ("do negocjacji") and > 0     ``FIXED``, negotiable
  ``budget`` (a wanted-ad budget) and value > 0        ``FIXED`` (the budget is the amount)
  anything else (0 / missing value, unknown type)      ``None`` = not observed
  ===================================================  ===============================

  ``negotiable`` is ``negotiable or arranged``. Zero is never an amount.
* **Params**: ``key -> label`` of every entry except ``price``. The normalized value key
  (``used``) is dropped because ``Params`` holds text pairs only; labels are what the LLM reads.
* **Location**: ``"<city>, <region>"`` (district and the fuzzy map point are ignored).
* **Photos**: API links are templates ``...;s={width}x{height}``. ``image_urls`` use
  ``IMAGE_SIZE`` (the site's largest srcset size) and ``thumbnail_url`` uses ``THUMB_SIZE``;
  OLX treats ``s=WxH`` as a bounding box, so any size works. State photos already carry
  ``;s=<original>`` and are rewritten to the same sizes.
* **Description**: kept raw (``<br />`` and entities); the application strips HTML in
  ``application/extraction/prepare.py``.
* **Status**: ``active`` -> ACTIVE; ``sold*`` -> SOLD; any other status -> REMOVED
  (``removed_by_user``, ``moderated``, ``unpaid``, ``limited``... the offer is not publicly
  available; the exact set is unverified, see spike section 5).
* **Promoted**: ``promotion.top_ad`` (API) / ``isPromoted`` (state).
* **Delivery / safe buy**: ``delivery.rock.active`` (API / state) ->
  ``has_delivery`` (True if active).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from scrappy.domain.offer import (
    ObservationLevel,
    OfferId,
    OfferObservation,
    OfferStatus,
    Params,
    Price,
    SellerRef,
)
from scrappy.domain.shared import InvalidValueError, Money, SourceId

from .schemas import ApiDelivery, ApiOffer, ApiPriceValue, StateAd

SOURCE_ID = SourceId("olx_pl")
IMAGE_SIZE = "1000x700"
THUMB_SIZE = "516x361"

_SIZE_TEMPLATE = "{width}x{height}"
_SIZE_SUFFIX = re.compile(r";s=\d+x\d+$")


class RecordInvalid(ValueError):
    """A record fails validation or mapping; becomes a ``RecordRejection``."""


def describe_validation_error(exc: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()[:5]
    ]
    return "; ".join(parts)


# ----------------------------------------------------------------------------- shared helpers


def is_delivery_active(delivery: ApiDelivery | None) -> bool:
    if delivery is None or delivery.rock is None:
        return False
    return bool(delivery.rock.active)


def status_from_text(raw: str) -> OfferStatus:
    text = raw.strip().lower()
    if text == "active":
        return OfferStatus.ACTIVE
    if text.startswith("sold"):
        return OfferStatus.SOLD
    return OfferStatus.REMOVED


def build_price(
    amount: Decimal | None,
    currency: str | None,
    *,
    kind: str | None,
    label: str | None,
    negotiable: bool,
    arranged: bool,
    budget: bool,
    exchange: bool = False,
    free: bool = False,
) -> Price | None:
    """Apply the price-kind table of the module docstring; ``None`` = not observed."""
    kind = (kind or "").lower()
    label_norm = (label or "").strip().lower()
    if exchange or kind == "exchange" or label_norm == "zamienię":
        return Price.exchange()
    if free or kind == "free" or label_norm == "za darmo":
        return Price.free()
    if amount is None or amount <= 0:
        return None
    try:
        money = Money.of(amount, currency or "PLN")
        return Price.fixed(money, negotiable=negotiable or arranged or kind == "arranged")
    except (InvalidValueError, ArithmeticError) as exc:
        raise RecordInvalid(f"invalid price: {exc}") from exc


def _photo_url(link: str, size: str) -> str:
    if _SIZE_TEMPLATE in link:
        return link.replace(_SIZE_TEMPLATE, size)
    return _SIZE_SUFFIX.sub(f";s={size}", link)


def build_images(links: Iterable[str]) -> tuple[tuple[str, ...], str | None]:
    """(image_urls at IMAGE_SIZE, thumbnail at THUMB_SIZE or None without photos)."""
    items = list(links)
    images = tuple(_photo_url(link, IMAGE_SIZE) for link in items)
    thumb = _photo_url(items[0], THUMB_SIZE) if items else None
    return images, thumb


def build_location(city: str | None, region: str | None) -> str | None:
    parts = [p.strip() for p in (city, region) if p and p.strip()]
    return ", ".join(parts) if parts else None


def build_params(pairs: Iterable[tuple[str, str | None]]) -> Params:
    values = {key: label.strip() for key, label in pairs if label and label.strip()}
    return Params.of(values)


def _label_of(value: object) -> str | None:
    if isinstance(value, dict):
        raw = value.get("label") or value.get("key")
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        raw = value
    else:
        raw = None
    return str(raw) if raw not in (None, "") else None


def _seller(
    user_id: object,
    name: str | None,
    is_business: bool | None,
    created_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    is_online: bool | None = None,
) -> SellerRef | None:
    external = str(user_id).strip() if user_id not in (None, "") else None
    if (
        external is None
        and name is None
        and is_business is None
        and created_at is None
        and last_seen_at is None
        and is_online is None
    ):
        return None
    return SellerRef(
        external_id=external,
        name=name or None,
        is_business=is_business,
        created_at=created_at,
        last_seen_at=last_seen_at,
        is_online=is_online,
    )


# ----------------------------------------------------------------------------- API mapping


def api_price(offer: ApiOffer) -> Price | None:
    param = offer.param("price")
    if param is None or not isinstance(param.value, dict):
        return None
    pv = ApiPriceValue.model_validate(param.value)
    return build_price(
        pv.value,
        pv.currency,
        kind=pv.type,
        label=pv.label,
        negotiable=pv.negotiable,
        arranged=pv.arranged,
        budget=pv.budget,
    )


def map_api_offer(raw: object, *, require_price: bool = True) -> OfferObservation:
    """Validate and map one search/detail API item. Raises :class:`RecordInvalid`."""
    try:
        offer = ApiOffer.model_validate(raw)
        price = api_price(offer)
        if price is None and require_price:
            raise RecordInvalid("missing or unusable price (ADR 0005: required for discovery)")
        images, thumb = build_images(p.link for p in offer.photos)
        city = offer.location.city.name if offer.location and offer.location.city else None
        region = offer.location.region.name if offer.location and offer.location.region else None
        return OfferObservation(
            offer_id=OfferId(SOURCE_ID, offer.external_id),
            level=ObservationLevel.DETAILS,
            url=offer.url,
            title=offer.title.strip(),
            price=price,
            location=build_location(city, region),
            thumbnail_url=thumb,
            posted_at=offer.created_time,
            refreshed_at=offer.last_refresh_time,
            promoted=bool(offer.promotion and offer.promotion.top_ad),
            has_delivery=is_delivery_active(offer.delivery),
            description=offer.description,
            params=build_params(
                (p.key, _label_of(p.value)) for p in offer.params if p.key != "price"
            ),
            status=status_from_text(offer.status),
            seller=_seller(
                offer.user.id if offer.user else None,
                offer.user.name if offer.user else None,
                offer.business,
                created_at=offer.user.created if offer.user else None,
                last_seen_at=offer.user.last_seen if offer.user else None,
                is_online=offer.user.is_online if offer.user else None,
            ),
            image_urls=images,
        )
    except ValidationError as exc:
        raise RecordInvalid(describe_validation_error(exc)) from exc
    except InvalidValueError as exc:
        raise RecordInvalid(str(exc)) from exc


# ----------------------------------------------------------------------------- state mapping


def map_state_ad(raw: object, *, require_price: bool = True) -> OfferObservation:
    """Same semantics as :func:`map_api_offer` for the camelCase embedded-state ad."""
    try:
        ad = StateAd.model_validate(raw)
        price = None
        if ad.price is not None:
            regular = ad.price.regularPrice
            price = build_price(
                regular.value if regular else None,
                regular.currencyCode if regular else None,
                kind=None,
                label=None,
                negotiable=regular.negotiable if regular else False,
                arranged=False,
                budget=ad.price.budget,
                exchange=ad.price.exchange,
                free=ad.price.free,
            )
        if price is None and require_price:
            raise RecordInvalid("missing or unusable price (ADR 0005: required for discovery)")
        images, thumb = build_images(ad.photos)
        return OfferObservation(
            offer_id=OfferId(SOURCE_ID, ad.external_id),
            level=ObservationLevel.DETAILS,
            url=ad.url,
            title=ad.title.strip(),
            price=price,
            location=build_location(
                ad.location.cityName if ad.location else None,
                ad.location.regionName if ad.location else None,
            ),
            thumbnail_url=thumb,
            posted_at=ad.createdTime,
            refreshed_at=ad.lastRefreshTime,
            promoted=ad.isPromoted,
            has_delivery=is_delivery_active(ad.delivery),
            description=ad.description,
            params=build_params((p.key, _label_of(p.value)) for p in ad.params if p.key != "price"),
            status=status_from_text(ad.status),
            seller=_seller(
                ad.user.id if ad.user else None,
                ad.user.name if ad.user else None,
                ad.isBusiness,
                created_at=ad.user.created if ad.user else None,
                last_seen_at=ad.user.lastSeen if ad.user else None,
                is_online=ad.user.isOnline if ad.user else None,
            ),
            image_urls=images,
        )
    except ValidationError as exc:
        raise RecordInvalid(describe_validation_error(exc)) from exc
    except InvalidValueError as exc:
        raise RecordInvalid(str(exc)) from exc

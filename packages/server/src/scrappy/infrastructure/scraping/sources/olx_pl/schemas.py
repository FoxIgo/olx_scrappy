"""Pydantic models of the raw olx.pl payloads (anti-corruption layer, ADR 0005).

Lenient on purpose (``extra="ignore"``, almost everything optional) except for the fields
ADR 0005 makes mandatory for a DETAILS-level record: id, url, title, description, status.
A price is required too (discovery rule) but that is checked in the mapper, because it lives
inside ``params[]`` in the API and the rule is configurable.

A model failing validation turns one item into a :class:`RecordRejection`; it never fails the
whole page. Datetimes must be timezone-aware.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must carry a UTC offset")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(lambda v: _aware(v))]


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _external_id(value: Any) -> str:
    text = str(value).strip()
    if not text or text == "None":
        raise ValueError("id must not be empty")
    return text


# ----------------------------------------------------------------------------- API (search/detail)


class ApiPriceValue(_Lenient):
    value: Decimal | None = None
    type: str | None = None
    currency: str | None = None
    negotiable: bool = False
    arranged: bool = False
    budget: bool = False
    label: str | None = None


class ApiParam(_Lenient):
    key: str
    name: str | None = None
    type: str | None = None
    value: Any = None


class ApiPhoto(_Lenient):
    link: str
    width: int | None = None
    height: int | None = None


class ApiUser(_Lenient):
    id: int | str | None = None
    uuid: str | None = None
    name: str | None = None
    seller_type: str | None = None
    company_name: str | None = None
    created: AwareDatetime | None = None
    last_seen: AwareDatetime | None = None
    is_online: bool | None = None


class ApiNamed(_Lenient):
    name: str | None = None


class ApiLocation(_Lenient):
    city: ApiNamed | None = None
    region: ApiNamed | None = None


class ApiPromotion(_Lenient):
    top_ad: bool = False
    highlighted: bool = False
    urgent: bool = False


class ApiDeliveryRock(_Lenient):
    active: bool = False
    mode: str | None = None
    offer_id: str | None = None


class ApiDelivery(_Lenient):
    rock: ApiDeliveryRock | None = None


class ApiOffer(_Lenient):
    """One ``data[]`` item of the search API, or ``data`` of the detail API (same shape)."""

    id: int | str
    url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str
    status: str = Field(min_length=1)
    created_time: AwareDatetime | None = None
    last_refresh_time: AwareDatetime | None = None
    valid_to_time: AwareDatetime | None = None
    params: list[ApiParam] = Field(default_factory=lambda: list[ApiParam]())
    photos: list[ApiPhoto] = Field(default_factory=lambda: list[ApiPhoto]())
    user: ApiUser | None = None
    business: bool | None = None
    location: ApiLocation | None = None
    promotion: ApiPromotion | None = None
    delivery: ApiDelivery | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: int | str) -> int | str:
        _external_id(value)
        return value

    @property
    def external_id(self) -> str:
        return _external_id(self.id)

    def param(self, key: str) -> ApiParam | None:
        return next((p for p in self.params if p.key == key), None)


class ApiMetadata(_Lenient):
    total_elements: int | None = None
    visible_total_count: int | None = None


class ApiLink(_Lenient):
    href: str | None = None


class ApiLinks(_Lenient):
    next: ApiLink | None = None


class ApiSearchEnvelope(_Lenient):
    """The page-level envelope; items stay raw dicts so each is validated on its own."""

    data: list[Any]
    metadata: ApiMetadata = Field(default_factory=ApiMetadata)
    links: ApiLinks = Field(default_factory=ApiLinks)


# ----------------------------------------------------------------------------- embedded state


class StateParam(_Lenient):
    key: str
    value: Any = None
    normalizedValue: Any = None


class StateRegularPrice(_Lenient):
    value: Decimal | None = None
    currencyCode: str | None = None
    negotiable: bool = False


class StatePrice(_Lenient):
    budget: bool = False
    free: bool = False
    exchange: bool = False
    displayValue: str | None = None
    regularPrice: StateRegularPrice | None = None


class StateLocation(_Lenient):
    cityName: str | None = None
    regionName: str | None = None


class StateUser(_Lenient):
    id: int | str | None = None
    name: str | None = None
    created: AwareDatetime | None = None
    lastSeen: AwareDatetime | None = None
    isOnline: bool | None = None


class StateAd(_Lenient):
    """One ``listing.listing.ads[]`` item of ``window.__PRERENDERED_STATE__`` (camelCase)."""

    id: int | str
    url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    status: str = Field(min_length=1)
    createdTime: AwareDatetime | None = None
    lastRefreshTime: AwareDatetime | None = None
    validToTime: AwareDatetime | None = None
    params: list[StateParam] = Field(default_factory=lambda: list[StateParam]())
    price: StatePrice | None = None
    photos: list[str] = Field(default_factory=lambda: list[str]())
    location: StateLocation | None = None
    user: StateUser | None = None
    isBusiness: bool | None = None
    isPromoted: bool = False
    delivery: ApiDelivery | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: int | str) -> int | str:
        _external_id(value)
        return value

    @property
    def external_id(self) -> str:
        return _external_id(self.id)

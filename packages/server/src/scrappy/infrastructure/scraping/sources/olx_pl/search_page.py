"""Shared assembly of a :class:`SearchPageResult` from parsed (API or HTML-state) items."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scrappy.application.ports.listing_source import PageRef, RecordRejection, SearchPageResult
from scrappy.domain.offer import OfferObservation
from scrappy.domain.shared import FetchOutcome

from .mapper import RecordInvalid
from .urls import MAX_OFFSET, next_page_ref, offset_of

type ItemMapper = Callable[..., OfferObservation]


@dataclass(frozen=True, slots=True)
class ParsedSearchPage:
    items: list[Any]
    total_elements: int | None = None
    visible_total: int | None = None
    next_href: str | None = None


def _raw_id(raw: Any) -> str | None:
    value = raw.get("id") if isinstance(raw, dict) else None
    return str(value).strip() if value not in (None, "") else None  # pyright: ignore[reportUnknownArgumentType]


def assemble_search_result(
    parsed: ParsedSearchPage,
    *,
    page: PageRef,
    mapper: ItemMapper,
    require_price: bool,
    raw_ref: str | None = None,
    force_truncated: bool = False,
) -> SearchPageResult:
    """Dedupe by id (promoted offers repeat; first occurrence wins), validate per item,
    compute ``total_results`` / ``truncated`` / ``next_page``."""
    seen: set[str] = set()
    observations: list[OfferObservation] = []
    rejections: list[RecordRejection] = []
    for raw in parsed.items:
        external_id = _raw_id(raw)
        if external_id is not None:
            if external_id in seen:
                continue
            seen.add(external_id)
        try:
            observations.append(mapper(raw, require_price=require_price))
        except RecordInvalid as exc:
            rejections.append(RecordRejection(str(exc), external_id, raw_ref))

    truncated = force_truncated or (
        parsed.total_elements is not None
        and parsed.visible_total is not None
        and parsed.visible_total > parsed.total_elements
    )
    next_page: PageRef | None = None
    if parsed.items and parsed.next_href:
        candidate = next_page_ref(parsed.next_href, page)
        if candidate is not None:
            offset = offset_of(candidate.cursor)
            if offset is not None and offset > MAX_OFFSET:
                truncated = True
            else:
                next_page = candidate
    return SearchPageResult(
        FetchOutcome.OK,
        observations=tuple(observations),
        rejections=tuple(rejections),
        next_page=next_page,
        total_results=parsed.total_elements,
        truncated=truncated,
        raw_ref=raw_ref,
    )

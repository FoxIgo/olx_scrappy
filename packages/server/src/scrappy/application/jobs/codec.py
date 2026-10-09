"""JSON-compatible encoding of job payloads and results, for queue adapters.

Adapters store ``(type, encode_payload(...))`` and ``encode_result(...)`` as JSON and decode
them with the inverse functions. Only plain ``dict``/``list``/``str``/``int``/``bool``/``None``
are produced; Decimal costs are encoded as strings. Round-trips are lossless.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from scrappy.application.jobs.model import (
    DiscoverPagePayload,
    EnrichOfferPayload,
    ExtractOfferPayload,
    JobPayload,
    JobResult,
    JobType,
)
from scrappy.application.ports.listing_source import PageRef
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash, OfferId
from scrappy.domain.run import DiscoveryCoverage, PhaseMetrics, RunMetrics
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, InvalidValueError

type JsonDict = dict[str, Any]


def encode_payload(payload: JobPayload) -> JsonDict:
    match payload:
        case DiscoverPagePayload(search=search, page=page):
            return {"search": search.value, "cursor": page.cursor, "page": page.number}
        case EnrichOfferPayload(offer_id=offer_id, request_tag=tag):
            return {"offer_id": str(offer_id), "request_tag": tag}
        case ExtractOfferPayload(
            offer_id=offer_id,
            content_hash=content_hash,
            catalog_version=catalog_version,
            force=force,
            request_tag=tag,
        ):
            return {
                "offer_id": str(offer_id),
                "content_hash": content_hash.value,
                "catalog_version": catalog_version,
                "force": force,
                "request_tag": tag,
            }


def decode_payload(job_type: JobType, data: JsonDict) -> JobPayload:
    match job_type:
        case JobType.DISCOVER_PAGE:
            return DiscoverPagePayload(
                SearchName(data["search"]), PageRef(data["cursor"], int(data["page"]))
            )
        case JobType.ENRICH_OFFER:
            return EnrichOfferPayload(OfferId.parse(data["offer_id"]), data.get("request_tag"))
        case JobType.EXTRACT_OFFER:
            return ExtractOfferPayload(
                OfferId.parse(data["offer_id"]),
                ContentHash(data["content_hash"]),
                str(data["catalog_version"]),
                force=bool(data.get("force", False)),
                request_tag=data.get("request_tag"),
            )


def _encode_phase(metrics: PhaseMetrics) -> JsonDict:
    return {
        "accepted": metrics.accepted,
        "rejected": metrics.rejected,
        "present": dict(metrics.present),
        "applicable": dict(metrics.applicable),
        "outcomes": {outcome.value: n for outcome, n in metrics.outcomes.items()},
    }


def _decode_phase(data: JsonDict) -> PhaseMetrics:
    outcomes = cast(dict[str, int], data.get("outcomes", {}))
    return PhaseMetrics(
        accepted=int(data.get("accepted", 0)),
        rejected=int(data.get("rejected", 0)),
        present=dict(cast(dict[str, int], data.get("present", {}))),
        applicable=dict(cast(dict[str, int], data.get("applicable", {}))),
        outcomes={FetchOutcome(key): int(n) for key, n in outcomes.items()},
    )


def encode_metrics(metrics: RunMetrics) -> JsonDict:
    """Also usable by run repositories to persist :class:`RunMetrics`."""
    return {
        "discovery": _encode_phase(metrics.discovery),
        "enrichment": _encode_phase(metrics.enrichment),
        "extraction": _encode_phase(metrics.extraction),
        "usage": {
            "prompt_tokens": metrics.usage.prompt_tokens,
            "completion_tokens": metrics.usage.completion_tokens,
            "cost_usd": None if metrics.usage.cost_usd is None else str(metrics.usage.cost_usd),
        },
        "coverage": {
            "pages": metrics.coverage.pages,
            "total_reported": metrics.coverage.total_reported,
            "truncated": metrics.coverage.truncated,
        },
        "failed_jobs": metrics.failed_jobs,
    }


def decode_metrics(data: JsonDict) -> RunMetrics:
    usage = cast(JsonDict, data.get("usage", {}))
    coverage = cast(JsonDict, data.get("coverage", {}))
    cost = usage.get("cost_usd")
    return RunMetrics(
        discovery=_decode_phase(cast(JsonDict, data.get("discovery", {}))),
        enrichment=_decode_phase(cast(JsonDict, data.get("enrichment", {}))),
        extraction=_decode_phase(cast(JsonDict, data.get("extraction", {}))),
        usage=TokenUsage(
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            None if cost is None else Decimal(str(cost)),
        ),
        coverage=DiscoveryCoverage(
            pages=int(coverage.get("pages", 0)),
            total_reported=coverage.get("total_reported"),
            truncated=bool(coverage.get("truncated", False)),
        ),
        failed_jobs=int(data.get("failed_jobs", 0)),
    )


def encode_result(result: JobResult) -> JsonDict:
    return {"metrics": encode_metrics(result.metrics), "notes": list(result.notes)}


def decode_result(data: JsonDict) -> JobResult:
    notes = data.get("notes", [])
    if not isinstance(notes, list):
        raise InvalidValueError("JobResult.notes must be a list")
    return JobResult(
        metrics=decode_metrics(cast(JsonDict, data.get("metrics", {}))),
        notes=tuple(str(note) for note in cast(list[object], notes)),
    )

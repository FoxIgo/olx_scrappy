"""Fake extraction profiles, health checks and an in-memory batch backend (ADR 0010).

``FakeBatchBackend`` is the reference behaviour of the ``BatchExtractionBackend`` port for
adapter authors: submit returns at once with a provider id; ``poll`` reports RUNNING until
the test settles the batch (``complete`` / ``fail`` / ``expire``), or immediately when
``auto`` is set (each item answered by the script, like a provider would).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from scrappy.application.ports.extraction_backends import (
    BatchBackendError,
    BatchItemResult,
    BatchPoll,
    BatchRequestItem,
    BatchSettings,
    BatchState,
    ExtractionMode,
    ExtractionProfile,
    ProfileCapabilities,
    ProfileHealth,
    StaticExtractionProfiles,
    SubmittedBatch,
)
from scrappy.application.ports.extractor import (
    AttributeExtractor,
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RuleExtraction,
)
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import OfferId
from tests.unit.fakes.system import FakeClock

PROMPT = "p1"

type ItemScript = Callable[[ExtractionInput], ExtractionResult | ExtractionRejection]


class FakeHealth:
    def __init__(self, ok: bool = True, detail: str = "ok") -> None:
        self.ok = ok
        self.detail = detail
        self.calls: list[bool] = []
        """The ``probe`` flag of every call."""

    async def check(self, *, probe: bool = False) -> ProfileHealth:
        self.calls.append(probe)
        return ProfileHealth(self.ok, self.detail)


@dataclass
class _ProviderBatch:
    handle: SubmittedBatch
    items: list[BatchRequestItem]
    batch_ref: str
    state: BatchState = BatchState.RUNNING
    results: list[BatchItemResult] = field(default_factory=list[BatchItemResult])
    error: str | None = None
    usage: TokenUsage | None = None


class FakeBatchBackend:
    def __init__(self, clock: FakeClock, script: ItemScript | None = None) -> None:
        self._clock = clock
        self.script = script
        self.auto = False
        """Settle every batch as COMPLETED (with ``script``) on its first poll."""
        self.batches: dict[str, _ProviderBatch] = {}
        self.submit_error: BatchBackendError | None = None
        self.fail_submit_when: Callable[[Sequence[BatchRequestItem]], str | None] | None = None
        """Validation failure: return an error text to fail the *batch* on its first poll."""
        self.cost: object = None
        self.polls = 0

    # ------------------------------------------------------------------ port
    async def submit(self, items: Sequence[BatchRequestItem], *, batch_ref: str) -> SubmittedBatch:
        if self.submit_error is not None:
            raise self.submit_error
        provider_id = f"pb{len(self.batches) + 1}"
        handle = SubmittedBatch(provider_id, self._clock.now(), len(items))
        batch = _ProviderBatch(handle, list(items), batch_ref)
        if self.fail_submit_when is not None:
            reason = self.fail_submit_when(items)
            if reason is not None:
                batch.state, batch.error = BatchState.FAILED, reason
        self.batches[provider_id] = batch
        return handle

    async def poll(self, batch: SubmittedBatch) -> BatchPoll:
        self.polls += 1
        provider = self.batches[batch.provider_batch_id]
        if provider.state is BatchState.RUNNING and self.auto:
            self.complete(batch.provider_batch_id)
        return BatchPoll(
            provider.state,
            total=len(provider.items),
            completed=len(provider.results),
            error=provider.error,
            usage=provider.usage,
        )

    async def results(self, batch: SubmittedBatch) -> AsyncIterator[BatchItemResult]:
        for result in self.batches[batch.provider_batch_id].results:
            yield result

    async def cancel(self, batch: SubmittedBatch) -> bool:
        return False

    async def find_submitted(
        self,
        *,
        batch_ref: str,
        item_count: int,
        custom_ids: Sequence[str],
        submitted_after: datetime,
        submitted_before: datetime,
    ) -> SubmittedBatch | None:
        for provider in self.batches.values():
            if provider.batch_ref == batch_ref and len(provider.items) == item_count:
                return provider.handle
        return None

    # ------------------------------------------------------------------ test controls
    def complete(
        self,
        provider_id: str,
        outcomes: dict[str, ExtractionResult | ExtractionRejection] | None = None,
        *,
        drop: Sequence[str] = (),
        cost: object = None,
    ) -> None:
        provider = self.batches[provider_id]
        results: list[BatchItemResult] = []
        for item in provider.items:
            if item.custom_id in drop:
                continue
            outcome = (outcomes or {}).get(item.custom_id)
            if outcome is None:
                assert self.script is not None, "no outcome and no script"
                outcome = self.script(item.input)
            results.append(BatchItemResult(item.custom_id, outcome))
        provider.results = results
        provider.state = BatchState.COMPLETED
        if cost is not None:
            tokens = sum((r.outcome.usage for r in results), TokenUsage())
            provider.usage = TokenUsage(
                tokens.prompt_tokens, tokens.completion_tokens, Decimal(str(cost))
            )

    def fail(self, provider_id: str, error: str = "validation failed") -> None:
        provider = self.batches[provider_id]
        provider.state, provider.error = BatchState.FAILED, error

    def expire(self, provider_id: str) -> None:
        self.batches[provider_id].state = BatchState.EXPIRED

    def register_orphan(self, batch_ref: str, items: Sequence[BatchRequestItem]) -> str:
        """A batch the provider accepted although our process died before recording it."""
        provider_id = f"pb{len(self.batches) + 1}"
        handle = SubmittedBatch(provider_id, self._clock.now(), len(items))
        self.batches[provider_id] = _ProviderBatch(handle, list(items), batch_ref)
        return provider_id


def make_profile(
    name: str,
    extractor: AttributeExtractor,
    *,
    mode: ExtractionMode = ExtractionMode.SYNC,
    concurrency: int = 1,
    rate_limit: float | None = None,
    daily_limit: int | None = None,
    quota_timezone: str = "UTC",
    quota_group: str | None = None,
    backend: FakeBatchBackend | None = None,
    health: FakeHealth | None = None,
    batch: BatchSettings | None = None,
    prompt_version: str = PROMPT,
    model: str | None = None,
) -> ExtractionProfile:
    return ExtractionProfile(
        name=name,
        provider=f"fake-{name}",
        model=model or f"{name}-model",
        prompt_version=prompt_version,
        extractor=extractor,
        health=health or FakeHealth(),
        mode=mode,
        capabilities=ProfileCapabilities(
            supports_batch=backend is not None,
            concurrency=concurrency,
            rate_limit_per_minute=rate_limit,
            daily_limit=daily_limit,
            quota_timezone=quota_timezone,
            quota_group=quota_group,
        ),
        batch=batch or BatchSettings(min_size=3, max_size=10, max_open=2),
        batch_backend=backend,
    )


def profiles_of(*profiles: ExtractionProfile, pool: Sequence[str] = ()) -> StaticExtractionProfiles:
    """``pool`` = the lanes that run in parallel (default: just the first profile)."""
    return StaticExtractionProfiles(
        {p.name: p for p in profiles},
        default_profile=profiles[0].name,
        pool_names=tuple(pool),
    )


class ScriptedRules:
    """A :class:`~scrappy.application.ports.extractor.RuleExtractor` driven by a function
    (ADR 0012); records every input it saw."""

    def __init__(
        self, script: Callable[[ExtractionInput], RuleExtraction], version: str = "rules-t1"
    ) -> None:
        self._script = script
        self._version = version
        self.calls: list[ExtractionInput] = []

    @property
    def version(self) -> str:
        return self._version

    def extract(self, request: ExtractionInput) -> RuleExtraction:
        self.calls.append(request)
        return self._script(request)


class FixedTop:
    """:data:`~scrappy.application.use_cases.extraction.tiering.TopOffers` returning a set
    ranking (strategy -> offers, best first), cut to ``top_n``."""

    def __init__(self, ranking: dict[str, list[OfferId]] | None = None) -> None:
        self.ranking: dict[str, list[OfferId]] = dict(ranking or {})
        self.calls: list[tuple[int, float]] = []

    async def __call__(self, top_n: int, min_coverage: float) -> dict[str, list[OfferId]]:
        self.calls.append((top_n, min_coverage))
        return {name: ids[:top_n] for name, ids in self.ranking.items()}

"""TierExtractions: the rule pass and the LLM gate (ADR 0012).

One call does, in order:

1. **Rule pass** over the rules backlog (offers whose content has no up-to-date rule run):
   prepare the same input the LLM gets, run the :class:`RuleExtractor`, store the result as
   an extraction (unless an LLM extraction of the same content already exists: the LLM
   supersedes rules), and record on the extraction state which uncertainty reasons send the
   offer to the LLM.
2. **Component resolution** of the new CPU/GPU texts, so provisional scores have benchmarks.
3. **Promotion**: the ``top_n`` best provisional deals of every scoring strategy whose
   current extraction is still a rule one are escalated (``top:<strategy>``).

With ``tiering.enabled`` the reconciler's backlog is gated to escalated offers. The rule
pass is pure CPU work (about 1 ms per offer) and never calls out, so each chunk is one
transaction.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scrappy.application.extraction.ingest import store_extraction
from scrappy.application.extraction.prepare import prepare_extraction_input
from scrappy.application.policy import ExtractionPolicy
from scrappy.application.ports.extractor import RULES_MODEL, RuleExtractor
from scrappy.application.ports.scoring import ScoringProvider
from scrappy.application.ports.system import CategoryProvider, Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics.common import Json, QueryScope
from scrappy.application.use_cases.analytics.rank import Rank
from scrappy.domain.category import CategoryCatalog
from scrappy.domain.extraction import ExtractionState, OfferExtraction
from scrappy.domain.offer import OfferId
from scrappy.domain.shared import InvalidValueError

RULES_PROFILE = "rules"
INVALID_REASON = "rules_invalid"
TOP_PREFIX = "top:"
DEFAULT_CHUNK = 200

type TopOffers = Callable[[int, float], Awaitable[Mapping[str, Sequence[OfferId]]]]
"""``(top_n, min_coverage)`` -> strategy name -> its best offers, best first."""
type Resolve = Callable[[], Awaitable[object]]


@dataclass(slots=True)
class TierReport:
    ruled: int = 0
    """Offers the rule pass ran on."""
    stored: int = 0
    """Rule extractions stored (offers with a current LLM extraction keep it)."""
    escalated: int = 0
    """Offers sent to the LLM because the rules were unsure."""
    promoted: int = 0
    """Offers sent to the LLM as top provisional deals."""
    reasons: dict[str, int] = field(default_factory=dict[str, int])
    """Escalation reason -> offers (uncertainty reasons and ``top:<strategy>``)."""
    notes: list[str] = field(default_factory=list[str])

    @property
    def did_work(self) -> bool:
        return self.ruled > 0 or self.promoted > 0


class ProvisionalTop:
    """:data:`TopOffers` from ``q rank``: each configured strategy's best offers."""

    def __init__(self, rank: Rank, provider: ScoringProvider) -> None:
        self._rank = rank
        self._provider = provider

    async def __call__(self, top_n: int, min_coverage: float) -> dict[str, list[OfferId]]:
        result: dict[str, list[OfferId]] = {}
        for name in await self._provider.strategies():
            answer = await self._rank(
                QueryScope(), name, min_coverage=min_coverage, limit=top_n, fields=("id",)
            )
            rows = cast("list[Json]", answer.data)
            result[name] = [OfferId.parse(str(row["id"])) for row in rows]
        return result


class TierExtractions:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        clock: Clock,
        categories: CategoryProvider,
        rules: RuleExtractor,
        policy: ExtractionPolicy,
        resolve: Resolve | None = None,
        top_offers: TopOffers | None = None,
        chunk: int = DEFAULT_CHUNK,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._categories = categories
        self._rules = rules
        self._policy = policy
        self._resolve = resolve
        self._top_offers = top_offers
        self._chunk = chunk

    @property
    def enabled(self) -> bool:
        return self._policy.tiering.enabled

    def version(self, catalog: CategoryCatalog) -> str:
        """What a rule run is valid for: the rules and the catalog they validated against."""
        return f"{self._rules.version}:{catalog.fingerprint}"

    async def backlog(self) -> int:
        catalog = await self._categories.catalog()
        async with self._uow() as uow:
            return len(await uow.extraction_states.rules_backlog(self.version(catalog)))

    async def __call__(
        self, *, limit: int | None = None, promote: bool | None = None
    ) -> TierReport:
        """Run the rule pass (up to ``limit`` offers) and the promotion.

        ``promote``: ``None`` promotes when the rule pass did something; the extractor loop
        passes ``True`` after LLM results changed the ranking.
        """
        report = TierReport()
        reasons: Counter[str] = Counter()
        catalog = await self._categories.catalog()
        while limit is None or report.ruled < limit:
            size = self._chunk if limit is None else min(self._chunk, limit - report.ruled)
            done = await self._rule_chunk(catalog, size, report, reasons)
            if done == 0:
                break
        if report.ruled and self._resolve is not None and await self._has_components():
            await self._resolve()
        if promote is None:
            promote = report.ruled > 0
        if promote and self.enabled:
            await self._promote(report, reasons)
        report.reasons = dict(reasons.most_common())
        return report

    async def _has_components(self) -> bool:
        """Resolving before ``benchmarks import`` would store every CPU/GPU text as
        unresolved for the current resolver version, and nothing re-resolves those after the
        import; without a catalogue the texts stay in the resolution backlog instead."""
        async with self._uow() as uow:
            return bool(await uow.components.list_components())

    # ------------------------------------------------------------------ rule pass
    async def _rule_chunk(
        self, catalog: CategoryCatalog, size: int, report: TierReport, reasons: Counter[str]
    ) -> int:
        version = self.version(catalog)
        tiering = self._policy.tiering
        async with self._uow() as uow:
            ids = await uow.extraction_states.rules_backlog(version, limit=size)
            if not ids:
                return 0
            offers = await uow.offers.get_many(ids)
            latest = await uow.extractions.latest_many(ids)
            states = await uow.extraction_states.get_many(ids)
            now = self._clock.now()
            for offer_id in ids:
                offer = offers.get(offer_id)
                if offer is None or offer.content_hash is None:
                    continue
                state = states.get(offer_id) or ExtractionState.new(offer_id, now)
                current = latest.get(offer_id)
                llm_current = (
                    current is not None
                    and current.provenance.model != RULES_MODEL
                    and current.provenance.content_hash == offer.content_hash
                )
                escalate: list[str] = []
                if not llm_current:
                    request = prepare_extraction_input(
                        offer, catalog, max_chars=self._policy.description_max_chars
                    )
                    outcome = self._rules.extract(request)
                    escalate = [r for r in outcome.uncertain if tiering.escalates(r)]
                    if outcome.result is not None:
                        try:
                            extraction = OfferExtraction.validated(
                                offer_id=offer_id,
                                category=outcome.result.category,
                                raw_attributes=outcome.result.attributes,
                                catalog=catalog,
                                model=RULES_MODEL,
                                prompt_version=self._rules.version,
                                content_hash=offer.content_hash,
                                extracted_at=now,
                                notes=outcome.result.notes,
                                catalog_fingerprint=catalog.fingerprint,
                                profile=RULES_PROFILE,
                                provider=RULES_PROFILE,
                            )
                        except InvalidValueError as error:
                            report.notes.append(f"{offer_id}: invalid rule result: {error}")
                            if tiering.escalates(INVALID_REASON):
                                escalate.append(INVALID_REASON)
                        else:
                            await store_extraction(uow, extraction)
                            report.stored += 1
                state.record_rules(offer.content_hash, version, escalate, now)
                await uow.extraction_states.save(state)
                report.ruled += 1
                if escalate:
                    report.escalated += 1
                    reasons.update(escalate)
            await uow.commit()
        return len(ids)

    # ------------------------------------------------------------------ promotion
    async def _promote(self, report: TierReport, reasons: Counter[str]) -> None:
        tiering = self._policy.tiering
        if self._top_offers is None or tiering.top_n == 0:
            return
        tops = await self._top_offers(tiering.top_n, tiering.min_coverage)
        ids = list(dict.fromkeys(i for found in tops.values() for i in found))
        if not ids:
            return
        async with self._uow() as uow:
            offers = await uow.offers.get_many(ids)
            latest = await uow.extractions.latest_many(ids)
            states = await uow.extraction_states.get_many(ids)
            now = self._clock.now()
            promoted: set[OfferId] = set()
            for strategy, found in tops.items():
                reason = f"{TOP_PREFIX}{strategy}"
                for offer_id in found:
                    offer, current = offers.get(offer_id), latest.get(offer_id)
                    state = states.get(offer_id)
                    if (
                        offer is None
                        or offer.content_hash is None
                        or current is None
                        or current.provenance.model != RULES_MODEL
                        or state is None
                        or state.rules_hash != offer.content_hash
                    ):
                        continue  # already LLM-extracted, or the rules are not current
                    if state.escalate(reason, now):
                        reasons[reason] += 1
                        if not state.escalation_reasons[:-1]:  # first reason: newly sent
                            promoted.add(offer_id)
                        await uow.extraction_states.save(state)
            await uow.commit()
        report.promoted += len(promoted)

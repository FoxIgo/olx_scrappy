"""The backlog rule and per-offer extraction state (ADR 0010 sections 2 and 3)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import (
    ExtractionProvenance,
    ExtractionRetryPolicy,
    ExtractionState,
    ExtractionTarget,
    OfferExtraction,
    extraction_due,
    needs_extraction,
)
from scrappy.domain.offer import ContentHash, Offer
from scrappy.domain.shared import InvalidValueError
from tests.unit.builders import T0, at, catalog, details, listing

PROMPT = "p1"


def offer() -> Offer:
    return Offer.from_observation(details("1"), T0)


def extraction(
    of: Offer,
    *,
    fingerprint: str | None = "current",
    prompt: str = PROMPT,
    content_hash: ContentHash | None = None,
    schema_version: int | None = 1,
    category: str = "laptop",
) -> OfferExtraction:
    cat = catalog()
    return OfferExtraction(
        offer_id=of.id,
        category=CategoryName(category),
        attributes={},
        provenance=ExtractionProvenance(
            model="m",
            prompt_version=prompt,
            schema_version=schema_version,
            content_hash=content_hash or of.content_hash or ContentHash("0" * 64),
            extracted_at=T0,
            catalog_fingerprint=cat.fingerprint if fingerprint == "current" else fingerprint,
        ),
    )


class TestNeedsExtraction:
    def test_never_extracted_or_content_changed(self) -> None:
        o = offer()
        assert needs_extraction(o, None, catalog(), PROMPT)
        assert needs_extraction(o, extraction(o, content_hash=ContentHash("f" * 64)), catalog())

    def test_up_to_date(self) -> None:
        o = offer()
        assert not needs_extraction(o, extraction(o), catalog(), PROMPT)

    def test_prompt_version_changed(self) -> None:
        o = offer()
        assert needs_extraction(o, extraction(o, prompt="p0"), catalog(), PROMPT)
        assert not needs_extraction(o, extraction(o, prompt="p0"), catalog())  # not checked

    def test_catalog_fingerprint_changed_even_for_other(self) -> None:
        o = offer()
        current = extraction(o, category="other", schema_version=None)
        assert not needs_extraction(o, current, catalog(), PROMPT)
        assert needs_extraction(o, current, catalog(laptop_version=2), PROMPT)

    def test_legacy_rows_without_fingerprint_keep_the_schema_version_rule(self) -> None:
        o = offer()
        legacy = extraction(o, fingerprint=None)
        assert not needs_extraction(o, legacy, catalog(), PROMPT)
        assert needs_extraction(o, legacy, catalog(laptop_version=2), PROMPT)
        other = extraction(o, fingerprint=None, category="other", schema_version=None)
        assert not needs_extraction(o, other, catalog(laptop_version=2), PROMPT)

    def test_no_content_no_extraction(self) -> None:
        assert not needs_extraction(Offer.from_observation(listing("2"), T0), None, catalog())


class TestRetryPolicy:
    def test_exponential_and_capped(self) -> None:
        policy = ExtractionRetryPolicy(3, timedelta(minutes=1), timedelta(minutes=3))
        assert [policy.delay(n) for n in (1, 2, 3, 4)] == [
            timedelta(minutes=1),
            timedelta(minutes=2),
            timedelta(minutes=3),
            timedelta(minutes=3),
        ]

    def test_validation(self) -> None:
        with pytest.raises(InvalidValueError):
            ExtractionRetryPolicy(max_attempts=0)
        with pytest.raises(InvalidValueError):
            ExtractionRetryPolicy(base_delay=timedelta(hours=2), max_delay=timedelta(hours=1))


class TestExtractionState:
    policy = ExtractionRetryPolicy(3, timedelta(minutes=1), timedelta(hours=1))

    def target(self, of: Offer) -> ExtractionTarget:
        return ExtractionTarget.of(of, catalog(), PROMPT)

    def test_failures_back_off_then_park(self) -> None:
        o = offer()
        state = ExtractionState.new(o.id, T0)
        state.lease("sync:w", at(10), T0)
        state.record_failure(self.target(o), "timeout", at(1), self.policy)
        assert state.lease_owner is None
        assert state.attempts == 1
        assert state.next_attempt_at == at(2)
        assert state.blocks(self.target(o), at(1))
        assert not state.blocks(self.target(o), at(2))
        state.record_failure(self.target(o), "timeout", at(3), self.policy)
        assert state.next_attempt_at == at(5)
        state.record_failure(self.target(o), "bad json", at(6), self.policy)
        assert state.parked
        assert state.next_attempt_at is None
        assert state.blocks(self.target(o), at(10_000))
        assert state.last_error == "bad json"

    def test_a_new_target_voids_old_failures(self) -> None:
        o = offer()
        state = ExtractionState.new(o.id, T0)
        for minute in range(3):
            state.record_failure(self.target(o), "x", at(minute), self.policy)
        assert state.parked
        changed = ExtractionTarget(ContentHash("e" * 64), catalog().fingerprint, PROMPT)
        assert not state.blocks(changed, at(5))  # content changed: parked no more
        state.record_failure(changed, "y", at(6), self.policy)
        assert state.attempts == 1
        assert not state.parked

    def test_success_and_manual_reset(self) -> None:
        o = offer()
        state = ExtractionState.new(o.id, T0)
        state.record_failure(self.target(o), "x", at(1), self.policy)
        state.reset(at(2), force=True, profile="openrouter")
        assert (state.attempts, state.forced, state.requested_profile) == (0, True, "openrouter")
        state.record_success(at(3))
        assert not state.forced
        assert state.requested_profile is None
        assert state.target is None

    def test_lease_expires_by_time(self) -> None:
        state = ExtractionState.new(offer().id, T0)
        state.lease("batch:b1", at(10), T0)
        assert state.is_leased(at(9))
        assert not state.is_leased(at(10))
        with pytest.raises(InvalidValueError):
            state.lease("", at(10), T0)


class TestExtractionDue:
    policy = ExtractionRetryPolicy(2, timedelta(minutes=1), timedelta(hours=1))

    def test_the_rule_combines_staleness_lease_backoff_parking_and_force(self) -> None:
        o = offer()
        cat = catalog()
        assert extraction_due(o, None, None, cat, PROMPT, T0)
        current = extraction(o)
        assert not extraction_due(o, current, None, cat, PROMPT, T0)

        state = ExtractionState.new(o.id, T0)
        state.lease("sync:w", at(5), T0)
        assert not extraction_due(o, None, state, cat, PROMPT, at(1))  # leased
        assert extraction_due(o, None, state, cat, PROMPT, at(5))  # lease expired

        target = ExtractionTarget.of(o, cat, PROMPT)
        state.record_failure(target, "x", at(5), self.policy)
        assert not extraction_due(o, None, state, cat, PROMPT, at(5))  # backoff
        assert extraction_due(o, None, state, cat, PROMPT, at(6))
        state.record_failure(target, "x", at(6), self.policy)
        assert not extraction_due(o, None, state, cat, PROMPT, at(10_000))  # parked
        assert extraction_due(o, None, state, catalog(laptop_version=2), PROMPT, at(7))

        forced = ExtractionState.new(o.id, T0)
        forced.reset(T0, force=True)
        assert extraction_due(o, current, forced, cat, PROMPT, T0)  # up to date, but forced

"""Scoring maths: transforms, cap, log, coverage, missing terms, enum maps, booleans."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from scrappy.domain.category import AttributeSpec, AttributeType, Category, CategoryName
from scrappy.domain.scoring import (
    Strategy,
    Term,
    Transform,
    parse_component_fact,
    score_offer,
    validate_against_category,
)
from scrappy.domain.shared import InvalidValueError

GPU = "gpu.blender_open_data.samples_per_minute"
LAPTOP = CategoryName("laptop")


def term(
    fact: str,
    weight: float,
    baseline: float = 1,
    *,
    cap: float | None = None,
    transform: Transform = Transform.LINEAR,
    value_map: tuple[tuple[str, float], ...] | None = None,
) -> Term:
    return Term(fact, fact, weight, baseline, cap, transform, value_map)


def strategy(*terms: Term) -> Strategy:
    return Strategy("s", LAPTOP, terms)


def test_linear_term_is_weight_times_ratio_to_baseline() -> None:
    result = score_offer(strategy(term("ram_gb", 0.4, 16)), {"ram_gb": 8})
    assert result.performance == pytest.approx(0.2)
    assert result.coverage == 1.0


def test_value_equal_to_baseline_gives_the_full_weight_for_both_transforms() -> None:
    linear = score_offer(strategy(term("ram_gb", 0.5, 16)), {"ram_gb": 16})
    log = score_offer(strategy(term("ram_gb", 0.5, 16, transform=Transform.LOG)), {"ram_gb": 16})
    assert linear.performance == pytest.approx(0.5)
    assert log.performance == pytest.approx(0.5)


def test_log_transform_has_diminishing_returns() -> None:
    t = term("ram_gb", 1, 16, transform=Transform.LOG)
    at_32 = score_offer(strategy(t), {"ram_gb": 32}).performance
    assert at_32 == pytest.approx(math.log2(1 + 2))
    assert at_32 < 2  # 32 GB is not twice as good as 16 GB
    assert score_offer(strategy(t), {"ram_gb": 0}).performance == 0


def test_cap_limits_the_fact_before_the_transform() -> None:
    t = term("ram_gb", 1, 16, cap=32)
    assert score_offer(strategy(t), {"ram_gb": 128}).performance == pytest.approx(2.0)


def test_missing_terms_add_nothing_and_lower_coverage_without_renormalising() -> None:
    s = strategy(term(GPU, 0.6, 100), term("ram_gb", 0.4, 16))
    full = score_offer(s, {GPU: 100.0, "ram_gb": 16})
    partial = score_offer(s, {"ram_gb": 16})
    assert full.performance == pytest.approx(1.0)
    assert full.coverage == pytest.approx(1.0)
    assert partial.performance == pytest.approx(0.4)  # not rescaled to 1.0
    assert partial.coverage == pytest.approx(0.4)
    assert [t.present for t in partial.terms] == [False, True]
    assert partial.terms[0].points is None


def test_nothing_known_scores_zero_with_zero_coverage() -> None:
    result = score_offer(strategy(term("ram_gb", 1, 16)), {"ram_gb": None})
    assert (result.performance, result.coverage) == (0.0, 0.0)


def test_booleans_are_one_and_zero_and_false_still_counts_as_known() -> None:
    s = strategy(term("ram_upgradeable", 0.5), term("ram_gb", 0.5, 16))
    yes = score_offer(s, {"ram_upgradeable": True, "ram_gb": 16})
    no = score_offer(s, {"ram_upgradeable": False, "ram_gb": 16})
    assert yes.performance == pytest.approx(1.0)
    assert no.performance == pytest.approx(0.5)
    assert no.coverage == 1.0


def test_enum_values_go_through_the_map_and_unmapped_values_are_missing() -> None:
    mapped = term("storage_type", 1, 1, value_map=(("ssd", 1.0), ("hdd", 0.3)))
    s = strategy(mapped)
    assert score_offer(s, {"storage_type": "hdd"}).performance == pytest.approx(0.3)
    assert score_offer(s, {"storage_type": "ssd"}).performance == pytest.approx(1.0)
    assert score_offer(s, {"storage_type": "tape"}).coverage == 0


def test_decimals_and_non_numeric_text() -> None:
    s = strategy(term("screen_in", 1, 15.6), term("gpu", 1, 1))
    result = score_offer(s, {"screen_in": Decimal("15.6"), "gpu": "RTX"})
    assert result.terms[0].points == pytest.approx(1.0)
    assert result.terms[1].points is None  # text is not a number: missing


def test_negative_facts_are_clamped_to_zero() -> None:
    assert score_offer(strategy(term("ram_gb", 1, 16)), {"ram_gb": -5}).performance == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"weight": 0, "baseline": 1}, "weight"),
        ({"weight": -1, "baseline": 1}, "weight"),
        ({"weight": 1, "baseline": 0}, "baseline"),
        ({"weight": 1, "baseline": 1, "cap": 0}, "cap"),
        ({"weight": 1, "baseline": 1, "value_map": (("a", -1.0),)}, "map"),
    ],
)
def test_term_rejects_bad_numbers(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidValueError, match=message):
        Term("x", "x", **kwargs)  # type: ignore[arg-type]


def test_strategy_needs_terms_and_unique_facts() -> None:
    with pytest.raises(InvalidValueError, match="at least one"):
        Strategy("s", LAPTOP, ())
    with pytest.raises(InvalidValueError, match="twice"):
        strategy(term("ram_gb", 1, 1), term("ram_gb", 2, 1))


def test_component_fact_names_and_aliases() -> None:
    ref = parse_component_fact("gpu.blender")
    assert ref is not None
    assert ref.key == GPU
    assert parse_component_fact(GPU) == ref
    assert parse_component_fact("ram_gb") is None
    for bad in ("gpu.nope", "gpu.blender.speed", "ram.blender", "gpu.blender.samples_per_minute.x"):
        with pytest.raises(InvalidValueError):
            parse_component_fact(bad)


CATEGORY = Category(
    LAPTOP,
    1,
    (
        AttributeSpec("gpu", AttributeType.STRING),
        AttributeSpec("ram_gb", AttributeType.INTEGER),
        AttributeSpec("ram_upgradeable", AttributeType.BOOLEAN),
        AttributeSpec("storage_type", AttributeType.ENUM, values=("ssd", "hdd")),
    ),
)


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (term("vram_gb", 1, 1), "unknown fact 'vram_gb'"),
        (term("gpu", 1, 1), "text, not a number"),
        (term("storage_type", 1, 1), "enum"),
        (term("storage_type", 1, 1, value_map=(("ssd", 1.0),)), "missing"),
        (term("storage_type", 1, 1, value_map=(("ssd", 1.0), ("hdd", 0), ("x", 1))), "lacks"),
        (term("ram_gb", 1, 1, value_map=(("a", 1.0),)), "only applies to enum"),
        (term("cpu.blender_open_data.samples_per_minute", 1, 1), "no 'cpu' attribute"),
    ],
)
def test_validation_against_the_category(bad: Term, message: str) -> None:
    with pytest.raises(InvalidValueError, match=message):
        validate_against_category(strategy(bad), CATEGORY)


def test_valid_strategy_passes_validation() -> None:
    ok = strategy(
        term(GPU, 1, 100),
        term("ram_gb", 1, 16),
        term("ram_upgradeable", 1),
        term("storage_type", 1, 1, value_map=(("ssd", 1.0), ("hdd", 0.3))),
    )
    validate_against_category(ok, CATEGORY)

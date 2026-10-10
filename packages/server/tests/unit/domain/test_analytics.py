from __future__ import annotations

from decimal import Decimal

import pytest

from scrappy.domain.analytics import (
    DealCandidate,
    count_facet,
    find_deals,
    median,
    percentile,
    summarize,
)
from scrappy.domain.shared import InvalidValueError

D = Decimal


def test_percentile_interpolates_linearly() -> None:
    values = [D(1), D(2), D(3), D(4)]
    assert percentile(values, D("0")) == D(1)
    assert percentile(values, D("1")) == D(4)
    assert percentile(values, D("0.5")) == D("2.5")
    assert percentile(values, D("0.25")) == D("1.75")  # position 0.75 between 1 and 2
    assert percentile([D(7)], D("0.9")) == D(7)


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(InvalidValueError):
        percentile([], D("0.5"))
    with pytest.raises(InvalidValueError):
        percentile([D(1)], D("1.5"))


def test_summarize() -> None:
    assert summarize([]) is None
    summary = summarize([D(1000), D(3000), D(2000), D(4000), D(10)])
    assert summary is not None
    assert (summary.n, summary.minimum, summary.maximum) == (5, D(10), D(4000))
    assert summary.median == D("2000.00")
    assert summary.p25 == D("1000.00")
    assert summary.p75 == D("3000.00")
    assert summary.mean == D("2002.00")


def test_median_even() -> None:
    assert median([D(10), D(20)]) == D(15)


def _cand(i: str, price: str, ram: int | None, gpu: str | None = "GTX", cur: str = "PLN"):
    return DealCandidate(i, D(price), cur, {"ram_gb": ram, "gpu": gpu})


def test_deals_found_with_group_median_and_ratio() -> None:
    cands = [_cand(str(i), p, 16) for i, p in enumerate(["1000", "1000", "1000", "1000", "500"])]
    report = find_deals(cands, ["ram_gb"], min_group=5, max_ratio=D("0.8"))
    assert [d.candidate.offer_id for d in report.deals] == ["4"]
    deal = report.deals[0]
    assert deal.group_median == D(1000)
    assert deal.ratio == D("0.5")
    assert deal.group_size == 5
    assert "50%" in deal.reason
    assert "ram_gb=16" in deal.reason


def test_deals_exclude_missing_small_groups_and_split_currency() -> None:
    cands = [_cand(str(i), "1000", 16) for i in range(5)]
    cands += [_cand("cheap", "100", 16)]
    cands += [_cand("nogroup", "1", None)]
    cands += [_cand("eur", "10", 16, cur="EUR")]
    cands += [_cand(f"s{i}", "10", 8) for i in range(2)]  # group of 2 < min_group
    report = find_deals(cands, ["ram_gb"])
    assert report.excluded_missing == 1
    assert report.small_groups == 2
    assert report.small_group_offers == 3
    assert len(report.mixed_currency_keys) == 1
    assert [d.candidate.offer_id for d in report.deals] == ["cheap"]


def test_deals_group_strings_case_insensitively_and_ints_with_decimals() -> None:
    cands = [
        DealCandidate(str(i), D(1000), "PLN", {"gpu": "gtx" if i % 2 else "GTX"}) for i in range(4)
    ]
    cands.append(DealCandidate("x", D(100), "PLN", {"gpu": "Gtx"}))
    report = find_deals(cands, ["gpu"], min_group=5)
    assert [d.candidate.offer_id for d in report.deals] == ["x"]
    nums = [DealCandidate(str(i), D(10), "PLN", {"n": 16 if i else D("16.0")}) for i in range(5)]
    assert find_deals(nums, ["n"]).compared == 5


def test_deals_validate_parameters() -> None:
    with pytest.raises(InvalidValueError):
        find_deals([], ["a"], min_group=1)
    with pytest.raises(InvalidValueError):
        find_deals([], ["a"], max_ratio=D(2))


def test_facet_counts_values_nulls_and_buckets() -> None:
    facet = count_facet(["a", "b", "a", None, "a", "b"])
    assert facet.values == (("a", 3), ("b", 2))
    assert facet.null_count == 1
    assert facet.total == 6
    assert facet.numeric is None

    numbers = count_facet([8, 16, 16, 32, None, 8], buckets=3)
    assert numbers.numeric is not None
    assert (numbers.numeric.minimum, numbers.numeric.maximum) == (D(8), D(32))
    assert sum(b.count for b in numbers.numeric.buckets) == 5
    assert numbers.numeric.buckets[-1].count == 1  # 32 lands in the last bucket

    single = count_facet([5, 5])
    assert single.numeric is not None
    assert len(single.numeric.buckets) == 1


def test_facet_counts_each_list_element() -> None:
    facet = count_facet([("screen", "hinge"), ("screen",), None])
    assert facet.values == (("screen", 2), ("hinge", 1))
    assert (facet.total, facet.null_count) == (3, 1)


def test_facet_booleans_are_not_numeric() -> None:
    assert count_facet([True, False, True]).numeric is None

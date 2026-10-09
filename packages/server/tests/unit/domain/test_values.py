from datetime import datetime
from decimal import Decimal

import pytest

from scrappy.domain.offer import (
    ContentHash,
    OfferId,
    Params,
    Price,
    PriceKind,
    compute_content_hash,
)
from scrappy.domain.shared import InvalidValueError, Money, RunId, SourceId, require_aware


class TestMoney:
    def test_decimal_amount(self) -> None:
        assert Money.of("1299.99", "PLN").amount == Decimal("1299.99")

    @pytest.mark.parametrize(
        ("amount", "currency"),
        [(Decimal("-1"), "PLN"), (Decimal("1"), "pln"), (Decimal("NaN"), "PLN")],
    )
    def test_invalid(self, amount: Decimal, currency: str) -> None:
        with pytest.raises(InvalidValueError):
            Money(amount, currency)

    def test_float_rejected(self) -> None:
        with pytest.raises(InvalidValueError):
            Money(1.5, "PLN")  # type: ignore[arg-type]

    def test_equal_regardless_of_exponent(self) -> None:
        assert Money.of("100", "PLN") == Money.of("100.00", "PLN")


class TestIdentifiers:
    def test_source_id_must_be_slug(self) -> None:
        assert str(SourceId("olx_pl")) == "olx_pl"
        with pytest.raises(InvalidValueError):
            SourceId("OLX PL")

    def test_offer_id_round_trip(self) -> None:
        offer_id = OfferId(SourceId("olx_pl"), "1098526767")
        assert str(offer_id) == "olx_pl:1098526767"
        assert OfferId.parse(str(offer_id)) == offer_id

    def test_offer_id_external_id_may_contain_colons(self) -> None:
        assert OfferId.parse("allegro_pl:a:b").external_id == "a:b"

    def test_offer_id_invalid(self) -> None:
        with pytest.raises(InvalidValueError):
            OfferId.parse("no-separator")
        with pytest.raises(InvalidValueError):
            OfferId(SourceId("olx_pl"), " 1")

    def test_run_id_rejects_colon(self) -> None:
        with pytest.raises(InvalidValueError):
            RunId("a:b")

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(InvalidValueError):
            require_aware(datetime(2026, 1, 1), "x")


class TestPrice:
    def test_fixed(self) -> None:
        price = Price.fixed(1300, negotiable=True)
        assert price.kind is PriceKind.FIXED
        assert price.amount == Money.of(1300, "PLN")

    def test_exchange_and_free_have_no_amount(self) -> None:
        assert Price.exchange().amount is None
        assert Price.free().kind is PriceKind.FREE
        with pytest.raises(InvalidValueError):
            Price(PriceKind.EXCHANGE, Money.of(0, "PLN"))

    def test_fixed_needs_amount(self) -> None:
        with pytest.raises(InvalidValueError):
            Price(PriceKind.FIXED)

    def test_negotiable_is_part_of_equality(self) -> None:
        assert Price.fixed(100) != Price.fixed(100, negotiable=True)


class TestParams:
    def test_of_sorts_and_equality_ignores_insertion_order(self) -> None:
        assert Params.of({"b": "2", "a": "1"}) == Params.of({"a": "1", "b": "2"})
        assert Params.of({"b": "2", "a": "1"}).items == (("a", "1"), ("b", "2"))

    def test_unsorted_items_rejected(self) -> None:
        with pytest.raises(InvalidValueError):
            Params((("b", "2"), ("a", "1")))


class TestContentHash:
    def test_known_value_is_stable(self) -> None:
        # Golden value: changing it invalidates every stored hash (re-extracts everything).
        value = compute_content_hash("Laptop", "Opis", Params.of({"state": "used"}))
        assert value == ContentHash(GOLDEN_HASH)

    def test_param_order_does_not_matter(self) -> None:
        a = compute_content_hash("t", "d", Params.of({"x": "1", "y": "2"}))
        b = compute_content_hash("t", "d", Params.of({"y": "2", "x": "1"}))
        assert a == b

    @pytest.mark.parametrize(
        ("title", "description", "params"),
        [
            ("other", "d", {"x": "1"}),
            ("t", "other", {"x": "1"}),
            ("t", "d", {"x": "2"}),
        ],
    )
    def test_any_content_change_changes_hash(
        self, title: str, description: str, params: dict[str, str]
    ) -> None:
        base = compute_content_hash("t", "d", Params.of({"x": "1"}))
        assert compute_content_hash(title, description, Params.of(params)) != base

    def test_none_params_equal_empty(self) -> None:
        assert compute_content_hash("t", "d", None) == compute_content_hash("t", "d", Params())

    def test_invalid_hash_rejected(self) -> None:
        with pytest.raises(InvalidValueError):
            ContentHash("xyz")


GOLDEN_HASH = "858ae883188324a2485cac35bd9d090c4ef0814d82acde6d26afb758716ccd9d"

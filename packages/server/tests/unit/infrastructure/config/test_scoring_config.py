"""``config/scoring.yaml`` -> strategies, validated against the category catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scrappy.application.use_cases.list_offers import typed_predicates
from scrappy.domain.category import CategoryCatalog, CategoryName
from scrappy.domain.scoring import Transform
from scrappy.infrastructure.config.categories import load_categories
from scrappy.infrastructure.config.errors import ConfigError
from scrappy.infrastructure.config.scoring import load_scoring, parse_scoring

REPO = Path(__file__).resolve().parents[4] / "config"
PATH = Path("scoring.yaml")


@pytest.fixture(scope="module")
def catalog() -> CategoryCatalog:
    return load_categories(REPO / "categories.yaml")


def strategy(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "category": "laptop",
        "filters": ["ram_gb>=8"],
        "terms": {"gpu.blender": {"weight": 1, "baseline": 2000}},
    }
    return {"strategies": {"s": {**base, **overrides}}}


def test_shipped_scoring_yaml_is_valid_against_shipped_categories(catalog: CategoryCatalog) -> None:
    strategies = load_scoring(REPO / "scoring.yaml", catalog)
    assert {"gaming", "work", "balanced", "battery", "repair"} <= set(strategies)
    for item in strategies.values():
        assert item.total_weight == pytest.approx(1.0), item.name


def test_parses_terms_aliases_defaults_and_filters(catalog: CategoryCatalog) -> None:
    data = strategy(
        terms={
            "gpu.blender": {"weight": 0.5, "baseline": 2000, "transform": "log"},
            "ram_gb": {"weight": 0.2, "baseline": 16, "cap": 32},
            "ram_upgradeable": {"weight": 0.1},
            "storage_type": {"weight": 0.2, "map": {"ssd": 1, "hdd": 0.3, "emmc": 0.2}},
        }
    )
    (parsed,) = parse_scoring(data, catalog=catalog, path=PATH).values()
    gpu, ram, upgradeable, storage = parsed.terms
    assert gpu.fact == "gpu.blender_open_data.samples_per_minute"
    assert gpu.name == "gpu.blender"
    assert gpu.transform is Transform.LOG
    assert (ram.cap, ram.transform) == (32, Transform.LINEAR)
    assert upgradeable.baseline == 1  # boolean default
    assert storage.baseline == 1
    assert storage.value_map is not None  # map default
    assert [f"{p.attribute}{p.op.value}{p.value}" for p in parsed.filters] == ["ram_gb>=8"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (strategy(terms={"nope_gb": {"weight": 1, "baseline": 1}}), "unknown fact 'nope_gb'"),
        (strategy(terms={"ram_gb": {"weight": 0, "baseline": 1}}), "weight"),
        (strategy(terms={"ram_gb": {"weight": 1, "baseline": 0}}), "baseline"),
        (strategy(terms={"ram_gb": {"weight": 1}}), "baseline is required"),
        (strategy(terms={"gpu.nowhere": {"weight": 1, "baseline": 1}}), "unknown benchmark source"),
        (strategy(terms={"cpu.blender.speed": {"weight": 1, "baseline": 1}}), "unknown metric"),
        (strategy(terms={"storage_type": {"weight": 1}}), "is an enum"),
        (strategy(terms={"storage_type": {"weight": 1, "map": {"ssd": 1}}}), "missing"),
        (strategy(terms={"gpu": {"weight": 1, "baseline": 1}}), "text, not a number"),
        (
            strategy(terms={"ram_gb": {"weight": 1, "baseline": 1, "transform": "sqrt"}}),
            "transform",
        ),
        (strategy(terms={"ram_gb": {"weight": 1, "baseline": 1, "speed": 3}}), "speed"),
        (strategy(terms={}), "terms"),
        (strategy(category="tv"), "unknown category"),
        (strategy(filters=["colour=red"]), "colour"),
        (strategy(filters=["ram_gb 8"]), "cannot parse filter"),
        (strategy(filters=["gpu>=big"]), "numeric attribute"),
        (strategy(filters=["damage=screen"]), "is a list"),
        (strategy(filters=["damage!~keyboard_x"]), "not one of"),
        (strategy(terms={"damage": {"weight": 1, "baseline": 1}}), "is a list"),
        ({"strategies": {"s": {"category": "laptop"}}}, "terms"),
    ],
)
def test_invalid_strategies_are_clear_config_errors(
    catalog: CategoryCatalog, data: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigError, match=message) as error:
        parse_scoring(data, catalog=catalog, path=PATH)
    assert "scoring.yaml" in str(error.value)


def test_filters_may_use_pseudo_fields(catalog: CategoryCatalog) -> None:
    data = strategy(filters=["price>=300", "title~acer"])
    (parsed,) = parse_scoring(data, catalog=catalog, path=PATH).values()
    assert len(parsed.filters) == 2


def test_empty_file_means_no_strategies(catalog: CategoryCatalog, tmp_path: Path) -> None:
    path = tmp_path / "scoring.yaml"
    path.write_text("", encoding="utf-8")
    assert load_scoring(path, catalog) == {}
    path.write_text(yaml.safe_dump(strategy()), encoding="utf-8")
    assert list(load_scoring(path, catalog)) == ["s"]


def test_missing_file_is_a_config_error(catalog: CategoryCatalog, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_scoring(tmp_path / "scoring.yaml", catalog)


def passes(name: str, attributes: dict[str, object], catalog: CategoryCatalog) -> bool:
    """Do the strategy's attribute filters accept this offer? (price filters are skipped)"""
    strategies = load_scoring(REPO / "scoring.yaml", catalog)
    category = catalog.get(CategoryName("laptop"))
    assert category is not None
    wanted = tuple(p for p in strategies[name].filters if p.attribute != "price")
    return all(p.matches(attributes) for p in typed_predicates(category, wanted))  # type: ignore[arg-type]


def laptop(**attrs: object) -> dict[str, object]:
    return {"ram_gb": 16, "condition": "used", **attrs}


@pytest.mark.parametrize("name", ["gaming", "work", "balanced", "battery"])
def test_regular_strategies_exclude_damaged_and_for_parts(
    name: str, catalog: CategoryCatalog
) -> None:
    assert passes(name, laptop(), catalog)
    assert not passes(name, laptop(condition="damaged"), catalog)
    assert not passes(name, laptop(condition="for_parts"), catalog)


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (laptop(condition="damaged", damage=("screen",)), True),
        (laptop(condition="damaged", damage=("screen", "battery", "charger_missing")), True),
        (laptop(condition="damaged", damage=("screen", "motherboard")), False),
        (laptop(condition="damaged", damage=("gpu",)), False),
        (laptop(condition="damaged", damage=("no_power",)), False),
        (laptop(condition="damaged", damage=("liquid_damage",)), False),
        (laptop(condition="damaged", damage=("bios_locked",)), False),
        (laptop(condition="damaged", damage=("unknown",)), False),
        (laptop(condition="damaged"), False),  # damaged but nothing stated: a risk
        (laptop(condition="used", damage=("screen",)), False),
        (laptop(condition="new", damage=("screen",)), False),
        # the seller's "na części" label is not trusted: a fixable fault is still fixable
        (laptop(condition="for_parts", damage=("screen",)), True),
        (laptop(condition="for_parts", damage=("storage_missing", "ram_missing")), True),
        (laptop(condition="for_parts", damage=("motherboard",)), False),
        # no RAM floor: RAM is cheap to add, it only lowers the score
        (laptop(condition="damaged", damage=("keyboard",), ram_gb=4), True),
    ],
)
def test_repair_strategy_wants_fixable_damage(
    attributes: dict[str, object], expected: bool, catalog: CategoryCatalog
) -> None:
    assert passes("repair", attributes, catalog) is expected


def test_repair_keeps_cheap_offers_but_not_placeholders(catalog: CategoryCatalog) -> None:
    repair = load_scoring(REPO / "scoring.yaml", catalog)["repair"]
    (price,) = [p for p in repair.filters if p.attribute == "price"]
    assert (price.op.value, price.value) == (">=", "100")

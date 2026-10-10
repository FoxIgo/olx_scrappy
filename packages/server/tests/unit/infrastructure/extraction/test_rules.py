"""Rule-based extraction (ADR 0012 tier 0) against the real ``config/categories.yaml``.

Titles and phrasings come from stored olx_pl offers.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from scrappy.application.ports.extractor import RULES_MODEL, ExtractionInput, RuleExtraction
from scrappy.domain.category import OTHER_CATEGORY, CategoryCatalog
from scrappy.domain.offer import ContentHash, Price
from scrappy.infrastructure.config.categories import load_categories
from scrappy.infrastructure.extraction.rules import RULES_VERSION, RuleBasedExtractor, Uncertain
from scrappy.infrastructure.extraction.rules.olx_params import bounds
from tests.unit.builders import LAPTOP, oid

CATEGORIES = Path(__file__).parents[4] / "config" / "categories.yaml"
USED = {"state": "Używane"}


@pytest.fixture(scope="module")
def catalog() -> CategoryCatalog:
    return load_categories(CATEGORIES)


def run(
    catalog: CategoryCatalog,
    title: str,
    description: str = "",
    params: dict[str, str] | None = None,
    price: Price | None = None,
) -> RuleExtraction:
    request = ExtractionInput(
        offer_id=oid("1"),
        content_hash=ContentHash("0" * 64),
        title=title,
        description=description,
        description_truncated=False,
        params=tuple(sorted((params if params is not None else USED).items())),
        price=price if price is not None else Price.fixed(1000),
        categories=tuple(catalog),
    )
    return RuleBasedExtractor().extract(request)


def attributes(outcome: RuleExtraction) -> dict[str, object]:
    assert outcome.result is not None
    return dict(outcome.result.attributes)


# ---------------------------------------------------------------------------- specs


def test_spec_list_title(catalog: CategoryCatalog) -> None:
    outcome = run(
        catalog,
        "Lenovo ThinkPad L490 / i5-8265U / 8GB-DDR4 / SSD-256GB NVME / FHD-IPS / Windows 11",
    )

    assert outcome.uncertain == ()
    assert outcome.result is not None
    assert outcome.result.category == LAPTOP
    assert outcome.result.model == RULES_MODEL
    assert outcome.result.prompt_version == RULES_VERSION
    assert attributes(outcome) == {
        "condition": "used",
        "damage": [],
        "cpu": "i5-8265U",
        "ram_gb": 8,
        "storage_gb": 256,
        "storage_type": "ssd",
        "resolution": "1920x1080",
    }


def test_slash_shorthand_ram_and_storage(catalog: CategoryCatalog) -> None:
    found = attributes(run(catalog, "Laptop Dell 7490 i5-8350U/8GB/256GB zasilacz"))

    assert (found["cpu"], found["ram_gb"], found["storage_gb"]) == ("i5-8350U", 8, 256)


def test_ram_word_is_not_reused_for_the_storage_size(catalog: CategoryCatalog) -> None:
    found = attributes(run(catalog, "MacBook Air i5 1.8GHz 8GB RAM 128GB SSD"))

    assert (found["ram_gb"], found["storage_gb"]) == (8, 128)


def test_ssd_and_hdd_add_up_and_sizes_bind_to_the_word_after_them(
    catalog: CategoryCatalog,
) -> None:
    found = attributes(run(catalog, "Lenovo IdeaPad 700 I5 8gb RAM 1tb HDD 240gb SSD"))

    assert (found["storage_gb"], found["storage_type"]) == (1240, "ssd")


def test_screen_refresh_gpu_and_vram(catalog: CategoryCatalog) -> None:
    found = attributes(run(catalog, 'Lenovo Legion 5 15,6" 144Hz Ryzen 7 5800H RTX 3060 6GB'))

    assert found["screen_in"] == Decimal("15.6")
    assert found["refresh_hz"] == 144
    assert found["cpu"] == "Ryzen 7 5800H"
    assert (found["gpu"], found["vram_gb"]) == ("RTX 3060", 6)


def test_split_intel_suffix_and_old_mobile_gpus(catalog: CategoryCatalog) -> None:
    found = attributes(
        run(
            catalog,
            "Laptop Lenovo Y510P",
            "Procesor: Intel Core i7-4700 MQ\nGrafika: GeForce GT 750M",
        )
    )

    assert (found["cpu"], found["gpu"]) == ("i7-4700MQ", "GT 750M")


def test_apple_chip_only_in_apple_context(catalog: CategoryCatalog) -> None:
    assert attributes(run(catalog, "MacBook Air M1 8GB 256GB SSD"))["cpu"] == "M1"
    assert "cpu" not in attributes(run(catalog, "Laptop Dell dysk SSD M2 512GB 16GB RAM"))


def test_integrated_gpu_when_nothing_dedicated(catalog: CategoryCatalog) -> None:
    found = attributes(
        run(catalog, "HP Pavilion 14", "Karta graficzna: Zintegrowana (Intel UHD Graphics 620)")
    )

    assert found["gpu"] == "Intel UHD Graphics 620"


def test_a_value_outside_the_site_range_is_dropped(catalog: CategoryCatalog) -> None:
    outcome = run(catalog, "Laptop HP 16GB RAM", params={**USED, "ramsize_laptops": "Do 4GB"})

    assert "ram_gb" not in attributes(outcome)
    assert Uncertain.RAM_CONFLICT in outcome.uncertain


def test_neighbouring_bucket_is_tolerated(catalog: CategoryCatalog) -> None:
    found = attributes(
        run(catalog, "Lenovo L480 128GB SSD", params={**USED, "disksize_laptops": "129GB - 256GB"})
    )

    assert found["storage_gb"] == 128


def test_two_different_values_are_not_guessed(catalog: CategoryCatalog) -> None:
    outcome = run(catalog, "Laptop Asus", "Mam dwie sztuki: jedna 8GB RAM, druga 16 GB RAM.")

    assert "ram_gb" not in attributes(outcome)
    assert Uncertain.RAM_CONFLICT in outcome.uncertain


def test_upgrade_limit_is_the_maximum_not_a_second_value(catalog: CategoryCatalog) -> None:
    outcome = run(catalog, "Laptop Asus", "RAM 8GB, możliwość rozbudowy do 16 GB RAM.")

    found = attributes(outcome)
    assert (found["ram_gb"], found["max_ram_gb"]) == (8, 16)
    assert outcome.uncertain == ()


# ---------------------------------------------------------------------------- condition


def test_damaged_offer_goes_to_the_llm_with_its_damage(catalog: CategoryCatalog) -> None:
    outcome = run(
        catalog,
        "Lenovo ideapad 3 - pęknięta matryca",
        "Laptop do naprawy, pęknięta matryca, reszta sprawna.",
        params={"state": "Uszkodzone"},
    )

    found = attributes(outcome)
    assert (found["condition"], found["damage"]) == ("damaged", ["screen"])
    assert outcome.uncertain == (Uncertain.DAMAGED,)


def test_negated_damage_is_not_damage(catalog: CategoryCatalog) -> None:
    outcome = run(
        catalog,
        "Laptop Lenovo G700",
        "Matryca jest w pełni sprawna, nie uszkodzona. Laptop normalnie się uruchamia.",
    )

    assert attributes(outcome)["damage"] == []
    assert outcome.uncertain == ()


def test_damage_words_in_a_used_offer_are_unclear(catalog: CategoryCatalog) -> None:
    outcome = run(catalog, "Dell Inspiron 13", "Bateria do wymiany, poza tym ok.")

    found = attributes(outcome)
    assert "condition" not in found
    assert found["damage"] == ["battery"]
    assert outcome.uncertain == (Uncertain.DAMAGE_UNCLEAR,)


def test_only_missing_parts_keep_a_used_offer_used(catalog: CategoryCatalog) -> None:
    outcome = run(
        catalog,
        "Laptop Dell Latitude 5490 bez dysku",
        params={**USED, "harddisktype_laptops": "Brak"},
    )

    found = attributes(outcome)
    assert (found["condition"], found["damage"]) == ("used", ["storage_missing"])
    assert outcome.uncertain == ()


# ---------------------------------------------------------------------------- GPU checks


def test_dedicated_gpu_without_a_model_is_unsure_only_when_the_text_talks_about_it(
    catalog: CategoryCatalog,
) -> None:
    dedicated = {**USED, "graphicscardtype_laptops": "Dedykowana"}

    talks = run(catalog, "Laptop Lenovo intel core i5 Nvidia", params=dedicated)
    silent = run(catalog, "Laptop Asus X751L 8GB RAM", params=dedicated)

    assert Uncertain.GPU_MISSING in talks.uncertain
    assert Uncertain.GPU_MISSING not in silent.uncertain


# ---------------------------------------------------------------------------- junk


@pytest.mark.parametrize(
    "title",
    [
        "Zasilacz do laptopa Dell 65W",
        "Matryca do laptopa Lenovo 15,6",
        "Tablet Lenovo TB-X606F",
        "SUPER tablet Samsung A11. Ekran 8.7 cala. Pamięć 4/64gb.",
        "Pamięć PC4 32 GB; 2x PC4-21300 DDR4 16GB",
    ],
)
def test_accessories_and_other_devices_are_other(catalog: CategoryCatalog, title: str) -> None:
    outcome = run(catalog, title)

    assert outcome.result is not None
    assert outcome.result.category == OTHER_CATEGORY
    assert outcome.result.attributes == {}


@pytest.mark.parametrize(
    "title",
    [
        "Laptop Dell 7490 i5-8350U/8GB/256GB zasilacz",
        "Lenovo MIIX 520-12IKB - 2w1 (laptop + tablet)",
        "Bateria nowa, laptop Dell E7470",
    ],
)
def test_laptops_with_accessory_words_stay_laptops(catalog: CategoryCatalog, title: str) -> None:
    outcome = run(catalog, title)

    assert outcome.result is not None
    assert outcome.result.category == LAPTOP


def test_suspiciously_cheap_offers_are_left_to_the_llm(catalog: CategoryCatalog) -> None:
    outcome = run(catalog, "Laptop Dell i5 8GB", price=Price.fixed(20))

    assert outcome.result is None
    assert outcome.uncertain == (Uncertain.CHEAP,)


def test_nothing_found_is_empty(catalog: CategoryCatalog) -> None:
    outcome = run(catalog, "Laptopy używane w najlepszych cenach!", params={})

    assert outcome.result is None
    assert outcome.uncertain == (Uncertain.EMPTY,)


def test_no_rule_set_for_the_catalog() -> None:
    outcome = run(CategoryCatalog.of([]), "Laptop Dell i5 8GB")

    assert outcome.result is None
    assert outcome.uncertain == (Uncertain.NO_RULES,)


# ---------------------------------------------------------------------------- params


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6GB - 12GB", (Decimal(6), Decimal(12))),
        ("Do 4GB", (None, Decimal(4))),
        ("128GB i więcej", (Decimal(128), None)),
        ("1TB", (Decimal(1000), Decimal(1000))),
        ('15-15,9"', (Decimal(15), Decimal("15.99"))),
        ('Poniżej 11"', (None, Decimal(11))),
        ("Inna", None),
    ],
)
def test_param_bounds(raw: str, expected: tuple[Decimal | None, Decimal | None] | None) -> None:
    assert bounds(raw) == expected

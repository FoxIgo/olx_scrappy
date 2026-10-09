"""ComponentMatcher: realistic Polish-marketplace strings against a small Blender-like catalog."""

from __future__ import annotations

import pytest

from scrappy.domain.component import (
    Component,
    ComponentAlias,
    ComponentKind,
    ComponentMatcher,
    Resolution,
    ResolutionMethod,
)

GPU = ComponentKind.GPU
CPU = ComponentKind.CPU

GPU_NAMES = [
    "NVIDIA GeForce RTX 4060",
    "NVIDIA GeForce RTX 4060 Laptop GPU",
    "NVIDIA GeForce RTX 3050 Laptop GPU",
    "NVIDIA GeForce RTX 3050 6GB Laptop GPU",
    "NVIDIA GeForce RTX 3050 Ti Laptop GPU",
    "NVIDIA GeForce RTX 3060",
    "NVIDIA GeForce RTX 3060 Ti",
    "NVIDIA GeForce RTX 3060 Laptop GPU",
    "NVIDIA GeForce GTX 1650",
    "NVIDIA GeForce GTX 1650 with Max-Q Design",
    "NVIDIA GeForce GTX 1650 Ti",
    "NVIDIA GeForce GTX 1660 Ti",
    "NVIDIA GeForce GTX 1050",
    "NVIDIA GeForce RTX 4070 with Max-Q Design",
    "NVIDIA GeForce RTX 4070 Laptop GPU",
    "AMD Radeon RX 6600M",
    "AMD Radeon 680M",
    "Intel Arc A370M",
]
CPU_NAMES = [
    "12th Gen Intel(R) Core(TM) i5-12450H",
    "Intel(R) Core(TM) i7-1165G7 @ 2.80GHz",
    "Intel(R) Core(TM) i7-12700",
    "Intel(R) Core(TM) i7-12700H",
    "Intel(R) Core(TM) i5-9300H",
    "AMD Ryzen 7 5800H with Radeon Graphics",
    "AMD Ryzen 7 7840HS w/ Radeon 780M Graphics",
    "AMD Ryzen 5 5600H with Radeon Graphics",
    "Intel(R) Core(TM) Ultra 7 155H",
    "Apple M1",
]


def build(extra_aliases: tuple[ComponentAlias, ...] = ()) -> ComponentMatcher:
    components = [Component.from_name(GPU, n) for n in GPU_NAMES]
    components += [Component.from_name(CPU, n) for n in CPU_NAMES]
    aliases = [ComponentAlias.for_name(c, c.name) for c in components]
    return ComponentMatcher(components, [*aliases, *extra_aliases])


MATCHER = build()
EXACT = ResolutionMethod.EXACT
ALIAS = ResolutionMethod.ALIAS
FUZZY = ResolutionMethod.FUZZY


def resolve(
    kind: ComponentKind, text: str, *, prefer_mobile: bool = False, vram_gb: int | None = None
) -> Resolution:
    return MATCHER.resolve(kind, text, prefer_mobile=prefer_mobile, vram_gb=vram_gb)


@pytest.mark.parametrize(
    ("kind", "text", "component"),
    [
        (GPU, "RTX 3060 Ti", "gpu:rtx-3060-ti"),
        (GPU, "RTX3060Ti", "gpu:rtx-3060-ti"),
        (GPU, "RTX 3050Ti", "gpu:rtx-3050-ti-laptop"),  # the only 3050 Ti in the catalog
        (GPU, "GTX1650", "gpu:gtx-1650"),
        (GPU, "GTX 1650 Ti", "gpu:gtx-1650-ti"),
        (GPU, "NVIDIA GeForce GTX 1050", "gpu:gtx-1050"),
        (GPU, "GeForce GTX 1660Ti", "gpu:gtx-1660-ti"),
        (GPU, "RX 6600M", "gpu:rx-6600m"),
        (GPU, "AMD Radeon 680M", "gpu:radeon-680m"),
        (GPU, "nvidia geforce rtx 4060 laptop gpu", "gpu:rtx-4060-laptop"),
        (CPU, "i5 12450H", "cpu:i5-12450h"),
        (CPU, "i5-12450H", "cpu:i5-12450h"),
        (CPU, "Intel Core i7-1165G7", "cpu:i7-1165g7"),
        (CPU, "Intel Core i7-1165G7 2.8 GHz", "cpu:i7-1165g7"),
        (CPU, "Ryzen 7 5800H", "cpu:ryzen-7-5800h"),
        (CPU, "AMD Ryzen 7 5800H", "cpu:ryzen-7-5800h"),
        (CPU, "Core Ultra 7 155H", "cpu:core-ultra-7-155h"),
        (CPU, "Apple M1", "cpu:m1"),
        (CPU, "intel core i5-9300H 4/8 2.4GHz", "cpu:i5-9300h"),
    ],
)
def test_exact(kind: ComponentKind, text: str, component: str) -> None:
    result = resolve(kind, text)
    assert (result.component_id, result.method) == (component, EXACT)
    assert result.confidence in (0.95, 1.0)


@pytest.mark.parametrize(
    ("kind", "text", "component"),
    [
        (CPU, "Ryzen 7 7840HS", "cpu:ryzen-7-7840hs-w-radeon-780m"),  # Blender's marketing tail
        (CPU, "Intel Core i5-9300HF", "cpu:i5-9300h"),  # HF = H without iGPU
        (GPU, "1660ti", "gpu:gtx-1660-ti"),  # a bare number that only one family has
        (GPU, "GeForce 1650", "gpu:gtx-1650"),
        (GPU, "3060", "gpu:rtx-3060"),
        (GPU, "3060 ti", "gpu:rtx-3060-ti"),
    ],
)
def test_fuzzy_keeps_the_model_number(kind: ComponentKind, text: str, component: str) -> None:
    result = resolve(kind, text)
    assert (result.component_id, result.method) == (component, FUZZY)
    assert 0.7 <= result.confidence < 1.0


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        (CPU, "i7"),
        (CPU, "i5"),
        (CPU, "Intel"),
        (CPU, "Intel Core i5"),
        (CPU, "AMD Ryzen 5"),
        (CPU, "Intel Core i7 10th gen"),
        (CPU, "i5 11th gen"),
        (CPU, "Intel Core Ultra 7"),
        (CPU, "AMD Ryzen 5 with Radeon Graphics"),
        (CPU, "Ryzen 5 5555U"),  # not in the catalog; a near number is not the same chip
        (GPU, "GTX"),
        (GPU, "Intel"),
        (GPU, "integrated"),
        (GPU, "zintegrowana"),
        (GPU, "Iris Xe"),
        (GPU, "NVIDIA GeForce GTX"),
        (GPU, "840M"),  # could be a Radeon too
        (GPU, "RTX 4090"),
        (GPU, "brak"),
        (GPU, "-"),
        (GPU, ""),
        (GPU, "   "),
        (CPU, "brak"),
        (CPU, ""),
    ],
)
def test_partial_or_unknown_text_stays_unresolved(kind: ComponentKind, text: str) -> None:
    assert resolve(kind, text) == Resolution.unresolved()


def test_tier_suffixes_are_never_crossed() -> None:
    assert resolve(GPU, "RTX 3060").component_id == "gpu:rtx-3060"
    assert resolve(GPU, "GTX 1650").component_id == "gpu:gtx-1650"
    assert resolve(GPU, "RTX 4050 Ti") == Resolution.unresolved()


@pytest.mark.parametrize(
    ("text", "prefer_mobile", "expected"),
    [
        ("RTX 4060", True, "gpu:rtx-4060-laptop"),
        ("RTX 4060", False, "gpu:rtx-4060"),
        ("RTX 4060 Laptop GPU", False, "gpu:rtx-4060-laptop"),  # the text says it
        ("RTX 3060", True, "gpu:rtx-3060-laptop"),
        ("RTX 3060 Ti", True, "gpu:rtx-3060-ti"),  # no laptop Ti in the catalog
        ("RTX 4070", True, "gpu:rtx-4070-laptop"),
        ("RTX 4070 Max-Q", True, "gpu:rtx-4070-maxq"),
        ("GTX 1650", True, "gpu:gtx-1650"),  # plain beats Max-Q unless the text says Max-Q
        ("GTX 1650", False, "gpu:gtx-1650"),
        ("GTX 1050", True, "gpu:gtx-1050"),  # nothing mobile to prefer
    ],
)
def test_laptop_offers_prefer_the_mobile_variant(
    text: str, prefer_mobile: bool, expected: str
) -> None:
    result = resolve(GPU, text, prefer_mobile=prefer_mobile)
    assert result.component_id == expected
    assert result.method is EXACT


@pytest.mark.parametrize(
    ("text", "vram", "expected"),
    [
        ("RTX 3050", 6, "gpu:rtx-3050-6gb-laptop"),
        ("RTX 3050", 4, "gpu:rtx-3050-laptop"),  # no 4 GB variant: the plain one
        ("RTX 3050", None, "gpu:rtx-3050-laptop"),
        ("RTX 3050 6GB", None, "gpu:rtx-3050-6gb-laptop"),
        ("RTX 3050 6 GB", 4, "gpu:rtx-3050-6gb-laptop"),  # the text wins over vram_gb
        ("RTX 3050 Ti", 4, "gpu:rtx-3050-ti-laptop"),
        ("GTX 1650 4 GB", None, "gpu:gtx-1650"),  # a size the catalog does not split
    ],
)
def test_memory_variant_comes_from_vram_gb(text: str, vram: int | None, expected: str) -> None:
    assert resolve(GPU, text, prefer_mobile=True, vram_gb=vram).component_id == expected


def test_cpu_prefers_the_only_mobile_sibling_of_a_truncated_number() -> None:
    laptop = resolve(CPU, "i7-12700", prefer_mobile=True)
    assert (laptop.component_id, laptop.method) == ("cpu:i7-12700h", FUZZY)
    desktop = resolve(CPU, "i7-12700", prefer_mobile=False)
    assert (desktop.component_id, desktop.method) == ("cpu:i7-12700", EXACT)


def test_manual_alias_overrides_and_matches_by_slug() -> None:
    iris = Component.from_name(GPU, "Intel Iris Xe Graphics G7 96EUs")
    matcher = ComponentMatcher([iris], [ComponentAlias(GPU, "iris xe", iris.id)])
    for text in ("Iris Xe", "iris  xe", "Intel Iris Xe"):
        result = matcher.resolve(GPU, text)
        assert (result.component_id, result.method) == (iris.id, ALIAS)
    assert resolve(GPU, "Iris Xe") == Resolution.unresolved()  # no alias, no guess


def test_alias_pointing_at_a_different_part_beats_the_slug_match() -> None:
    target = "gpu:rtx-4060-laptop"
    matcher = build((ComponentAlias(GPU, "rtx 3060", target),))
    result = matcher.resolve(GPU, "RTX 3060", prefer_mobile=True)
    assert (result.component_id, result.method) == (target, ALIAS)


def test_confidence_is_lower_for_choices_than_for_literal_matches() -> None:
    literal = resolve(GPU, "RTX 4060 Laptop")
    chosen = resolve(GPU, "RTX 4060", prefer_mobile=True)
    assert (literal.confidence, chosen.confidence) == (1.0, 0.95)

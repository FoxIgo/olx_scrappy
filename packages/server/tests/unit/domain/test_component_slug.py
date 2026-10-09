"""Component name normalization: the slug is the join key between benchmark names, aliases
and (later) the free-text CPU/GPU of an offer."""

from __future__ import annotations

import pytest

from scrappy.domain.component import (
    Component,
    ComponentKind,
    Segment,
    alias_text,
    component_slug,
    is_identifying_slug,
)

GPU_NAMES = [
    ("NVIDIA GeForce RTX 4060 Laptop GPU", "rtx-4060-laptop"),
    ("NVIDIA GeForce RTX 4060", "rtx-4060"),
    ("GeForce RTX 4060 Ti", "rtx-4060-ti"),
    ("RTX4060Ti", "rtx-4060-ti"),
    ("rtx3050ti 4GB", "rtx-3050-ti-4gb"),
    ("NVIDIA GeForce RTX 3050 6GB Laptop GPU", "rtx-3050-6gb-laptop"),
    ("Laptop NVIDIA RTX 3050 Ti", "rtx-3050-ti-laptop"),
    ("GeForce RTX 3060 Mobile", "rtx-3060-laptop"),
    ("NVIDIA GeForce GTX 1650", "gtx-1650"),
    ("GTX1650", "gtx-1650"),
    ("NVIDIA GeForce GTX 1650 with Max-Q Design", "gtx-1650-maxq"),
    ("NVIDIA GeForce RTX 3080 Ti Laptop GPU", "rtx-3080-ti-laptop"),
    ("NVIDIA GeForce RTX 4070 SUPER", "rtx-4070-super"),
    ("NVIDIA RTX A2000 Laptop GPU", "rtx-a2000-laptop"),
    ("AMD Radeon RX 6600M", "rx-6600m"),
    ("Radeon RX 7900 XTX", "rx-7900-xtx"),
    ("AMD Radeon 780M Graphics", "radeon-780m"),
    ("Intel(R) Arc(TM) A770 Graphics", "arc-a770"),
    ("Intel(R) Iris(R) Xe Graphics", "iris-xe"),
    ("Intel(R) UHD Graphics 620", "uhd-620"),
    ("NVIDIA GeForce MX450", "mx-450"),
]

CPU_NAMES = [
    ("12th Gen Intel(R) Core(TM) i5-12450H", "i5-12450h"),
    ("Intel(R) Core(TM) i7-1165G7 @ 2.80GHz", "i7-1165g7"),
    ("Intel Core i7-3770K CPU @ 3.50GHz", "i7-3770k"),
    ("i5 12450H", "i5-12450h"),
    ("Intel Core Ultra 7 155H", "core-ultra-7-155h"),
    ("AMD Ryzen 7 5800H with Radeon Graphics", "ryzen-7-5800h"),
    ("AMD Ryzen 3 3100 4-Core Processor", "ryzen-3-3100"),
    ("AMD Ryzen 5 PRO 4650U with Radeon Graphics", "ryzen-5-pro-4650u"),
    ("AMD Ryzen 9 7945HX3D", "ryzen-9-7945hx3d"),
    ("Intel Xeon CPU E5-1650 v4 @ 3.60GHz", "xeon-e5-1650-v4"),
    ("Intel(R) Celeron(R) N4020 CPU @ 1.10GHz", "celeron-n4020"),
    ("Apple M2 Pro", "m2-pro"),
]


@pytest.mark.parametrize(("name", "slug"), GPU_NAMES)
def test_gpu_slugs(name: str, slug: str) -> None:
    assert component_slug(name, "gpu") == slug


@pytest.mark.parametrize(("name", "slug"), CPU_NAMES)
def test_cpu_slugs(name: str, slug: str) -> None:
    assert component_slug(name, "cpu") == slug


@pytest.mark.parametrize(("name", "slug"), GPU_NAMES)
def test_gpu_slugs_are_idempotent(name: str, slug: str) -> None:
    assert component_slug(slug, "gpu") == slug


@pytest.mark.parametrize(("name", "slug"), CPU_NAMES)
def test_cpu_slugs_are_idempotent(name: str, slug: str) -> None:
    assert component_slug(slug, "cpu") == slug


def test_laptop_and_desktop_variants_never_collapse() -> None:
    desktop = component_slug("NVIDIA GeForce RTX 4060", "gpu")
    laptop = component_slug("NVIDIA GeForce RTX 4060 Laptop GPU", "gpu")
    maxq = component_slug("NVIDIA GeForce RTX 4060 Max-Q", "gpu")
    assert len({desktop, laptop, maxq}) == 3
    assert component_slug("RTX 3050 Laptop GPU", "gpu") != component_slug(
        "RTX 3050 Ti Laptop", "gpu"
    )
    assert component_slug("RTX 3050 6GB Laptop", "gpu") != component_slug("RTX 3050 Laptop", "gpu")


def test_word_order_of_laptop_marker_does_not_matter() -> None:
    assert component_slug("Laptop RTX 4060", "gpu") == component_slug("RTX 4060 Laptop GPU", "gpu")


@pytest.mark.parametrize("text", ["", "   ", "Intel(R) Graphics", "NVIDIA GPU"])
def test_names_without_identity_give_an_empty_slug(text: str) -> None:
    assert component_slug(text, "gpu") == ""


def test_generic_names_have_no_model_number() -> None:
    assert not is_identifying_slug(component_slug("AMD Radeon Graphics", "gpu"))
    assert not is_identifying_slug(component_slug("Intel(R) Arc(TM) Graphics", "gpu"))
    assert is_identifying_slug("rtx-4060")


def test_alias_text_lowercases_and_collapses_whitespace() -> None:
    assert alias_text("  NVIDIA   GeForce RTX\t4060 ") == "nvidia geforce rtx 4060"


GPU = ComponentKind.GPU
CPU = ComponentKind.CPU


@pytest.mark.parametrize(
    ("kind", "name", "traits"),
    [
        (GPU, "NVIDIA GeForce RTX 4060 Laptop GPU", (Segment.MOBILE, "nvidia", "rtx", "40")),
        (GPU, "GeForce GTX 1650 with Max-Q Design", (Segment.MOBILE, "nvidia", "gtx", "16")),
        (GPU, "NVIDIA GeForce RTX 4060", (Segment.UNKNOWN, "nvidia", "rtx", "40")),
        (GPU, "AMD Radeon RX 6800M", (Segment.MOBILE, "amd", "rx", "6000")),
        (GPU, "AMD Radeon 780M Graphics", (Segment.INTEGRATED, "amd", "radeon", None)),
        (GPU, "Intel(R) Iris(R) Xe Graphics", (Segment.INTEGRATED, "intel", "iris", None)),
        (CPU, "12th Gen Intel(R) Core(TM) i5-12450H", (Segment.MOBILE, "intel", "core-i5", "12")),
        (CPU, "Intel(R) Core(TM) i7-1165G7", (Segment.MOBILE, "intel", "core-i7", "11")),
        (CPU, "Intel Core i5-8250U", (Segment.MOBILE, "intel", "core-i5", "8")),
        (CPU, "Intel Core i7-3770K", (Segment.DESKTOP, "intel", "core-i7", "3")),
        (CPU, "Intel Core i5-12400F", (Segment.DESKTOP, "intel", "core-i5", "12")),
        (CPU, "AMD Ryzen 7 5800H with Radeon Graphics", (Segment.MOBILE, "amd", "ryzen-7", "5000")),
        (CPU, "AMD Ryzen 5 5600X", (Segment.DESKTOP, "amd", "ryzen-5", "5000")),
        (CPU, "Intel Xeon CPU E5-1650 v4", (Segment.UNKNOWN, "intel", "xeon", None)),
    ],
)
def test_traits_are_derived_heuristically(
    kind: ComponentKind, name: str, traits: tuple[Segment, str, str, str | None]
) -> None:
    component = Component.from_name(kind, name)

    assert (component.segment, component.vendor, component.family, component.generation) == traits
    assert component.id == f"{kind.value}:{component.slug}"

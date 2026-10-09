"""Canonical CPU/GPU components, their aliases and benchmark scores (ADR 0011).

Facts only: a score is stored as measured. Which score matters is a scoring strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NamedTuple

from scrappy.domain.component.slug import alias_text, component_slug
from scrappy.domain.shared import InvalidValueError, require_aware


class ComponentKind(StrEnum):
    CPU = "cpu"
    GPU = "gpu"


class Segment(StrEnum):
    MOBILE = "mobile"
    DESKTOP = "desktop"
    INTEGRATED = "integrated"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Component:
    """One part, identified by ``(kind, slug)``; ``id`` is ``"<kind>:<slug>"``."""

    kind: ComponentKind
    slug: str
    name: str
    vendor: str | None = None
    family: str | None = None
    generation: str | None = None
    segment: Segment = Segment.UNKNOWN

    def __post_init__(self) -> None:
        if not self.slug or not self.name.strip():
            raise InvalidValueError("a component needs a name and a slug")

    @property
    def id(self) -> str:
        return component_id(self.kind, self.slug)

    @classmethod
    def from_name(cls, kind: ComponentKind, name: str) -> Component:
        """Build a component from a device name; the traits are derived heuristically."""
        slug = component_slug(name, kind.value)
        if not slug:
            raise InvalidValueError(f"cannot derive a component slug from {name!r}")
        traits = _cpu_traits(slug) if kind is ComponentKind.CPU else _gpu_traits(slug)
        return cls(
            kind=kind,
            slug=slug,
            name=" ".join(name.split()),
            vendor=traits.vendor,
            family=traits.family,
            generation=traits.generation,
            segment=traits.segment,
        )


def component_id(kind: ComponentKind, slug: str) -> str:
    return f"{kind.value}:{slug}"


@dataclass(frozen=True, slots=True)
class ComponentAlias:
    """A normalized text (see ``alias_text``) that names ``component_id`` for ``kind``."""

    kind: ComponentKind
    alias: str
    component_id: str

    @classmethod
    def for_name(cls, component: Component, text: str) -> ComponentAlias:
        return cls(component.kind, alias_text(text), component.id)


@dataclass(frozen=True, slots=True)
class Benchmark:
    """One score of a component from one ``(source, metric)``; ``samples`` = submissions."""

    component_id: str
    source: str
    metric: str
    score: float
    samples: int
    fetched_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.fetched_at, "fetched_at")
        if self.samples < 1:
            raise InvalidValueError("a benchmark needs at least one sample")


# ---------------------------------------------------------------------------- heuristics


class _Traits(NamedTuple):
    vendor: str | None
    family: str | None
    generation: str | None
    segment: Segment


def _cpu_vendor_family(slug: str) -> tuple[str | None, str | None]:
    if match := re.match(r"(ryzen(?:-ai)?(?:-(?:[3579]|z\d))?|threadripper|athlon|epyc)\b", slug):
        return "amd", match[1]
    if match := re.match(r"(core-ultra-[579]|core-[357]|i[3579]|xeon|celeron|pentium)\b", slug):
        family = f"core-{match[1]}" if re.fullmatch(r"i[3579]", match[1]) else match[1]
        return "intel", family
    if re.match(r"m\d", slug):
        return "apple", "apple-m"
    if re.match(r"n\d{3}", slug):
        return "intel", "intel-n"
    return None, None


_INTEL_MOBILE = re.compile(r"^(?:h[a-z]?|u|p|y|g\d|m|[qm]m|mq|hq|hk|hx|l)$")
_INTEL_DESKTOP = re.compile(r"^(?:|k|kf|ks|f|t|s|x|xe|kb|e)$")
_RYZEN_MOBILE = re.compile(r"^(?:u|h|hs|hx|hx3d|c|e)$")
_RYZEN_DESKTOP = re.compile(r"^(?:|x|x3d|g|ge|gt|f|xt|t|e)$")


def _cpu_traits(slug: str) -> _Traits:
    vendor, family = _cpu_vendor_family(slug)
    generation: str | None = None
    segment = Segment.UNKNOWN
    if vendor == "intel" and (match := re.search(r"\bi[3579]-(\d{4,5})([a-z]{0,2}\d?)$", slug)):
        digits, suffix = match[1], match[2]
        if len(digits) == 5 or (digits[:2] in {"10", "11"} and suffix.startswith("g")):
            generation = digits[:2]  # 12450 -> 12, 1165G7 -> 11
        else:
            generation = digits[0]  # 8250U -> 8, 4710MQ -> 4
        segment = _intel_segment(suffix)
    elif vendor == "intel" and (match := re.search(r"-(\d{3})([a-z]{0,2})$", slug)):
        segment = _intel_segment(match[2]) if family and "ultra" in family else Segment.UNKNOWN
    elif vendor == "amd" and (match := re.search(r"-(\d{4})([a-z0-9]{0,4})$", slug)):
        generation = f"{match[1][0]}000"
        suffix = match[2]
        if _RYZEN_MOBILE.match(suffix):
            segment = Segment.MOBILE
        elif _RYZEN_DESKTOP.match(suffix):
            segment = Segment.DESKTOP
    return _Traits(vendor, family, generation, segment)


def _intel_segment(suffix: str) -> Segment:
    if _INTEL_MOBILE.match(suffix):
        return Segment.MOBILE
    if _INTEL_DESKTOP.match(suffix):
        return Segment.DESKTOP
    return Segment.UNKNOWN


def _gpu_traits(slug: str) -> _Traits:
    tokens = slug.split("-")
    vendor: str | None = None
    family: str | None = None
    generation: str | None = None
    number = next((t for t in tokens if re.fullmatch(r"\d{3,4}[a-z]?", t)), None)
    if tokens[0] in {"rtx", "gtx", "gts", "gt", "mx"}:
        vendor, family = "nvidia", tokens[0]
        if number is not None and len(number) >= 4 and number[:4].isdigit():
            generation = number[:2]
    elif tokens[0] == "rx" or tokens[0] == "radeon" or tokens[0] == "vega":
        vendor, family = "amd", tokens[0]
        if tokens[0] == "rx" and number is not None and number[:4].isdigit():
            generation = f"{number[0]}000"
    elif tokens[0] in {"arc", "iris", "uhd", "hd"}:
        vendor, family = "intel", tokens[0]
    elif re.fullmatch(r"m\d.*", tokens[0]):
        vendor, family = "apple", "apple-m"
    return _Traits(vendor, family, generation, _gpu_segment(tokens, number))


def _gpu_segment(tokens: list[str], number: str | None) -> Segment:
    if "laptop" in tokens or "maxq" in tokens:
        return Segment.MOBILE
    first = tokens[0]
    if first in {"iris", "uhd", "hd", "vega"} or (first == "radeon" and number is not None):
        # Radeon 680M / Vega 8 are integrated; "Radeon RX ..." is handled below
        return Segment.INTEGRATED
    if first == "arc" and any(re.fullmatch(r"\d{3}[vt]", t) for t in tokens):
        return Segment.INTEGRATED
    if re.fullmatch(r"\d{3,4}[ms]", number or ""):
        return Segment.MOBILE if first in {"rx", "gtx", "gt", "arc", "mx"} else Segment.INTEGRATED
    if first == "arc" and any(re.fullmatch(r"a\d{3}m", t) for t in tokens):
        return Segment.MOBILE
    if first == "mx":
        return Segment.MOBILE
    return Segment.UNKNOWN

"""Linking an offer's free-text CPU/GPU to a canonical component (ADR 0011 section 3).

``ComponentMatcher`` is pure: it is built from the component catalog and the aliases and
answers "which component does this raw text name?". Order of evidence:

1. a **manual alias** that points somewhere other than the text's own slug (a human decision
   always wins; seeded aliases only repeat the slug match and are not an override);
2. a text without a model number ("i7", "GTX", "Intel", "integrated") is **unresolved**,
   never guessed;
3. **exact** slug match, choosing the variant that fits the offer (below);
4. **fuzzy**, always with the *same model number*: a CPU named without Blender's "w/ Radeon
   780M" tail, an Intel "HF" for "H", a bare GPU number ("1660ti" -> GTX 1660 Ti) when only
   one family has it, or a close slug; ambiguous candidates stay unresolved;
5. (follow-up) an LLM picking from a short candidate list: ``ResolutionMethod.LLM``.

Variant choice. Extractions write "RTX 4060", not "RTX 4060 Laptop GPU", but a laptop has
the laptop silicon, so with ``prefer_mobile`` the order is ``-laptop``, ``-maxq``,
``-laptop-maxq``, then the plain slug (other offers: the reverse). Memory size variants
(``rtx-3050-6gb-laptop`` vs ``rtx-3050-laptop``): the offer's ``vram_gb`` picks the sized one
when it exists, otherwise the plain one. A text that already says "Laptop"/"Max-Q" is taken
literally. For CPUs, ``prefer_mobile`` swaps a desktop part for its only mobile sibling
(``i7-12700`` -> ``i7-12700h``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from enum import StrEnum

from scrappy.domain.component.component import Component, ComponentAlias, ComponentKind, Segment
from scrappy.domain.component.slug import alias_text, component_slug, is_identifying_slug
from scrappy.domain.offer import OfferId
from scrappy.domain.shared import InvalidValueError, require_aware

RESOLVER_VERSION = 2
"""Bump when the matching rules change; every link with an older version is re-resolved."""


class ResolutionMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    LLM = "llm"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Resolution:
    component_id: str | None
    confidence: float
    method: ResolutionMethod

    @classmethod
    def unresolved(cls) -> Resolution:
        return cls(None, 0.0, ResolutionMethod.UNRESOLVED)


@dataclass(frozen=True, slots=True)
class OfferComponentLink:
    """The stored answer for ``(offer, kind)``; ``raw_text`` is what it was resolved from."""

    offer_id: OfferId
    kind: ComponentKind
    raw_text: str
    resolution: Resolution
    resolver_version: int
    resolved_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.resolved_at, "resolved_at")
        r = self.resolution
        if not 0.0 <= r.confidence <= 1.0:
            raise InvalidValueError("confidence must be between 0 and 1")
        if (r.component_id is None) != (r.method is ResolutionMethod.UNRESOLVED):
            raise InvalidValueError("a link is unresolved exactly when it has no component")


_SUFFIXES = ("-laptop-maxq", "-laptop", "-maxq")
_MOBILE_ORDER = ("-laptop", "", "-maxq", "-laptop-maxq")  # Max-Q only when the text says so
_PLAIN_ORDER = ("", "-laptop", "-maxq", "-laptop-maxq")
_MEMORY = re.compile(r"-\d+gb(?=-|$)")
_MODEL_TOKEN = re.compile(r"^\d{3,}[a-z0-9]*$")
_TIER = frozenset({"ti", "super", "xt", "xtx"})
_SIBLING_REST = re.compile(r"^[a-z]{1,2}\d?$")
_DECORATION = re.compile(r"^(.+?)-(?:w|radeon|creator)(?:-|$)")
"""Blender names "Ryzen 7 7840HS w/ Radeon 780M": the slug has a tail offers never write."""
_INTEL_HF = re.compile(r"(-\d{4,5}h[kqx]?)f$")
_MEMORY_TEXT = re.compile(r"\b(\d+)\s*gb?\b", re.IGNORECASE)
_CORES_TEXT = re.compile(r"\b\d+\s*/\s*\d+\b")
_NVIDIA_FAMILIES = frozenset({"rtx", "gtx", "gts", "gt", "mx"})
_FUZZY_MIN_RATIO = 0.8
_FUZZY_MARGIN = 0.1


def _clean(text: str) -> str:
    """ "4 GB" -> "4GB"; drop "6/12" core/thread counts that offers append to a CPU name."""
    return _CORES_TEXT.sub(" ", _MEMORY_TEXT.sub(r"\1gb", text))


def _split_suffix(slug: str) -> tuple[str, str]:
    for suffix in _SUFFIXES:
        if slug.endswith(suffix):
            return slug[: -len(suffix)], suffix
    return slug, ""


def _model_token(slug: str) -> str | None:
    return next((t for t in slug.split("-") if _MODEL_TOKEN.match(t)), None)


def _tier(slug: str) -> frozenset[str]:
    return frozenset(slug.split("-")) & _TIER


class ComponentMatcher:
    """See the module docstring. Build once per batch; ``resolve`` is cheap and pure."""

    def __init__(self, components: Iterable[Component], aliases: Iterable[ComponentAlias]) -> None:
        self._by_slug: dict[tuple[ComponentKind, str], Component] = {}
        self._by_id: dict[str, Component] = {}
        self._by_model: dict[tuple[ComponentKind, str], list[Component]] = {}
        for c in components:
            self._by_slug[(c.kind, c.slug)] = c
            self._by_id[c.id] = c
            token = _model_token(c.slug)
            if token is not None:
                self._by_model.setdefault((c.kind, token), []).append(c)
        self._decorated: dict[tuple[ComponentKind, str], list[Component]] = {}
        for c in self._by_id.values():
            if match := _DECORATION.match(c.slug):
                self._decorated.setdefault((c.kind, match[1]), []).append(c)
        self._alias_text: dict[tuple[ComponentKind, str], str] = {}
        self._alias_slug: dict[tuple[ComponentKind, str], str | None] = {}
        for a in aliases:
            self._alias_text[(a.kind, a.alias)] = a.component_id
            slug = component_slug(a.alias, a.kind.value)
            if slug:
                key = (a.kind, slug)
                known = self._alias_slug.get(key, a.component_id)
                self._alias_slug[key] = known if known == a.component_id else None  # ambiguous

    def resolve(
        self,
        kind: ComponentKind,
        raw_text: str,
        *,
        prefer_mobile: bool = False,
        vram_gb: int | None = None,
    ) -> Resolution:
        text = raw_text.strip()
        if not text:
            return Resolution.unresolved()
        slug = component_slug(_clean(text), kind.value)
        override = self._override(kind, text, slug)
        if override is not None:
            return override
        if not is_identifying_slug(slug):
            return Resolution.unresolved()
        direct = self._lookup(kind, slug, prefer_mobile, vram_gb)
        if direct is not None:
            return direct
        without_f = _INTEL_HF.sub(r"\1", slug)
        if kind is ComponentKind.CPU and without_f != slug:
            alt = self._lookup(kind, without_f, prefer_mobile, vram_gb)
            if alt is not None:
                return Resolution(
                    alt.component_id, min(alt.confidence, 0.85), ResolutionMethod.FUZZY
                )
        return self._fuzzy(kind, slug, prefer_mobile, vram_gb)

    def _lookup(
        self, kind: ComponentKind, slug: str, prefer_mobile: bool, vram_gb: int | None
    ) -> Resolution | None:
        found = self._pick(kind, slug, prefer_mobile, vram_gb)
        if found is not None:
            component, is_slug_itself = found
            if prefer_mobile and kind is ComponentKind.CPU:
                sibling = self._mobile_sibling(component)
                if sibling is not None:
                    return Resolution(sibling.id, 0.8, ResolutionMethod.FUZZY)
            confidence = 1.0 if is_slug_itself else 0.95
            return Resolution(component.id, confidence, ResolutionMethod.EXACT)
        decorated = self._decorated.get((kind, slug))
        if decorated:  # same chip under several marketing tails: the shortest name is canonical
            best = min(decorated, key=lambda c: (len(c.slug), c.slug))
            return Resolution(best.id, 0.9, ResolutionMethod.FUZZY)
        return None

    # ------------------------------------------------------------------ evidence

    def _override(self, kind: ComponentKind, text: str, slug: str) -> Resolution | None:
        target = self._alias_text.get((kind, alias_text(text)))
        if target is None and slug:
            target = self._alias_slug.get((kind, slug))
        component = self._by_id.get(target) if target else None
        if component is None or component.slug == slug:
            return None
        return Resolution(component.id, 1.0, ResolutionMethod.ALIAS)

    def _pick(
        self, kind: ComponentKind, slug: str, prefer_mobile: bool, vram_gb: int | None
    ) -> tuple[Component, bool] | None:
        """First existing variant of ``slug``; the bool says it is the slug itself."""
        core, suffix = _split_suffix(slug)
        order = (suffix,) if suffix else (_MOBILE_ORDER if prefer_mobile else _PLAIN_ORDER)
        cores = [core]
        if _MEMORY.search(core):
            cores.append(_MEMORY.sub("", core))  # "gtx-1650-4gb" -> "gtx-1650" as a fallback
        elif vram_gb and kind is ComponentKind.GPU:
            cores.insert(0, f"{core}-{vram_gb}gb")
        for candidate_core in cores:
            for sfx in order:
                candidate = candidate_core + sfx
                component = self._by_slug.get((kind, candidate))
                if component is not None:
                    return component, candidate == slug
        return None

    def _mobile_sibling(self, component: Component) -> Component | None:
        """The only mobile CPU named like this one plus 1-2 letters (``i7-12700h``)."""
        if component.segment is Segment.MOBILE:
            return None
        mobile = [
            c
            for (kind, _), c in self._by_slug.items()
            if kind is component.kind
            and c.segment is Segment.MOBILE
            and c.slug.startswith(component.slug)
            and _SIBLING_REST.match(c.slug[len(component.slug) :])
        ]
        return mobile[0] if len(mobile) == 1 else None

    def _fuzzy(
        self, kind: ComponentKind, slug: str, prefer_mobile: bool, vram_gb: int | None
    ) -> Resolution:
        token = _model_token(slug)
        if token is None:
            return Resolution.unresolved()
        core, suffix = _split_suffix(slug)
        plain_core = _MEMORY.sub("", core)
        if kind is ComponentKind.GPU and core[0].isdigit():
            return self._bare_number(kind, token, plain_core, suffix, prefer_mobile, vram_gb)
        scored: dict[str, float] = {}
        for candidate in self._by_model.get((kind, token), ()):
            c_core = _MEMORY.sub("", _split_suffix(candidate.slug)[0])
            if _tier(c_core) != _tier(plain_core):
                continue
            ratio = SequenceMatcher(None, plain_core, c_core).ratio()
            if ratio >= _FUZZY_MIN_RATIO:
                scored[c_core] = max(scored.get(c_core, 0.0), ratio)
        ranked = sorted(scored.items(), key=lambda item: item[1], reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][1] - ranked[1][1] < _FUZZY_MARGIN):
            return Resolution.unresolved()
        best_core, ratio = ranked[0]
        found = self._pick(kind, best_core + suffix, prefer_mobile, vram_gb)
        if found is None:
            return Resolution.unresolved()
        return Resolution(found[0].id, round(ratio * 0.9, 2), ResolutionMethod.FUZZY)

    def _bare_number(
        self,
        kind: ComponentKind,
        token: str,
        plain_core: str,
        suffix: str,
        prefer_mobile: bool,
        vram_gb: int | None,
    ) -> Resolution:
        """ "1660ti" / "3060": the number (plus tier) alone, when exactly one NVIDIA family has
        it (a bare "840M" could as well be a Radeon)."""
        cores = {
            core
            for c in self._by_model.get((kind, token), ())
            if (core := _MEMORY.sub("", _split_suffix(c.slug)[0])).partition("-")[2] == plain_core
            and core.partition("-")[0] in _NVIDIA_FAMILIES
        }
        if len(cores) != 1:
            return Resolution.unresolved()
        found = self._pick(kind, cores.pop() + suffix, prefer_mobile, vram_gb)
        if found is None:
            return Resolution.unresolved()
        return Resolution(found[0].id, 0.8, ResolutionMethod.FUZZY)

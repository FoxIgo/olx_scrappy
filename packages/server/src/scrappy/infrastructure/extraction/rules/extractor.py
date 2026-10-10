"""``RuleBasedExtractor``: tier 0 of ADR 0012 (params mapping + regex, no LLM).

Facts come from three places, in this order of trust:

1. **Site params** that are exact (OLX ``state`` -> condition, ``harddisktype`` -> storage
   type). Range params ("6GB - 12GB") are never facts; they only veto parsed values.
2. **Title**, where sellers write spec lists ("i5-8265U / 8GB / SSD 256GB / 14"").
3. **Description**, for what the title lacks.

A value found in several different forms (two RAM sizes, two dedicated GPUs) is dropped
and reported as uncertain, never guessed. Uncertainty reasons are what the tiering policy
uses to send an offer to the LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from scrappy.application.ports.extractor import (
    RULES_MODEL,
    ExtractionInput,
    ExtractionResult,
    RuleExtraction,
)
from scrappy.domain.category import OTHER_CATEGORY, Category, CategoryName
from scrappy.domain.offer import PriceKind
from scrappy.infrastructure.extraction.rules import olx_params as olx
from scrappy.infrastructure.extraction.rules.damage import (
    find_damage,
    junk_title,
    mentions_damage,
)
from scrappy.infrastructure.extraction.rules.hardware import (
    GPU_WORDS,
    GpuMatch,
    find_cpus,
    find_gpus,
)
from scrappy.infrastructure.extraction.rules.specs import (
    find_battery_wh,
    find_ram,
    find_refresh,
    find_resolutions,
    find_screens,
    find_slash_pair,
    find_storage,
)

RULES_VERSION = "rules-v1"
"""Bump on every rule change that can alter results; offers are then re-run (cheap)."""

LAPTOP = CategoryName("laptop")
JUNK_PRICE_FLOOR = Decimal(80)
"""A fixed price below this is suspicious for a laptop (a part, a placeholder): the offer is
not classified by rules, it is sent to the LLM."""


class Uncertain:
    """Reason codes (``RuleExtraction.uncertain``)."""

    NO_RULES = "no_rules"  # no rule set for any candidate category
    EMPTY = "empty"  # nothing extracted
    DAMAGED = "damaged"  # damaged / for parts: damage list and condition need the LLM
    DAMAGE_UNCLEAR = "damage_unclear"  # damage words in a "used" offer
    CHEAP = "cheap"  # price below the junk floor
    CPU_MULTIPLE = "cpu_multiple"
    CPU_CONFLICT = "cpu_conflict"  # differs from the site's processor family
    GPU_MULTIPLE = "gpu_multiple"
    GPU_MISSING = "gpu_missing"  # site says dedicated GPU, none found
    GPU_CONFLICT = "gpu_conflict"  # site says integrated, dedicated found
    RAM_CONFLICT = "ram_conflict"
    STORAGE_CONFLICT = "storage_conflict"
    SCREEN_CONFLICT = "screen_conflict"


@dataclass(slots=True)
class _Draft:
    attributes: dict[str, object] = field(default_factory=dict[str, object])
    uncertain: list[str] = field(default_factory=list[str])

    def unsure(self, reason: str) -> None:
        if reason not in self.uncertain:
            self.uncertain.append(reason)


def _pick[T](title: Sequence[T], description: Sequence[T]) -> tuple[T | None, bool]:
    """``(value, conflicting)``: the title wins; else a single description value."""
    if len(title) == 1:
        return title[0], False
    if len(title) > 1:
        return None, True
    if len(description) == 1:
        return description[0], False
    return None, len(description) > 1


class LaptopRules:
    """Rules for the ``laptop`` category (attribute names of ``config/categories.yaml``)."""

    def apply(self, request: ExtractionInput, category: Category) -> RuleExtraction:
        draft = _Draft()
        title, description = request.title, request.description
        params = dict(request.params)
        self._condition(draft, params, title, description)
        self._cpu(draft, params, title, description)
        self._gpu(draft, params, title, description)
        self._memory_and_storage(draft, params, title, description)
        self._screen(draft, params, title, description)
        known = {
            name: value
            for name, value in draft.attributes.items()
            if value is not None and category.attribute(name) is not None
        }
        if not known:
            draft.unsure(Uncertain.EMPTY)
            return RuleExtraction(None, tuple(draft.uncertain))
        notes = f"rules: unsure {', '.join(draft.uncertain)}" if draft.uncertain else None
        result = ExtractionResult(
            category=category.name,
            attributes=known,
            model=RULES_MODEL,
            prompt_version=RULES_VERSION,
            notes=notes,
        )
        return RuleExtraction(result, tuple(draft.uncertain))

    # ------------------------------------------------------------------ fields
    @staticmethod
    def _condition(draft: _Draft, params: Mapping[str, str], title: str, description: str) -> None:
        text = f"{title}\n{description}"
        damage = find_damage(text)
        state = olx.condition(params)
        storage_missing = olx.storage_missing(params)
        if storage_missing and "storage_missing" not in damage:
            damage.append("storage_missing")
        damaged_words = mentions_damage(text)
        if state in ("damaged", "for_parts"):
            draft.attributes["condition"] = state
            draft.unsure(Uncertain.DAMAGED)
        elif damaged_words or (damage and set(damage) - olx.MISSING_ONLY):
            draft.unsure(Uncertain.DAMAGE_UNCLEAR)
        elif state is not None:
            draft.attributes["condition"] = state
        draft.attributes["damage"] = damage or (
            [] if state in ("new", "used") and not damaged_words else None
        )

    @staticmethod
    def _cpu(draft: _Draft, params: Mapping[str, str], title: str, description: str) -> None:
        cpu, multiple = _pick(find_cpus(title), find_cpus(description))
        if multiple:
            draft.unsure(Uncertain.CPU_MULTIPLE)
        if cpu is not None and not olx.cpu_matches_family(params, cpu):
            draft.unsure(Uncertain.CPU_CONFLICT)
            cpu = None
        draft.attributes["cpu"] = cpu

    @staticmethod
    def _gpu(draft: _Draft, params: Mapping[str, str], title: str, description: str) -> None:
        def gpus(text: str, *, dedicated: bool) -> list[GpuMatch]:
            return [g for g in find_gpus(text) if g.dedicated is dedicated]

        gpu, multiple = _pick(gpus(title, dedicated=True), gpus(description, dedicated=True))
        if multiple:
            draft.unsure(Uncertain.GPU_MULTIPLE)
        kind = olx.gpu_kind(params)
        if gpu is None and not multiple:
            if kind == "dedicated" and GPU_WORDS.search(f"{title}\n{description}"):
                draft.unsure(Uncertain.GPU_MISSING)
            else:
                gpu, _ = _pick(gpus(title, dedicated=False), gpus(description, dedicated=False))
        elif gpu is not None and kind == "integrated":
            draft.unsure(Uncertain.GPU_CONFLICT)
            gpu = None
        if gpu is not None:
            draft.attributes["gpu"] = gpu.name
            draft.attributes["vram_gb"] = gpu.vram_gb

    @staticmethod
    def _memory_and_storage(
        draft: _Draft, params: Mapping[str, str], title: str, description: str
    ) -> None:
        title_ram, title_max = find_ram(title)
        desc_ram, desc_max = find_ram(description)
        pair = find_slash_pair(title)
        if pair is not None and not title_ram:
            title_ram = [pair[0]]
        ram, conflicting = _pick(title_ram, desc_ram)
        if ram is not None and not olx.within_range(params, olx.RAM_PARAM, ram):
            conflicting, ram = True, None
        if conflicting:
            draft.unsure(Uncertain.RAM_CONFLICT)
        draft.attributes["ram_gb"] = ram
        maximum, _ = _pick(title_max, desc_max)
        if maximum is not None and (ram is None or maximum > ram):
            draft.attributes["max_ram_gb"] = maximum

        drives_title = find_storage(title)
        if not drives_title and pair is not None:
            drives_title = [(pair[1], None)]
        drives = drives_title or find_storage(description)
        size: int | None = None
        kinds = {kind for _, kind in drives if kind is not None}
        if len(drives) == 1:
            size = drives[0][0]
        elif len(drives) == 2 and len(kinds) == 2:  # SSD + HDD: total capacity
            size = drives[0][0] + drives[1][0]
        elif drives:
            draft.unsure(Uncertain.STORAGE_CONFLICT)
        if size is not None and not olx.within_range(params, olx.DISK_PARAM, size):
            draft.unsure(Uncertain.STORAGE_CONFLICT)
            size = None
        draft.attributes["storage_gb"] = size
        storage_type = olx.storage_type(params)
        if storage_type is None and len(kinds) == 1:
            storage_type = next(iter(kinds))
        elif storage_type is None and kinds == {"ssd", "hdd"}:
            storage_type = "ssd"
        draft.attributes["storage_type"] = storage_type

    @staticmethod
    def _screen(draft: _Draft, params: Mapping[str, str], title: str, description: str) -> None:
        screen, conflicting = _pick(
            find_screens(title, allow_bare=True), find_screens(description, allow_bare=False)
        )
        if screen is not None and not olx.within_range(params, olx.SCREEN_PARAM, screen):
            conflicting, screen = True, None
        if conflicting:
            draft.unsure(Uncertain.SCREEN_CONFLICT)
        draft.attributes["screen_in"] = screen
        refresh, _ = _pick(find_refresh(title), find_refresh(description))
        draft.attributes["refresh_hz"] = refresh
        resolution, _ = _pick(find_resolutions(title), find_resolutions(description))
        draft.attributes["resolution"] = resolution
        battery, _ = _pick(find_battery_wh(title), find_battery_wh(description))
        draft.attributes["battery_wh"] = battery


type RuleSet = Callable[[ExtractionInput, Category], RuleExtraction]


class RuleBasedExtractor:
    """Picks the rule set of a candidate category; junk titles become ``other``.

    With no rule set for any candidate category the offer is left to the LLM.
    """

    def __init__(self, rule_sets: Mapping[CategoryName, RuleSet] | None = None) -> None:
        self._rule_sets: dict[CategoryName, RuleSet] = dict(
            rule_sets if rule_sets is not None else {LAPTOP: LaptopRules().apply}
        )

    @property
    def version(self) -> str:
        return RULES_VERSION

    def extract(self, request: ExtractionInput) -> RuleExtraction:
        candidates = [c for c in request.categories if c.name in self._rule_sets]
        if len(candidates) != 1:
            return RuleExtraction(None, (Uncertain.NO_RULES,))
        price = request.price
        if (
            price is not None
            and price.kind is PriceKind.FIXED
            and price.amount is not None
            and price.amount.amount < JUNK_PRICE_FLOOR
        ):
            return RuleExtraction(None, (Uncertain.CHEAP,))
        if junk_title(request.title):
            return RuleExtraction(
                ExtractionResult(
                    category=OTHER_CATEGORY,
                    attributes={},
                    model=RULES_MODEL,
                    prompt_version=RULES_VERSION,
                    notes="rules: accessory or other device in the title",
                )
            )
        category = candidates[0]
        return self._rule_sets[category.name](request, category)

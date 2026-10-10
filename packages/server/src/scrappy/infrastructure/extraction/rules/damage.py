"""Damage, missing parts and junk in Polish offer text (ADR 0012 tier 0).

Stem regexes cover Polish inflection ("pęknięta / pękniętą / pęknięty matryca"). A match
preceded by a negation ("nie uszkodzona", "bez pęknięć") is ignored. The rules only report
what they find; deciding damaged vs for_parts is left to the LLM for any offer with damage
(the extractor marks it uncertain).
"""

from __future__ import annotations

import re

_I = re.IGNORECASE

_NEGATION = re.compile(r"(?:\bnie|\bbez|\bżadn\w*|\bbrak\w*)\s+(?:\w+\s+){0,2}$", _I)

_GAP = r"\s+(?:\w+\s+)?"
_BROKEN = r"uszkodz\w*|pęk\w*|złaman\w*|zbit\w*|rozbit\w*|nie działa\w*|do wymiany"


def _either(part: str, fault: str) -> re.Pattern[str]:
    """``fault part`` or ``part fault``, with at most one word between them."""
    return re.compile(rf"(?:{fault}){_GAP}(?:{part})|(?:{part}){_GAP}(?:{fault})", _I)


def _missing(part: str) -> re.Pattern[str]:
    return re.compile(rf"\b(?:brak|bez){_GAP}(?:{part})", _I)


DAMAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("screen", _either(r"matryc\w*|ekran\w*|wyświetlacz\w*", _BROKEN)),
    ("keyboard", _either(r"klawiatur\w*|klawisz\w*", _BROKEN)),
    ("touchpad", _either(r"touchpad\w*", _BROKEN)),
    ("battery", _either(r"bateri\w*", r"do wymiany|nie trzyma\w*|martw\w*|uszkodz\w*|spuchn\w*")),
    ("hinge", _either(r"zawias\w*", rf"{_BROKEN}|urwan\w*")),
    ("housing", _either(r"obudow\w*", r"pęk\w*|złaman\w*|uszkodz\w*")),
    ("charging_port", _either(r"gniazd\w*\s+(?:zasilani|ładowani)\w*",
                              r"uszkodz\w*|nie działa\w*|luźn\w*")),
    ("storage_missing", _missing(r"dysk\w*")),
    ("ram_missing", _missing(r"ram\w*|pamięci\s+ram")),
    ("charger_missing", _missing(r"zasilacz\w*|ładowark\w*")),
    ("os_missing", _missing(r"systemu")),
    ("bios_locked", _either(r"bios\w*", r"blokad\w*|hasł\w*|zablokowan\w*|na hasło")),
    ("motherboard", _either(r"płyt\w*\s+główn\w*", r"uszkodz\w*|spalon\w*|do naprawy")),
    ("gpu", re.compile(rf"artefakt\w*|reball\w*|(?:uszkodz|spalon)\w*{_GAP}"
                       r"(?:grafik\w*|kart\w* graficzn\w*|gpu)", _I)),
    ("no_power", re.compile(r"\bnie\s+(?:\w+\s+)?(?:włącza|uruchamia|startuje|odpala)"
                            r"|brak\s+(?:reakcji|obrazu)", _I)),
    ("liquid_damage", re.compile(r"zalan\w*|zalaniu", _I)),
)  # fmt: skip
"""Damage values (``categories.yaml`` laptop.damage) and how sellers phrase them."""

_NEGATED_DAMAGE = frozenset(
    {"storage_missing", "ram_missing", "charger_missing", "os_missing", "no_power"}
)
"""Patterns that already contain their own negation word: no negation check."""

FOR_PARTS = re.compile(r"\bna\s+częśc|\bdawca\b|\bdo\s+naprawy\b|\bniesprawn\w*|\buszkodzon\w*", _I)
"""Words that say the item as a whole is damaged / for parts (LLM decides which)."""

_JUNK_TITLE = re.compile(
    r"^\s*(?:(?:nowa|nowy|nowe|oryginaln\w*|orginaln\w*|sprawn\w*|używan\w*)\s+)?"
    r"(?:zasilacz|ładowarka|ladowarka|matryca|klawiatura|bateria|akumulator|płyta\s+główna|"
    r"obudowa|torba|plecak|podstawka|stacja\s+dokująca|replikator|dysk|pamięć|pamiec|kabel|"
    r"wentylator|radiator|zawias\w*|taśma|tasma|głośnik\w*|kamera|monitor|komputer\s+stacjonarny|"
    r"tablet|telefon|smartfon|myszka|mysz)\b",
    _I,
)
_LAPTOP_WORD = re.compile(
    r"laptop|notebook|macbook|thinkpad|latitude|elitebook|probook|ideapad|vivobook|zenbook|"
    r"inspiron|vostro|pavilion|aspire|legion|omen|rog\b|tuf\b|xps|surface|chromebook",
    _I,
)
_OTHER_DEVICE = re.compile(
    r"\b(?:tablet\w*|smartfon\w*|telefon\w*|konsol\w*|komputer\s+stacjonarny|monitor|"
    r"drukark\w*|iphone|ipad|galaxy\s+tab)\b",
    _I,
)
"""Another kind of device anywhere in the title (with no laptop word: "laptop 2w1 tablet"
stays a laptop)."""
_LAPTOP_WITH_EXTRA = re.compile(r"\b(?:do|dla|od|z)\s+(?:laptop|notebook|macbook)", _I)
"""'zasilacz do laptopa': the laptop word names what the accessory is for."""


def find_damage(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for name, pattern in DAMAGE_PATTERNS:
        for m in pattern.finditer(text):
            if name not in _NEGATED_DAMAGE and _NEGATION.search(
                text[max(0, m.start() - 30) : m.start()]
            ):
                continue
            found.append((m.start(), name))
            break
    return [name for _, name in sorted(found)]


def mentions_damage(text: str) -> bool:
    for m in FOR_PARTS.finditer(text):
        if not _NEGATION.search(text[max(0, m.start() - 30) : m.start()]):
            return True
    return False


def junk_title(title: str) -> bool:
    """The title names an accessory, part or another device as the item sold."""
    if _OTHER_DEVICE.search(title) and not _LAPTOP_WORD.search(title):
        return True
    if not _JUNK_TITLE.search(title):
        return False
    return not _LAPTOP_WORD.search(title) or _LAPTOP_WITH_EXTRA.search(title) is not None

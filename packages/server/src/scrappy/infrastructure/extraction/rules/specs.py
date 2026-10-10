"""Numeric laptop specs found in offer text (ADR 0012 tier 0).

Every finder returns all distinct candidates; the extractor decides (title first, then the
description, conflicts are dropped). Only plausible values are accepted, so "16" in
"i5-8gen/8/256/14"" is not taken for RAM and "144hz" is never a screen size.
"""

from __future__ import annotations

import re
from decimal import Decimal

_I = re.IGNORECASE

RAM_SIZES = frozenset({1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64, 96, 128})
STORAGE_SIZES_GB = frozenset(
    {16, 32, 64, 120, 128, 160, 180, 240, 250, 256, 275, 320, 480, 500, 512, 640, 750, 960,
     1000, 1024, 2000, 2048, 4000}
)  # fmt: skip
SCREEN_SIZES = frozenset(
    Decimal(s)
    for s in ("10.1", "11", "11.6", "12", "12.1", "12.3", "12.4", "12.5", "13", "13.3", "13.4",
              "13.5", "13.6", "13.9", "14", "14.1", "14.5", "15", "15.3", "15.4", "15.6", "16",
              "16.1", "17", "17.3", "18")
)  # fmt: skip
REFRESH_RATES = frozenset({60, 75, 90, 100, 120, 144, 165, 180, 240, 300, 360})

_UP_TO = re.compile(r"(?:\bdo|\bmax\.?|maks\w*|up to|rozbudow\w*(?: do)?)\s*$", _I)

_RAM_AFTER = re.compile(
    r"\b(\d{1,3})\s*gb\s*(?:-|\s)?\s*(?:ram\b|ddr\d|lpddr\d|pami[eę]ci|so-?dimm)", _I
)
_RAM_BEFORE = re.compile(r"\b(?:ram|pami[eę]ć|pami[eę]ci(?: ram)?)\b\s*[:\-]?\s*(\d{1,3})\s*gb", _I)
_SLASH_PAIR = re.compile(
    r"(?<![\d.,])(\d{1,2})\s*(?:gb)?\s*/\s*(\d{3,4}|[124])\s*(gb|tb)?(?![\d.,])", _I
)

_SIZE = r"(\d{1,4}(?:[.,]\d)?)\s*(gb|tb)"
_STORAGE_AFTER = re.compile(rf"\b{_SIZE}\s*(?:-|\s)?\s*(ssd|hdd|nvme|emmc|m\.?2|msata)\b", _I)
_STORAGE_BEFORE = re.compile(
    rf"\b(ssd|hdd|nvme|emmc|msata|dysk\w*(?:\s+twardy)?)\b[^\d\n]{{0,25}}?{_SIZE}", _I
)

_SCREEN_UNIT = re.compile(
    # inch marks: sellers type every kind of quote and prime
    r"(?<![\w.,])(1\d(?:[.,]\d{1,2})?)\s*"
    r"(?:\"|”|″|''|’|′|cal\w*|inch\w*|in\b|-?calowy)",  # noqa: RUF001
    _I,
)
_STORAGE_WORD_AFTER = re.compile(r"\s*(?:-|\s)?\s*(?:ssd|hdd|emmc|nvme|dysk|m\.?2)", _I)
_SCREEN_BARE = re.compile(
    r"(?<![\d.,])(1[0-8][.,]\d)(?![\d.,])(?!\s*(?:ghz|kg|mm|v\b|wh|%|gb|tb|mhz|cm|h\b))", _I
)
_REFRESH = re.compile(r"\b(\d{2,3})\s*hz\b", _I)
_RESOLUTION = re.compile(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b", _I)  # noqa: RUF001
_RES_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:fhd|full\s*-?\s*hd|1080p)\b(?!\s*\+)", _I), "1920x1080"),
    (re.compile(r"\b(?:wuxga|fhd\s*\+|fhd\+)", _I), "1920x1200"),
    (re.compile(r"\b(?:w?qhd|2k|1440p)\b", _I), "2560x1440"),
    (re.compile(r"\b(?:4k|uhd)\b(?!\s*graphics)", _I), "3840x2160"),
)
_BATTERY_WH = re.compile(r"(?<![\d.,])(\d{2,3}(?:[.,]\d)?)\s*wh\b", _I)
_RAM_WORD_AFTER = re.compile(r"\s*(?:-|\s)?\s*(?:ram\b|ddr|lpddr|pami[eę]c)", _I)


def _preceded_by_up_to(text: str, start: int) -> bool:
    return _UP_TO.search(text[max(0, start - 20) : start]) is not None


def _gb(value: str, unit: str) -> int | None:
    number = Decimal(value.replace(",", "."))
    gb = number * 1000 if unit.lower() == "tb" else number
    if gb != gb.to_integral_value():
        return None
    result = int(gb)
    if result == 1024:
        return 1000
    if result == 2048:
        return 2000
    return result


def find_ram(text: str) -> tuple[list[int], list[int]]:
    """``(installed, maximum)`` RAM sizes in GB. "do 32GB" counts as a maximum."""
    installed: list[int] = []
    maximum: list[int] = []
    # "8GB RAM 128GB SSD": the RAM word already belongs to the 8, so "RAM 128GB" is no match.
    used_words: list[tuple[int, int]] = []
    hits: list[tuple[int, int]] = []
    for m in _RAM_AFTER.finditer(text):
        used_words.append((m.end(1), m.end()))
        hits.append((m.start(), int(m.group(1))))
    for m in _RAM_BEFORE.finditer(text):
        if any(start <= m.start() < end for start, end in used_words):
            continue
        if _STORAGE_WORD_AFTER.match(text, m.end()):
            continue
        hits.append((m.start(1), int(m.group(1))))
    for start, value in sorted(hits):
        if value not in RAM_SIZES:
            continue
        target = maximum if _preceded_by_up_to(text, start) else installed
        if value not in target:
            target.append(value)
    return installed, maximum


def find_slash_pair(text: str) -> tuple[int, int] | None:
    """The ``8/256`` shorthand: RAM / storage in GB, only with plausible values."""
    for m in _SLASH_PAIR.finditer(text):
        ram = int(m.group(1))
        size = _gb(m.group(2), m.group(3) or ("tb" if len(m.group(2)) == 1 else "gb"))
        if ram in RAM_SIZES and size in STORAGE_SIZES_GB and ram < 128:
            return ram, size
    return None


def _storage_kind(word: str) -> str | None:
    word = word.lower()
    if word in ("ssd", "nvme", "m2", "m.2", "msata"):
        return "ssd"
    if word == "hdd":
        return "hdd"
    if word == "emmc":
        return "emmc"
    return None


def find_storage(text: str) -> list[tuple[int, str | None]]:
    """Distinct ``(size_gb, kind)`` drives; kind is ssd/hdd/emmc or None (just "dysk")."""
    found: list[tuple[int, int, str | None]] = []
    # Sizes already bound to the drive word after them: in "1TB HDD 240GB SSD" the 240
    # belongs to SSD, not to the HDD before it.
    taken: set[int] = set()

    def plausible(size: int | None, kind: str | None, end: int) -> bool:
        if size not in STORAGE_SIZES_GB:
            return False
        if size <= 64 and kind != "emmc":  # 16GB / 32GB next to "SSD" is usually RAM
            return False
        return _RAM_WORD_AFTER.match(text, end) is None

    for m in _STORAGE_AFTER.finditer(text):
        size, kind = _gb(m.group(1), m.group(2)), _storage_kind(m.group(3))
        if plausible(size, kind, m.end(2)) and size is not None:
            found.append((m.start(), size, kind))
            taken.add(m.start(1))
    for m in _STORAGE_BEFORE.finditer(text):
        size, kind = _gb(m.group(2), m.group(3)), _storage_kind(m.group(1))
        if (
            m.start(2) not in taken
            and plausible(size, kind, m.end(3))
            and size is not None
            and not _preceded_by_up_to(text, m.start(2))
        ):
            found.append((m.start(), size, kind))
    result: list[tuple[int, str | None]] = []
    for _, size, kind in sorted(found):
        same_size = [r for r in result if r[0] == size]
        if any(r[1] == kind or r[1] is None or kind is None for r in same_size):
            if kind is not None:  # upgrade an untyped duplicate
                result = [(s, kind if s == size and k is None else k) for s, k in result]
            continue
        result.append((size, kind))
    return result


def find_screens(text: str, *, allow_bare: bool) -> list[Decimal]:
    """Screen diagonals in inches. Bare numbers ("15,6") only where ``allow_bare``
    (titles, where a lone 15,6 is a screen; in a description it can be anything)."""
    found: list[tuple[int, Decimal]] = []
    patterns = (_SCREEN_UNIT, _SCREEN_BARE) if allow_bare else (_SCREEN_UNIT,)
    for pattern in patterns:
        for m in pattern.finditer(text):
            value = Decimal(m.group(1).replace(",", ".")).normalize()
            if value in SCREEN_SIZES:
                found.append((m.start(), value))
    result: list[Decimal] = []
    for _, value in sorted(found):
        if value not in result:
            result.append(value)
    return result


def find_refresh(text: str) -> list[int]:
    result: list[int] = []
    for m in _REFRESH.finditer(text):
        value = int(m.group(1))
        if value in REFRESH_RATES and value not in result:
            result.append(value)
    return result


def find_resolutions(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for m in _RESOLUTION.finditer(text):
        width, height = int(m.group(1)), int(m.group(2))
        if 1000 <= width <= 4000 and 600 <= height <= 2600 and width > height:
            found.append((m.start(), f"{width}x{height}"))
    for pattern, value in _RES_ALIASES:
        for m in pattern.finditer(text):
            found.append((m.start(), value))
    result: list[str] = []
    for _, value in sorted(found):
        if value not in result:
            result.append(value)
    return result


def find_battery_wh(text: str) -> list[Decimal]:
    result: list[Decimal] = []
    for m in _BATTERY_WH.finditer(text):
        value = Decimal(m.group(1).replace(",", ".")).normalize()
        if 20 <= value <= 100 and value not in result:
            result.append(value)
    return result

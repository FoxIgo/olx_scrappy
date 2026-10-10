"""OLX.pl laptop params (``offer.params``) as facts and as range checks (ADR 0012).

Exact params map to attribute values. Range params ("6GB - 12GB", "15-15,9\"") are not
facts; :func:`within_range` uses them to veto a parsed value. Unknown params or values
are ignored (no veto), so a site change degrades to "no help", never to wrong data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

STATE_PARAM = "state"
DISK_TYPE_PARAM = "harddisktype_laptops"
GPU_TYPE_PARAM = "graphicscardtype_laptops"
CPU_FAMILY_PARAM = "processorseries_laptops"
RAM_PARAM = "ramsize_laptops"
DISK_PARAM = "disksize_laptops"
SCREEN_PARAM = "screendiagonal_laptops"

_CONDITION = {
    "nowe": "new",
    "używane": "used",
    "odnowione / poleasingowe": "used",
    "powystawowe / outlet": "used",
    "uszkodzone": "damaged",
}
_STORAGE_TYPE = {"ssd": "ssd", "hdd": "hdd", "emmc": "emmc", "hdd + ssd": "ssd"}
_GPU_KIND = {"zintegrowana": "integrated", "dedykowana": "dedicated"}
MISSING_ONLY = frozenset({"storage_missing", "ram_missing", "charger_missing", "os_missing"})
"""Damage values that are just missing parts: a used offer with only these is not unclear."""

_CPU_FAMILY = {
    "intel core i3": re.compile(r"^i3-"),
    "intel core i5": re.compile(r"^i5-"),
    "intel core i7": re.compile(r"^i7-"),
    "intel core i9": re.compile(r"^i9-"),
    "amd ryzen 3": re.compile(r"^Ryzen 3 "),
    "amd ryzen 5": re.compile(r"^Ryzen 5 "),
    "amd ryzen 7": re.compile(r"^Ryzen 7 "),
    "amd ryzen 9": re.compile(r"^Ryzen 9 "),
    "intel pentium / celeron": re.compile(r"^(?:Pentium|Celeron) "),
}

_NUMBER = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"\s*(gb|tb|\"|”)?"
_RANGE = re.compile(rf"^{_NUMBER}{_UNIT}\s*-\s*{_NUMBER}{_UNIT}$", re.IGNORECASE)
_UP_TO = re.compile(rf"^(?:do|poniżej)\s*{_NUMBER}{_UNIT}$", re.IGNORECASE)
_AT_LEAST = re.compile(rf"^{_NUMBER}{_UNIT}\s*i\s*więcej$", re.IGNORECASE)
_EXACT = re.compile(rf"^{_NUMBER}{_UNIT}$", re.IGNORECASE)


def _value(params: Mapping[str, str], key: str) -> str | None:
    raw = params.get(key)
    return None if raw is None else raw.strip().casefold()


def condition(params: Mapping[str, str]) -> str | None:
    value = _value(params, STATE_PARAM)
    return None if value is None else _CONDITION.get(value)


def storage_type(params: Mapping[str, str]) -> str | None:
    value = _value(params, DISK_TYPE_PARAM)
    return None if value is None else _STORAGE_TYPE.get(value)


def storage_missing(params: Mapping[str, str]) -> bool:
    return _value(params, DISK_TYPE_PARAM) == "brak"


def gpu_kind(params: Mapping[str, str]) -> str | None:
    value = _value(params, GPU_TYPE_PARAM)
    return None if value is None else _GPU_KIND.get(value)


def cpu_matches_family(params: Mapping[str, str], cpu: str) -> bool:
    """False only when the site names a known family and the CPU is from another one."""
    value = _value(params, CPU_FAMILY_PARAM)
    pattern = None if value is None else _CPU_FAMILY.get(value)
    return pattern is None or pattern.search(cpu) is not None


def _number(text: str, unit: str | None) -> Decimal:
    value = Decimal(text.replace(",", "."))
    return value * 1000 if unit is not None and unit.lower() == "tb" else value


def bounds(raw: str) -> tuple[Decimal | None, Decimal | None] | None:
    """``"6GB - 12GB"`` -> (6, 12); ``"Do 4GB"`` -> (None, 4); unknown text -> None.

    Upper bounds of ``a-a,9`` screen buckets are inclusive of the whole inch (15-15,9 ->
    up to 15.99). ``Poniżej 11"`` is an exclusive bound, treated as inclusive (harmless).
    """
    text = raw.strip()
    if m := _RANGE.match(text):
        low = _number(m.group(1), m.group(2) or m.group(4))
        high = _number(m.group(3), m.group(4))
        if "," in m.group(3) or "." in m.group(3):
            high += Decimal("0.09")
        return low, high
    if m := _UP_TO.match(text):
        return None, _number(m.group(1), m.group(2))
    if m := _AT_LEAST.match(text):
        return _number(m.group(1), m.group(2)), None
    if m := _EXACT.match(text):
        value = _number(m.group(1), m.group(2))
        return value, value
    return None


def within_range(params: Mapping[str, str], key: str, value: int | Decimal) -> bool:
    raw = params.get(key)
    if raw is None:
        return True
    found = bounds(raw)
    if found is None:
        return True
    low, high = found
    number = Decimal(value)
    # Sellers pick the neighbouring bucket at the edges (128GB filed as "129GB - 256GB",
    # 512GB as "513GB - 999GB"), and "1TB" covers 960-1024GB drives: allow a 10% margin.
    return (low is None or number >= low * _LOW_MARGIN) and (
        high is None or number <= high * _HIGH_MARGIN
    )


_LOW_MARGIN = Decimal("0.9")
_HIGH_MARGIN = Decimal("1.1")

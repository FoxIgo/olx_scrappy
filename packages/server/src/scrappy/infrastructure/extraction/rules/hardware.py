"""CPU and GPU model names found in offer text (ADR 0012 tier 0).

Output is normalized raw text in the form the LLM prompt asks for ("i5-8265U",
"Ryzen 7 5800H", "RTX 3050 Ti"); the component resolver (ADR 0011) links it to a part.
Vague text ("i5", "GeForce") is not a model and is never returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.IGNORECASE

_INTEL_SUFFIX = r"(?:HQ|MQ|QM|HK|HS|HX|HF|U|H|G[1-7]|Y|M|P|K|T|KF|F)"
_INTEL_CORE = re.compile(
    rf"\bi([3579])\s*-?\s*(\d{{4,5}})(?:\s?({_INTEL_SUFFIX}))?(?![a-z0-9])", _I
)
_INTEL_ULTRA = re.compile(r"\bultra\s*([579])\s*-?\s*(\d{3})\s?([a-z]{1,2})?\b", _I)
_INTEL_LOW = re.compile(r"\b(celeron|pentium)\s*(?:silver|gold)?\s*([a-z]?\d{4}[a-z]?\d?)\b", _I)
_RYZEN = re.compile(
    r"\bryzen\s*([3579])\s*(?:pro\s*)?-?\s*(\d{4})\s?(HX|HS|H|U|G|GE|X3D|X)?(?![a-z0-9])", _I
)
_APPLE = re.compile(r"(?<![\w.])M([1-5])(?:\s*(Pro|Max|Ultra))?(?![\w.])")
_APPLE_CONTEXT = re.compile(r"macbook|apple|\bchip\b|imac", _I)
_NOT_APPLE_NEAR = re.compile(r"ssd|nvme|sata|dysk|slot|złącz|pcie", _I)

_NVIDIA = re.compile(
    r"\b(rtx|gtx|gt|mx)\s*-?\s*(\d{3,4})(m)?(?:\s*(ti|super))?(?![a-z0-9])"
    r"(?:\s*(?:max-?q)?\s*(\d{1,2})\s*gb)?",
    _I,
)
_RTX_PRO = re.compile(r"\brtx\s*a(\d{3,4})\b", _I)
_QUADRO = re.compile(r"\bquadro\s*(nvs\s*\d{3,4}m?|[a-z]{1,2}\d{3,4}m?)\b", _I)
_GEFORCE_BARE = re.compile(r"\bgeforce\s*(\d{3,4})\s?(mx|m)?(?![a-z0-9])", _I)
_RADEON_OLD = re.compile(r"\bradeon\s*(?:(r[5-9])\s*(m?\d{3}x?m?)|hd\s*(\d{4}m?))\b", _I)
GPU_WORDS = re.compile(
    r"geforce|nvidia|radeon|quadro|\brtx|\bgtx|grafik|karta graficzna|\bgpu\b", _I
)
"""Text that talks about a GPU; without it a missing GPU model is no reason for the LLM."""
_AMD_RX = re.compile(r"\b(?:radeon\s*)?rx\s*-?\s*(\d{3,4})\s?(m|s|xt)?\b(?:\s*(\d{1,2})\s*gb)?", _I)
_RADEON_IGPU = re.compile(r"\bradeon\s*(\d{3})m\b", _I)
_INTEL_IGPU = re.compile(
    r"\b(iris\s*xe|iris\s*plus|iris\s*pro|(?:u?hd)\s*graphics\s*\d{3,4})\b", _I
)


@dataclass(frozen=True, slots=True)
class GpuMatch:
    name: str
    dedicated: bool
    vram_gb: int | None = None


def _unique(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


def find_cpus(text: str) -> list[str]:
    """Distinct CPU models in order of appearance."""
    found: list[tuple[int, str]] = []
    for m in _INTEL_CORE.finditer(text):
        suffix = (m.group(3) or "").upper()
        found.append((m.start(), f"i{m.group(1)}-{m.group(2)}{suffix}"))
    for m in _INTEL_ULTRA.finditer(text):
        found.append(
            (m.start(), f"Core Ultra {m.group(1)} {m.group(2)}{(m.group(3) or '').upper()}")
        )
    for m in _INTEL_LOW.finditer(text):
        found.append((m.start(), f"{m.group(1).capitalize()} {m.group(2).upper()}"))
    for m in _RYZEN.finditer(text):
        found.append((m.start(), f"Ryzen {m.group(1)} {m.group(2)}{(m.group(3) or '').upper()}"))
    if _APPLE_CONTEXT.search(text):
        for m in _APPLE.finditer(text):
            near = text[max(0, m.start() - 12) : m.end() + 12]
            if _NOT_APPLE_NEAR.search(near):
                continue
            variant = f" {m.group(2).capitalize()}" if m.group(2) else ""
            found.append((m.start(), f"M{m.group(1)}{variant}"))
    return _unique([name for _, name in sorted(found)])


def find_gpus(text: str) -> list[GpuMatch]:
    """Distinct GPUs in order of appearance (dedicated and integrated)."""
    found: list[tuple[int, GpuMatch]] = []
    for m in _NVIDIA.finditer(text):
        family = m.group(1).upper()
        number = m.group(2)
        if family in ("GT", "MX") and len(number) != 3:
            continue
        mobile = "M" if m.group(3) else ""
        variant = f" {m.group(4).capitalize()}" if m.group(4) else ""
        vram = int(m.group(5)) if m.group(5) else None
        found.append((m.start(), GpuMatch(f"{family} {number}{mobile}{variant}", True, vram)))
    for m in _RTX_PRO.finditer(text):
        found.append((m.start(), GpuMatch(f"RTX A{m.group(1)}", True)))
    for m in _QUADRO.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).upper()
        found.append((m.start(), GpuMatch(f"Quadro {name}", True)))
    for m in _GEFORCE_BARE.finditer(text):
        found.append(
            (m.start(), GpuMatch(f"GeForce {m.group(1)}{(m.group(2) or '').upper()}", True))
        )
    for m in _RADEON_OLD.finditer(text):
        if m.group(3):
            found.append((m.start(), GpuMatch(f"Radeon HD {m.group(3).upper()}", True)))
        else:
            found.append(
                (m.start(), GpuMatch(f"Radeon {m.group(1).upper()} {m.group(2).upper()}", True))
            )
    for m in _AMD_RX.finditer(text):
        suffix = (m.group(2) or "").upper()
        vram = int(m.group(3)) if m.group(3) else None
        found.append((m.start(), GpuMatch(f"RX {m.group(1)}{suffix}", True, vram)))
    for m in _RADEON_IGPU.finditer(text):
        found.append((m.start(), GpuMatch(f"Radeon {m.group(1)}M", False)))
    for m in _INTEL_IGPU.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        name = re.sub(r"(?i)^iris", "Iris", name)
        name = re.sub(r"(?i)\bxe\b", "Xe", name)
        name = re.sub(r"(?i)\bplus\b", "Plus", name)
        name = re.sub(r"(?i)\bpro\b", "Pro", name)
        name = re.sub(r"(?i)^uhd graphics", "UHD Graphics", name)
        name = re.sub(r"(?i)^hd graphics", "HD Graphics", name)
        found.append((m.start(), GpuMatch(f"Intel {name}", False)))
    result: dict[str, GpuMatch] = {}
    for _, gpu in sorted(found, key=lambda item: item[0]):
        known = result.get(gpu.name)
        if known is None or (known.vram_gb is None and gpu.vram_gb is not None):
            result[gpu.name] = gpu
    return list(result.values())

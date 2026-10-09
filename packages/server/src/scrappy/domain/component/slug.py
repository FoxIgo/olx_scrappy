"""Component name normalization: free text -> a stable slug.

``component_slug`` is the one function that turns "NVIDIA GeForce RTX 4060 Laptop GPU",
"rtx4060 laptop" or "12th Gen Intel(R) Core(TM) i5-12450H @ 2.50GHz" into the slug used to
match benchmark names, aliases and (slice 3) the free-text CPU/GPU of an offer.

Rules (pure, deterministic, idempotent on its own output):

* lower-case; ``(R)``/``(TM)`` marks, ``@ x.xGHz``, ``N-Core`` and "Nth Gen" are dropped;
* marketing words are dropped: vendor names, "GeForce", "Processor", "CPU", "Graphics",
  "GPU", "with Radeon Graphics", "Series", "Design" ...;
* ``Radeon`` is dropped before ``RX``; ``Core`` is dropped before ``iN`` (kept in
  "Core Ultra 7 155H");
* GPU brand prefixes glued to digits are split (``rtx3050ti`` -> ``rtx-3050-ti``);
* ``Mobile``/``Notebook``/``Laptop`` all mean ``laptop`` and ``Max-Q`` becomes ``maxq``.
  Both go to the END of the slug, so "RTX 4060" and "RTX 4060 Laptop GPU" are different
  components while "Laptop RTX 4060" equals the latter;
* memory sizes are kept (``6gb``): "RTX 3050 6GB Laptop" is silicon different from
  "RTX 3050 Laptop".
"""

from __future__ import annotations

import re

_NOISE_PHRASES = re.compile(
    r"""
    \(r\) | \(tm\) | \(c\) | [®™]
  | @\s*\d+(?:[.,]\d+)?\s*ghz | \b\d+(?:[.,]\d+)?\s*ghz\b
  | \b\d+(?:st|nd|rd|th)\s+gen\b
  | \b\d+\s*-\s*core\b | \b\d+\s*core\b
  | \bwith\s+radeon\s+(?:graphics|vega)\b
  | \bwith\s+max-?q\b | \bmax-?q(?:\s+design)?\b
  """,
    re.IGNORECASE | re.VERBOSE,
)
_DROP_WORDS = frozenset(
    {
        "nvidia",
        "geforce",
        "amd",
        "ati",
        "intel",
        "apple",
        "corporation",
        "processor",
        "processors",
        "cpu",
        "gpu",
        "graphics",
        "series",
        "design",
        "with",
        "edition",
        "gen",
        "generation",
    }
)
_LAPTOP_WORDS = frozenset({"laptop", "mobile", "notebook"})
_GPU_PREFIX = re.compile(r"^(gtx|rtx|gts|gt|rx|mx)(\d.*)$")
_GPU_SUFFIX = re.compile(r"^(\d+)(ti|super|xt|xtx)$")
_SPLIT = re.compile(r"[^a-z0-9]+")


def component_slug(text: str, kind: str) -> str:
    """The slug of a ``"cpu"`` or ``"gpu"`` name; ``""`` when nothing identifying is left."""
    cleaned = _NOISE_PHRASES.sub(" ", text.lower())
    has_maxq = bool(re.search(r"max-?q", text.lower()))
    tokens = [t for t in _SPLIT.split(cleaned) if t]
    tokens = _expand_gpu_tokens(tokens) if kind == "gpu" else tokens
    laptop = any(t in _LAPTOP_WORDS for t in tokens)
    tokens = [t for t in tokens if t not in _DROP_WORDS and t not in _LAPTOP_WORDS]
    tokens = _drop_context_words(tokens)
    tokens = list(dict.fromkeys(tokens)) if kind == "gpu" else tokens
    if not tokens:
        return ""
    if laptop:
        tokens.append("laptop")
    if has_maxq:
        tokens.append("maxq")
    return "-".join(tokens)


def _expand_gpu_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for token in tokens:
        match = _GPU_PREFIX.match(token)
        parts = [match[1], match[2]] if match else [token]
        for part in parts:
            suffixed = _GPU_SUFFIX.match(part)
            out.extend([suffixed[1], suffixed[2]] if suffixed else [part])
    return out


def _drop_context_words(tokens: list[str]) -> list[str]:
    """``radeon`` before ``rx`` and ``core`` before ``i3/i5/i7/i9`` add nothing."""
    out: list[str] = []
    for index, token in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token == "radeon" and following == "rx":
            continue
        if token == "core" and re.fullmatch(r"i[3579]", following):
            continue
        out.append(token)
    return out


def alias_text(text: str) -> str:
    """Alias key: the original text lower-cased with collapsed whitespace."""
    return " ".join(text.lower().split())


def is_identifying_slug(slug: str) -> bool:
    """A slug with a model number. "AMD Radeon Graphics" (``radeon``) names no part."""
    return any(ch.isdigit() for ch in slug)

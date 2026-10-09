"""Deterministic preparation of LLM input from a stored offer (ADR 0007 step 1)."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from scrappy.application.ports.extractor import ExtractionInput
from scrappy.domain.category import CategoryCatalog
from scrappy.domain.offer import Offer
from scrappy.domain.shared import InvalidValueError

_BLOCK_TAGS = frozenset(
    {"br", "p", "div", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SKIP_TAGS = frozenset({"script", "style"})
_INLINE_SPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


class _TextExtractor(HTMLParser):
    def __init__(self, *, newlines_are_whitespace: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._newlines_are_whitespace = newlines_are_whitespace

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS and tag != "br":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data.replace("\n", " ") if self._newlines_are_whitespace else data)


def strip_html(text: str) -> str:
    """Remove tags (block tags and ``<br>`` become line breaks), decode entities.

    If the text contains markup, raw newlines are HTML whitespace (OLX sends ``<br />\n``,
    which must not become two line breaks). Plain text keeps its newlines.
    """
    parser = _TextExtractor(newlines_are_whitespace=_TAG.search(text) is not None)
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs, trim lines, keep at most one blank line in a row."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut to at most ``max_chars``, preferably at a whitespace boundary in the last 20%."""
    if len(text) <= max_chars:
        return text, False
    cut = text[:max_chars]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary >= int(max_chars * 0.8):
        cut = cut[:boundary]
    return cut.rstrip(), True


def prepare_description(raw: str, max_chars: int) -> tuple[str, bool]:
    return truncate(normalize_whitespace(strip_html(raw)), max_chars)


def prepare_extraction_input(
    offer: Offer, catalog: CategoryCatalog, *, max_chars: int
) -> ExtractionInput:
    """Build the LLM input. Same offer + catalog + limit always give the same input.

    All catalog categories are candidates: classification is per offer, independent of
    which searches found it (ADR 0007), so it must not depend on the searches.
    """
    if offer.description is None or offer.content_hash is None:
        raise InvalidValueError(f"offer {offer.id} has no content to extract from yet")
    description, truncated = prepare_description(offer.description, max_chars)
    return ExtractionInput(
        offer_id=offer.id,
        content_hash=offer.content_hash,
        title=normalize_whitespace(offer.title or ""),
        description=description,
        description_truncated=truncated,
        params=tuple((key, normalize_whitespace(value)) for key, value in (offer.params or ())),
        price=offer.price,
        categories=tuple(catalog),
    )

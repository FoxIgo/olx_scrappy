import pytest

from scrappy.application.extraction.prepare import (
    normalize_whitespace,
    prepare_description,
    prepare_extraction_input,
    strip_html,
    truncate,
)
from scrappy.domain.offer import Offer
from scrappy.domain.shared import InvalidValueError
from tests.unit.builders import LAPTOP, PHONE, at, catalog, details, listing


def test_olx_br_markup_becomes_single_line_breaks() -> None:
    raw = "Laptop w dobrym stanie<br />\nRAM: 16 GB<br />\n<br />\nCena do negocjacji &amp; wysyłka"
    assert prepare_description(raw, 1000) == (
        "Laptop w dobrym stanie\nRAM: 16 GB\n\nCena do negocjacji & wysyłka",
        False,
    )


def test_plain_text_keeps_newlines() -> None:
    assert strip_html("a\nb") == "a\nb"


def test_scripts_and_styles_are_dropped() -> None:
    assert (
        normalize_whitespace(strip_html("<p>x</p><script>alert(1)</script><style>p{}</style>"))
        == "x"
    )


def test_whitespace_normalization() -> None:
    assert normalize_whitespace("  a \t b \r\n\n\n\n c  ") == "a b\n\nc"


def test_truncate_prefers_word_boundary() -> None:
    text = "word " * 100
    cut, truncated = truncate(text, 52)
    assert truncated
    assert len(cut) <= 52
    assert cut.endswith("word")


def test_truncate_short_text_untouched() -> None:
    assert truncate("short", 100) == ("short", False)


def test_input_is_deterministic_and_complete() -> None:
    offer = Offer.from_observation(
        details("1", description="<b>GTX</b>  1650", params={"state": "used", "brand": "Dell"}),
        at(0),
    )
    first = prepare_extraction_input(offer, catalog(), max_chars=200)
    second = prepare_extraction_input(offer, catalog(), max_chars=200)
    assert first == second
    assert first.description == "GTX 1650"
    assert first.params == (("brand", "Dell"), ("state", "used"))
    assert [c.name for c in first.categories] == [LAPTOP, PHONE]
    assert first.content_hash == offer.content_hash


def test_input_requires_content() -> None:
    with pytest.raises(InvalidValueError):
        prepare_extraction_input(
            Offer.from_observation(listing("1"), at(0)), catalog(), max_chars=200
        )

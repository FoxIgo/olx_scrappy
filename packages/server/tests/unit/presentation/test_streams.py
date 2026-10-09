"""Redirected output on Windows uses the ANSI code page; Polish text must not crash it."""

from __future__ import annotations

import io

from scrappy.presentation.cli.render import configure_streams


def test_redirected_stream_becomes_utf8() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1251")
    configure_streams([stream])
    stream.write("Częstochowa, Śląskie")
    stream.flush()
    assert raw.getvalue().decode("utf-8") == "Częstochowa, Śląskie"


def test_streams_without_reconfigure_are_left_alone() -> None:
    configure_streams([io.StringIO()])


def test_offer_detail_shows_the_description_without_html() -> None:
    from rich.console import Console

    from scrappy.domain.offer import Offer
    from scrappy.presentation.cli.render import offer_detail
    from tests.unit.builders import T0, details

    offer = Offer.from_observation(
        details("1", description="Sprzedam laptop<br />\nStan: bardzo dobry &amp; czysty"), T0
    )
    console = Console(record=True, width=100)
    console.print(offer_detail(offer, None, [], []))
    text = console.export_text()
    assert "<br" not in text
    assert "&amp;" not in text
    assert "bardzo dobry & czysty" in text

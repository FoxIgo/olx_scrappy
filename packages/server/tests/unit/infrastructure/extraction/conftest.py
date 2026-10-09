from __future__ import annotations

from scrappy.application.ports.extractor import ExtractionInput
from scrappy.domain.offer import ContentHash, Price
from tests.unit.builders import catalog, oid

HASH = ContentHash("a" * 64)


def make_input(
    description: str = "Laptop Asus, GTX 1650, 16GB RAM, SSD 512GB",
    title: str = "Laptop Asus",
) -> ExtractionInput:
    return ExtractionInput(
        offer_id=oid("1"),
        content_hash=HASH,
        title=title,
        description=description,
        description_truncated=False,
        params=(("state", "used"),),
        price=Price.fixed(1200),
        categories=tuple(catalog()),
    )

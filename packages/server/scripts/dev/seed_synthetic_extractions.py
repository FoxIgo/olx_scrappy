"""Build the SYNTHETIC evaluation database data/eval/scrappy.db from the real e2e scrape.

Dev/test tooling only (not product code): the heuristics below are regexes over title,
params and description that stand in for the LLM, so agents testing the `scrappy q` skill
get realistic extraction data without an OpenRouter key.

What it does (everything goes through the application's own code paths):

1. Copies data/e2e/scrappy.db -> data/eval/scrappy.db (SQLite backup API, overwrites).
2. Adds the saved search ``rtx-laptops`` and links a set of offers to it (repositories).
3. Replays every offer through the real ``ExtractOfferHandler`` with a scripted extractor
   (``HeuristicExtractor``): validation, provenance, ``needs_extraction`` compatibility and
   derived relevance on every search link all come from the real handler.
4. Adds price history: a later "run" saw a lower price for ~10 offers
   (``Offer.apply`` + ``snapshot_for`` + ``OfferRepository.add_snapshot``).

Run from packages/server:  uv run python scripts/dev/seed_synthetic_extractions.py
Point the app at it:       SCRAPPY_DATA_DIR=<repo>/data/eval
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from scrappy.application.jobs.handlers.extract_offer import ExtractOfferHandler
from scrappy.application.jobs.model import ExtractOfferPayload, Job, JobId
from scrappy.application.ports.extractor import ExtractionInput, ExtractionResult
from scrappy.domain.category import CategoryName
from scrappy.domain.offer import (
    ObservationLevel,
    Offer,
    OfferObservation,
    OfferSnapshot,
    Price,
    PriceKind,
    snapshot_for,
)
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.infrastructure.config.settings import Settings
from scrappy.main import build_app

SERVER_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = SERVER_DIR.parent.parent
SRC_DB = REPO_DIR / "data" / "e2e" / "scrappy.db"
EVAL_DIR = REPO_DIR / "data" / "eval"
EVAL_DB = EVAL_DIR / "scrappy.db"

MODEL = "synthetic-seed"
PROMPT_VERSION = "seed-v1"
RTX_SEARCH = SearchName("rtx-laptops")
RTX_URL = "https://www.olx.pl/oferty/q-rtx-3050-laptop/"
RTX_LINKS_TARGET = 20
PRICE_HISTORY_OFFERS = 10

# ----------------------------------------------------------------------------- heuristics

_HTML = re.compile(r"<[^>]+>")
_PART_TITLE = re.compile(
    r"^\W*(płyta|plyta|karta graficzna|zasilacz|ładowarka|ladowarka|matryca|bateria|klawiatura"
    r"|obudowa|etui|torba|plecak)\b",
    re.I,
)
_DESKTOP = re.compile(r"\b(komputer\w*|stacjonarn\w*|desktop|pc)\b", re.I)
_LAPTOP = re.compile(r"\b(laptop\w*|notebook\w*)\b", re.I)
_BARE_GPU_CARD = re.compile(r"low profile|gddr\d|^\W*(gigabyte|msi|zotac|palit)\s+geforce", re.I)

_GPU = re.compile(r"\b(GTX|RTX)\s*-?\s*(\d{3,4})\s*(M\b|MX|Ti\b|TI\b|Super\b|SUPER\b)?", re.I)
_GPU_MX = re.compile(r"\bMX\s*(\d{3})\b", re.I)
_GPU_PHRASE = re.compile(
    r"(?:\b(?:GTX|RTX)\s*-?\s*\d{3,4}\s*(?:M|MX|Ti|Super)?|\b(?:NVIDIA|GeForce)\b)"
    r"[\s,|/-]*(?:\d{1,2}\s*(?:GB|ГБ)(?!\s*(?:RAM|ram|DDR|SSD|HDD|NVMe)))?",
    re.I,
)
_INTEL = re.compile(r"\bi([3579])\s*-?\s*(\d{4,5})(G\d)?([A-Z]{0,2})\b", re.I)
_RYZEN = re.compile(r"\b(?:Ryzen|R)\s*([3579])\s*[-/ ]?\s*(\d{4}[A-Z]{0,2})\b", re.I)
_RAM_UNIT = r"(?:GB|Gb|gb|GIGA|ГБ)"
_RAM_BEFORE = re.compile(rf"\b(\d{{1,3}})\s*{_RAM_UNIT}\s*(?:DDR\d|RAM|ramu?|pami[eę]ci)", re.I)
_RAM_AFTER = re.compile(rf"\b(?:RAM|ram|pami[eę][cć] RAM)\s*:?\s*(\d{{1,3}})\s*{_RAM_UNIT}", re.I)
_RAM_SLASH = re.compile(rf"\b(4|8|12|16|24|32|64)\s*/\s*(\d{{3,4}})\s*(?:{_RAM_UNIT}|\b)", re.I)
_BARE_GB = re.compile(rf"\b(\d{{1,3}})\s*{_RAM_UNIT}\b")
_DRIVE_WORD = r"(?:SSD|NVMe|M\.?\s?2|HDD|dysk\w*|ГБ)"
_STORAGE_AFTER = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(GB|Gb|gb|TB|Tb|tb|G|T|ГБ)\s*(?:dysk\w*\s*)?(SSD|NVMe|M\.?\s?2|HDD)",
    re.I,
)
_STORAGE_BEFORE = re.compile(
    r"\b(SSD|NVMe|M\.?\s?2|HDD)\s*:?\s*(\d+(?:[.,]\d+)?)\s*(GB|Gb|gb|TB|Tb|tb|G|T|ГБ)?\b", re.I
)
_STORAGE_VALUES = {120, 128, 240, 250, 256, 480, 500, 512, 750, 960, 1000, 2000}
_SCREEN = re.compile(r"\b(1[1-9](?:[.,]\d)?)\s*(?:\"|”|″|''|cal\w*|inch\w*|-inch)", re.I)
_FOR_PARTS = re.compile(r"(?<!nie )\bna\s+cz[eę][sś]ci\b", re.I)
_STATE = {"Używane": "used", "Nowe": "new", "Uszkodzone": "damaged"}
_SERIES = {
    "Intel Core i3": "Core i3",
    "Intel Core i5": "Core i5",
    "Intel Core i7": "Core i7",
    "Intel Core i9": "Core i9",
    "AMD Ryzen 3": "Ryzen 3",
    "AMD Ryzen 5": "Ryzen 5",
    "AMD Ryzen 7": "Ryzen 7",
    "AMD Ryzen 9": "Ryzen 9",
}
_EXACT_RAM = {"16GB": 16, "32GB": 32, "24GB": 24, "Do 4GB": None, "6GB - 12GB": None}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", _HTML.sub(" ", html)).strip()


def _gpu(text: str) -> str | None:
    for match in _GPU.finditer(text):
        family, number, suffix = match.group(1).upper(), match.group(2), match.group(3) or ""
        suffix = suffix.strip()
        if suffix.upper() == "TI":
            suffix = " Ti"
        elif suffix.upper() == "SUPER":
            suffix = " Super"
        elif suffix:
            suffix = suffix.upper()
        return f"{family} {number}{suffix}"
    mx = _GPU_MX.search(text)
    return f"MX{mx.group(1)}" if mx else None


def _cpu(text: str, params: dict[str, str]) -> str | None:
    intel = _INTEL.search(text)
    if intel:
        return f"i{intel.group(1)}-{intel.group(2)}{(intel.group(3) or '').upper()}{intel.group(4).upper()}"
    ryzen = _RYZEN.search(text)
    if ryzen:
        return f"Ryzen {ryzen.group(1)} {ryzen.group(2).upper()}"
    return _SERIES.get(params.get("processorseries_laptops", ""))


def _ram(title_desc: str, params: dict[str, str]) -> int | None:
    text = _GPU_PHRASE.sub(" ", title_desc)
    for pattern in (_RAM_BEFORE, _RAM_AFTER):
        match = pattern.search(text)
        if match and 2 <= int(match.group(1)) <= 128:
            return int(match.group(1))
    slash = _RAM_SLASH.search(text)
    if slash:
        return int(slash.group(1))
    exact = _EXACT_RAM.get(params.get("ramsize_laptops", ""))
    if exact:
        return exact
    candidates = [
        int(m.group(1))
        for m in _BARE_GB.finditer(text)
        if int(m.group(1)) in (4, 6, 8, 12, 16, 20, 24, 32, 64)
        and not re.match(r"\s*(?:SSD|HDD|NVMe|M\.?2|dysk)", text[m.end() :], re.I)
    ]
    return candidates[0] if len(set(candidates)) == 1 else None


def _to_gb(number: str, unit: str | None) -> int | None:
    value = Decimal(number.replace(",", "."))
    if unit and unit.upper().startswith("T"):
        value *= 1000
    gb = int(value)
    return gb if gb in _STORAGE_VALUES else None


def _storage(title_desc: str, params: dict[str, str]) -> tuple[int | None, str | None]:
    text = _GPU_PHRASE.sub(" ", title_desc)
    size: int | None = None
    kind: str | None = None
    slash = _RAM_SLASH.search(text)
    if slash:
        size = _to_gb(slash.group(2), "GB")
    hits: list[tuple[int | None, str]] = []
    for m in _STORAGE_AFTER.finditer(text):
        hits.append((_to_gb(m.group(1), m.group(2)), m.group(3)))
    for m in _STORAGE_BEFORE.finditer(text):
        unit = m.group(3) or ("GB" if int(Decimal(m.group(2).replace(",", "."))) >= 100 else "TB")
        hits.append((_to_gb(m.group(2), unit), m.group(1)))
    ordered = sorted(hits, key=lambda h: 0 if re.match(r"ssd|nvme|m", h[1], re.I) else 1)
    for hit_size, hit_kind in ordered:
        if hit_size is not None:
            size = hit_size
            kind = "ssd" if re.match(r"ssd|nvme|m", hit_kind, re.I) else "hdd"
            break
    if kind is None:
        if re.search(r"\b(SSD|NVMe)\b|\bM\.?2\b", text, re.I):
            kind = "ssd"
        elif re.search(r"\bHDD\b", text, re.I):
            kind = "hdd"
        elif re.search(r"emmc", text, re.I):
            kind = "emmc"
        else:
            kind = {"SSD": "ssd", "HDD": "hdd", "HDD + SSD": "ssd"}.get(
                params.get("harddisktype_laptops", "")
            )
    if size is None:
        size = {"1TB": 1000, "2TB": 2000}.get(params.get("disksize_laptops", ""))
    return size, kind


def _screen(text: str) -> Decimal | None:
    for match in _SCREEN.finditer(text):
        value = Decimal(match.group(1).replace(",", "."))
        if Decimal(11) <= value <= Decimal("18.9"):
            return value
    return None


def _condition(title_desc: str, params: dict[str, str]) -> str | None:
    if _FOR_PARTS.search(title_desc):
        return "for_parts"
    return _STATE.get(params.get("state", ""))


def _is_other(title: str, params: dict[str, str]) -> bool:
    if _PART_TITLE.search(title) or _BARE_GPU_CARD.search(title):
        return not _LAPTOP.search(title) or bool(_PART_TITLE.search(title))
    if _DESKTOP.search(title) and not _LAPTOP.search(title):
        return True
    has_desktop_params = any(key.endswith("_desktops") for key in params)
    has_laptop_params = any(key.endswith("_laptops") for key in params)
    return has_desktop_params and not has_laptop_params


class HeuristicExtractor:
    """Scripted ``AttributeExtractor``: regexes instead of an LLM (synthetic data only)."""

    async def extract(self, request: ExtractionInput) -> ExtractionResult:
        params = dict(request.params)
        if _is_other(request.title, params):
            return ExtractionResult(
                CategoryName("other"), {}, MODEL, PROMPT_VERSION, notes="synthetic: not a laptop"
            )
        text = f"{request.title} . {request.description}"
        # Title wins over the description for the GPU/CPU, which is where sellers put them.
        gpu = _gpu(request.title) or _gpu(request.description)
        cpu = _cpu(request.title, params) or _cpu(request.description, params)
        screen = _screen(request.title) or _screen(request.description)
        size, kind = _storage(f"{request.title} . {request.description}", params)
        ram = _ram(request.title, {}) or _ram(text, params)
        attributes: dict[str, object] = {
            "gpu": gpu,
            "cpu": cpu,
            "ram_gb": ram,
            "storage_gb": size,
            "storage_type": kind,
            "screen_in": str(screen) if screen is not None else None,
            "condition": _condition(text, params),
        }
        return ExtractionResult(
            CategoryName("laptop"), attributes, MODEL, PROMPT_VERSION, notes="synthetic: regex"
        )


# ----------------------------------------------------------------------------- seeding


def copy_database() -> None:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{EVAL_DB}{suffix}").unlink(missing_ok=True)
    src = sqlite3.connect(SRC_DB)
    dst = sqlite3.connect(EVAL_DB)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    raw_src, raw_dst = SRC_DB.parent / "raw", EVAL_DIR / "raw"
    if raw_src.exists() and not raw_dst.exists():
        shutil.copytree(raw_src, raw_dst)


def _lower_price(price: Price, factor: Decimal) -> Price | None:
    if price.kind is not PriceKind.FIXED or price.amount is None:
        return None
    new = (price.amount.amount * factor / 10).to_integral_value() * 10
    if new >= price.amount.amount or new <= 0:
        return None
    return Price.fixed(new, price.amount.currency, negotiable=price.negotiable)


async def seed() -> None:
    copy_database()
    settings = Settings(data_dir=EVAL_DIR, config_dir=SERVER_DIR / "config")
    app = await build_app(settings, sources={}, extractor=HeuristicExtractor())
    try:
        catalog = await app.categories.catalog()
        now = app.clock.now()

        # -- all offers
        offers: list[Offer] = []
        after = None
        async with app.uow() as uow:
            while True:
                page = await uow.offers.list_with_content(after=after, limit=200)
                if not page:
                    break
                offers.extend(page)
                after = page[-1].id

        # -- second saved search + links (before extraction, so the handler derives relevance)
        def mentions_rtx(offer: Offer) -> bool:
            return bool(
                re.search(r"\bRTX\b", f"{offer.title} {_plain(offer.description or '')}", re.I)
            )

        rtx_hits = [o for o in offers if mentions_rtx(o)]
        fillers = [
            o for o in offers if o not in rtx_hits and re.search(r"\blaptop", o.title or "", re.I)
        ]
        fillers.sort(key=lambda o: str(o.id))
        linked = (rtx_hits + fillers)[:RTX_LINKS_TARGET]
        async with app.uow() as uow:
            await uow.searches.save(
                SavedSearch(
                    RTX_SEARCH, linked[0].id.source, RTX_URL, CategoryName("laptop"), created_at=now
                )
            )
            for offer in linked:
                await uow.search_offers.save(SearchOffer.first_seen(RTX_SEARCH, offer.id, now))
            await uow.commit()

        # -- extraction through the real handler
        handler = ExtractOfferHandler(
            uow=app.uow,
            extractor=HeuristicExtractor(),
            categories=app.categories,
            clock=app.clock,
            policy=app.policy,
        )
        for index, offer in enumerate(offers):
            assert offer.content_hash is not None
            job = Job.new(
                JobId(f"seed-{index}"),
                ExtractOfferPayload(offer.id, offer.content_hash, catalog.fingerprint),
                run_id=None,
                now=now,
            )
            await handler.handle(job)

        # -- price history: a later run saw a lower price for ~10 offers
        history: list[tuple[str, str, str, str]] = []
        candidates = [
            o for o in offers if o.price is not None and _lower_price(o.price, Decimal("0.9"))
        ]
        candidates.sort(key=lambda o: str(o.id))
        step = max(1, len(candidates) // PRICE_HISTORY_OFFERS)
        chosen = candidates[::step][:PRICE_HISTORY_OFFERS]
        async with app.uow() as uow:
            for number, offer in enumerate(chosen):
                stored = await uow.offers.get(offer.id)
                assert stored is not None and stored.price is not None
                factors = [Decimal("0.9")] + ([Decimal("0.95")] if number < 3 else [])
                for drop, factor in enumerate(factors):
                    lower = _lower_price(stored.price, factor)
                    if lower is None:
                        continue
                    at = now - timedelta(hours=2 - drop)
                    old = stored.price
                    changes = stored.apply(
                        OfferObservation(stored.id, ObservationLevel.LISTING, price=lower), at
                    )
                    snapshot: OfferSnapshot | None = snapshot_for(stored.id, changes, at)
                    if snapshot is not None:
                        await uow.offers.add_snapshot(snapshot)
                        history.append((str(stored.id), str(old), str(lower), at.isoformat()))
                await uow.offers.save(stored)
            await uow.commit()

        await report(app, linked, history)
    finally:
        await app.aclose()


async def report(app, linked: list[Offer], history: list[tuple[str, str, str, str]]) -> None:
    async with app.uow() as uow:
        ids = [o.id for o in linked]
        offers = []
        after = None
        while True:
            page = await uow.offers.list_with_content(after=after, limit=200)
            if not page:
                break
            offers.extend(page)
            after = page[-1].id
        latest = await uow.extractions.latest_many([o.id for o in offers])
        searches = await uow.searches.list_all()
        snapshots = 0
        for o in offers:
            snapshots += len(await uow.offers.list_snapshots(o.id))
        links = {s.name.value: 0 for s in searches}
        relevant: Counter[str] = Counter()
        for offer in offers:
            for link in await uow.search_offers.list_for_offer(offer.id):
                links[link.search.value] += 1
                relevant[f"{link.search.value}:{link.is_relevant}"] += 1
    by_category = Counter(str(e.category) for e in latest.values())
    laptops = [e for e in latest.values() if str(e.category) == "laptop"]
    print(f"eval database: {EVAL_DB}")
    print(f"offers: {len(offers)}  extractions: {len(latest)} ({dict(by_category)})")
    print("attribute fill rates (laptop extractions):")
    for name in ("gpu", "cpu", "ram_gb", "storage_gb", "storage_type", "screen_in", "condition"):
        filled = sum(1 for e in laptops if e.attributes.get(name) is not None)
        print(
            f"  {name:13s} {filled:3d}/{len(laptops)}  ({100 * filled / max(1, len(laptops)):.0f}%)"
        )
    print(
        f"snapshots: {snapshots} over {len({h[0] for h in history})} offers (synthetic price drops):"
    )
    for offer_id, old, new, at in history:
        print(f"  {offer_id}: {old} -> {new} at {at}")
    print(f"searches: {[s.name.value for s in searches]}  links: {links}")
    print(f"relevance by search: {dict(relevant)}")
    print(
        f"rtx-laptops links: {len(ids)} ({sum(1 for o in linked if re.search(r'RTX', (o.title or '') + _plain(o.description or ''), re.I))} mention RTX)"
    )


if __name__ == "__main__":
    if not SRC_DB.exists():
        sys.exit(f"missing {SRC_DB}")
    asyncio.run(seed())

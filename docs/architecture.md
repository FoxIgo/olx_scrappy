# Architecture overview

## Goal (current understanding)

A personal tool that runs saved searches on several marketplaces (olx.pl, allegro.pl, …)
on a schedule, stores listings, tracks price/state changes, and notifies about new or
changed listings. A web UI may come later.

## Shape

```
              ┌──────────────────────── packages/server ─────────────────────────┐
 CLI ───┐     │ presentation        application              domain              │
 Cron ──┼────►│  (driving)   ──►  use cases  ──►  Listing, SavedSearch, Price    │
 HTTP ──┘     │                      │ ports                                     │
 (later)      │                      ▼                                           │
              │                infrastructure (driven)                           │
              │  ListingSource impls          │ SQLite repos │ Notifier │ Clock  │
              │  ┌─ olx_pl ─────┐ ┌─ allegro_pl ┐                                │
              │  │ urls/parser/ │ │ urls/parser/ │   ◄── site recipes            │
              │  │ mapper       │ │ mapper       │                               │
              │  └──────┬───────┘ └──────┬───────┘                               │
              │         ▼  PageFetcher   ▼          ◄── engines (swappable)      │
              │   httpx │ scrapling http │ stealthy │ dynamic                    │
              └─────────────────────────────────────────────────────────────────┘
```

Two independent axes inside infrastructure: **which site** (recipe) and **how to fetch**
(engine). They are combined in `main.py` from config. See
[adr/0004-scraping-sources-and-engines.md](adr/0004-scraping-sources-and-engines.md).

## Main flow: `RunSavedSearch`

1. A trigger (cron or CLI) calls `RunSavedSearch(search_id)`.
2. The use case loads the `SavedSearch`, picks the `ListingSource` for `search.source`.
3. The recipe paginates the search URL through its `PageFetcher` (rate-limited, with
   retries and fallback), parses pages, and maps them to `ScrapedListing`.
4. The use case loads known listings; the domain computes the diff: new / price changed / gone.
5. Listings and price snapshots are persisted.
6. `Notifier` sends a summary of the changes.

Idempotency: running the same search twice in a row must produce no duplicate listings
and no duplicate notifications.

## Proposed stack

- Python 3.12+, uv, asyncio ([adr/0003-language-python.md](adr/0003-language-python.md))
- Scraping: Scrapling (fetchers + `Selector`) and httpx, behind `PageFetcher`
- pydantic at the edges only (raw payloads, API models); plain dataclasses in the domain
- SQLite (sqlite3 / SQLAlchemy Core): a single file, no ops, fine for one user
- Typer for CLI; FastAPI later for HTTP (gives OpenAPI for the TS frontend)
- pytest, pyright/mypy, import-linter for layer rules

ADRs: [0001 monorepo](adr/0001-monorepo.md) · [0002 hexagonal](adr/0002-hexagonal-server.md) ·
[0003 Python](adr/0003-language-python.md) · [0004 sources & engines](adr/0004-scraping-sources-and-engines.md)

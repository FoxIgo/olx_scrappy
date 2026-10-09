# ADR 0002 — Hexagonal (ports & adapters) server

Status: **proposed**

## Decision

The server has exactly four layers plus a composition root (Python layout, see ADR 0003):

```
packages/server/src/scrappy/
├── domain/           # pure model, zero dependencies
├── application/      # use cases + port interfaces
├── infrastructure/   # driven adapters (things WE call): sites, DB, notifier, clock
├── presentation/     # driving adapters (things that call US): CLI, scheduler, HTTP API
└── main.py           # composition root: the only place that wires concrete classes
```

### Dependency rule

```
presentation   ──► application ──► domain
infrastructure ──► application ──► domain
```

- `domain` imports nothing outside itself (no ORM, no HTTP, not even `datetime.now()`).
- `application` imports only `domain`. It **owns the port interfaces**.
- `infrastructure` implements application ports. Never imported by `application` or `domain`.
- `presentation` calls use cases. Never touches infrastructure directly.
- `main.py` is the only module allowed to import from every layer.

Enforce this with `import-linter` in CI, not discipline. Without enforcement, the layering
erodes within weeks.

## Proposed contents

```
domain/
  listing/        Listing (entity), ListingId = (SourceId, external_id), ListingStatus
  search/         SavedSearch (entity: source, search_url, schedule)
  price_history/  PriceSnapshot, PriceChange (domain event)
  shared/         Money (amount + currency), SourceId, errors

application/
  ports/
    listing_source.py        # ListingSource: the only thing the app knows about scraping
    listing_repository.py
    saved_search_repository.py
    notifier.py
    clock.py
  use_cases/
    run_saved_search.py      # fetch → diff vs stored → persist → notify
    add_saved_search.py
    list_listings.py         # read side for CLI / future API

infrastructure/
  scraping/                  # see ADR 0004
    engines/                 # PageFetcher impls: httpx, scrapling (http/stealthy/dynamic)
    sources/
      olx_pl/                # recipe: urls, parser, mapper, fixtures
      allegro_pl/
  persistence/
    sqlite/                  # repositories + migrations
  notifications/
    telegram.py, console.py
  system/
    clock.py

presentation/
  cli/                       # first interface: `scrappy search add <url>`, `scrappy run`
  scheduler/                 # periodic trigger → RunSavedSearch
  http/                      # later, FastAPI, for the frontend
```

## Critical notes / things to watch

1. **"Infrastructure" and "presentation" are both adapters.** The split is driven
   (outbound) vs driving (inbound). The scheduler is *presentation*, not
   infrastructure, because it *triggers* use cases.
2. **Site adapters are the most volatile code in the project.** Sites change markup/APIs
   without notice. Validate raw payloads and fail loudly on drift. Only the per-site
   mapper knows site field names. Consider archiving raw pages so a fixed mapper can
   re-parse old data. Details: ADR 0004.
3. **Name ports by capability, not vendor.** `ListingSource`, not `OlxScraper`.
4. **Don't over-build the hexagon.** For a personal tool: no DI container (manual wiring
   in `main.py`), no CQRS, no event sourcing, no generic `BaseRepository[T]`. Domain events
   can start as plain return values from use cases.
5. **The domain must hold real logic, or the layers are just ceremony.** Logic that belongs
   there: is a listing new or already seen, did the price drop, dedup, filter rules a site
   can't apply server-side. If the domain ends up as plain data bags, we are adding layers
   without getting anything for them.
6. **Testing follows the layers:** domain = pure unit tests; use cases = tests with
   in-memory fakes of the ports; site recipes = offline tests against saved fixture pages
   with a fake fetcher; one manual smoke run against the real sites, not in CI.

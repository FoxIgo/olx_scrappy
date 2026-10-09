# ADR 0004 — Site recipes and scraping engines as separate, swappable parts

Status: **proposed**

## Context

We want to scrape several sites (olx.pl, allegro.pl, more later) and to swap scraping
tools freely (plain HTTP, Scrapling's `Fetcher` / `StealthyFetcher` / `DynamicFetcher`,
Playwright, an official API client…). The tooling landscape moves fast; the business
logic (saved searches, diffing, price history, notifications) shouldn't care.

## Key insight: two independent axes

| Axis | Question it answers | Examples | Changes when… |
| --- | --- | --- | --- |
| **Source (site recipe)** | *What* to fetch and *how to read it* | `olx_pl`, `allegro_pl` | the site changes its URLs/markup/JSON |
| **Engine (fetcher)** | *How* to get the bytes | httpx, Scrapling Fetcher, Scrapling Stealthy, Playwright | a site starts blocking us, or a better tool appears |

Mixing them (an `OlxScraplingScraper` class) means N sites × M engines = N×M classes.
Keeping them apart means N + M parts, combined with config.

## Decision

### 1. The application sees only one port: `ListingSource`

```python
# application/ports/listing_source.py
class ListingSource(Protocol):
    source_id: SourceId                       # "olx_pl", "allegro_pl"
    def search(self, search: SavedSearch) -> AsyncIterator[ScrapedListing]: ...
```

The use case gets a `Mapping[SourceId, ListingSource]` and picks one using
`saved_search.source`. The application doesn't know engines exist.

### 2. Engines are an abstraction *internal to infrastructure*, not an application port

`PageFetcher` is **not** in `application/ports`. Fetching bytes is a technical detail
of *how* a `ListingSource` works, not a business capability. Putting it in the application
layer would make the application depend on infrastructure-level concepts (URLs, headers,
JS rendering). This is a "hexagon inside the adapter": infrastructure can have its own
internal interfaces.

```python
# infrastructure/scraping/engines/base.py
@dataclass(frozen=True)
class FetchRequest:
    url: str
    render_js: bool = False
    wait_for: str | None = None        # CSS selector hint for browser engines
    headers: Mapping[str, str] = {}

@dataclass(frozen=True)
class RawPage:
    url: str
    status: int
    content_type: str
    body: str                          # HTML or JSON text

class PageFetcher(Protocol):
    async def fetch(self, req: FetchRequest) -> RawPage: ...
```

### 3. A recipe = fetcher (injected) + URL builder + parser + mapper

```
infrastructure/scraping/
├── engines/
│   ├── base.py                 # PageFetcher, FetchRequest, RawPage, FetchBlocked error
│   ├── httpx_fetcher.py
│   ├── scrapling_http.py       # wraps scrapling Fetcher/FetcherSession
│   ├── scrapling_stealthy.py   # wraps StealthyFetcher/StealthySession
│   ├── scrapling_dynamic.py    # wraps DynamicFetcher/DynamicSession
│   └── decorators.py           # RateLimited, Retrying, Fallback, Archiving, Cached
└── sources/
    ├── olx_pl/
    │   ├── source.py           # OlxPlListingSource(fetcher) implements ListingSource
    │   ├── urls.py             # search URL / pagination
    │   ├── parser.py           # RawPage → OLX-shaped records (selectors or JSON)
    │   ├── mapper.py           # OLX records → ScrapedListing (anti-corruption layer)
    │   └── fixtures/           # saved real pages for tests
    └── allegro_pl/
        └── … same shape …
```

Each recipe gets its `PageFetcher` through its constructor. Which engine goes with which
site is decided in the composition root, driven by config:

```yaml
# config/sources.yaml
olx_pl:
  engine: http
  rate_limit: 1/3s
allegro_pl:
  engine: [http, stealthy]   # fallback chain: escalate only if blocked
  rate_limit: 1/10s
```

### 4. Cross-cutting concerns are fetcher decorators, written once

`RateLimitedFetcher(RetryingFetcher(FallbackFetcher([http, stealthy])))`. Every site gets
rate limiting, retries, raw-page archiving, and dev-time caching without the recipes
knowing about them. This is where the decoupling pays off most.

### 5. Parsing doesn't depend on the engine

Scrapling's `Selector` can parse raw HTML without its fetchers. So a parser can use
Scrapling's CSS/XPath API, and adaptive selectors if useful, whatever engine fetched the
page. Swapping httpx ↔ Stealthy doesn't touch the parser.

### 6. Extraction strategy order inside a recipe

Each recipe picks the most stable source of data available on its site, in this order:

1. **Official API** (e.g. Allegro REST): a recipe with its own client, no `PageFetcher`.
2. **Private JSON endpoint** that the site's own frontend calls (XHR/fetch/GraphQL).
3. **Embedded state JSON** in the HTML (`__NEXT_DATA__`, `__PRERENDERED_STATE__`, JSON-LD).
4. **HTML selectors** (Scrapling `Selector`; adaptive mode as a safety net).

A recipe can combine them, e.g. discovery from a JSON endpoint and details from
embedded state. The order is a guideline, decided per site by a spike.

### 7. Politeness policy (per host, in fetcher decorators)

- A concurrency limit **per host** (semaphore), not one global pool.
- Delays between requests with **random jitter**, not a fixed interval.
- On `429` / `503`: exponential backoff with jitter, honoring `Retry-After`.
- Configured per source in `sources.yaml`. Recipes don't know about it.

### 8. Fetch outcome classification

A blocked request often returns **HTTP 200 with a challenge page**. So "did it work" is
decided by classification, not status codes alone:

```python
class FetchOutcome(Enum):
    OK            # real content
    BLOCKED       # 403/429, captcha, challenge page → retry later or escalate engine
    NOT_FOUND     # 404 / "offer does not exist" → domain status, not an error
    GONE          # removed / sold page → domain status (R9)
    TRANSIENT     # network error, 5xx → retry
```

- Engines detect **generic** blocks (status codes, known challenge markers).
- Each recipe adds **site-specific** rules (`classify(page) -> FetchOutcome`), since only
  the recipe knows what "offer removed" looks like on OLX.
- `FallbackFetcher` escalates to the next engine only on `BLOCKED`. Never on
  `NOT_FOUND`/`GONE`, which are valid answers.

## Critical notes / risks

1. **The common interface only covers what all engines can do.** `url → body` covers
   ~90% of cases. A site that needs real interaction (click "load more", infinite scroll,
   login) won't fit. Rule: add *hints* to `FetchRequest` (`render_js`, `wait_for`)
   first. If a recipe truly needs browser control, let that one recipe depend on a
   specific engine directly and document it. Don't grow `PageFetcher` into a full
   browser API.
2. **Use Scrapling as a library, not as a framework.** Its `Spider` (scheduling,
   callbacks, pipelines, checkpoints) would take over control flow that belongs to our
   use cases and scheduler. Use fetchers + `Selector` only. Revisit if we ever need large
   crawls (thousands of pages) rather than "check saved searches".
3. **Prefer structured data over HTML.** If a site has internal JSON endpoints or embeds
   state JSON in the page (`__PRERENDERED_STATE__`, `__NEXT_DATA__`…), parse that. It
   breaks far less often than CSS selectors. The recipe decides; the engine doesn't care.
4. **Allegro is much harder than OLX.** It has strong anti-bot protection, and it also
   has an official REST API. Spike before building: an official API recipe (no `PageFetcher`,
   just its own client implementing `ListingSource`) might beat scraping. The port lets
   both options coexist.
5. **Searches don't map across sites.** OLX and Allegro have different categories,
   filters, and location models. Don't build a universal `SearchCriteria` up front.
   **Start with `SavedSearch = source + search URL copied from the browser`.** The
   recipe only paginates that URL. A normalized cross-site query ("iphone 15 under
   2000 zł everywhere") can come later, as a per-recipe `criteria → URL` translator.
6. **Identity is per source.** `ListingId = (source_id, external_id)`. Linking the
   same item across sites is a separate, hard problem; not in scope.
7. **ToS and politeness.** Personal, low-frequency use; respect rate limits; check each
   site's terms and robots.txt. Stealth engines are a fallback, not the default.

## Consequences

- Adding a site = new folder in `sources/` + a config entry. Nothing outside
  infrastructure changes.
- Swapping an engine for a site = config change. Adding a new engine = one file
  implementing `PageFetcher`.
- Recipes are tested offline against `fixtures/` (saved real pages), with a fake fetcher.

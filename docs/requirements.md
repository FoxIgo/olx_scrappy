# Requirements (gathered step by step)

Living document. Each item records the decision and *why it matters for architecture*.

## Round 1 — core use case

### R1. Core feature: scrape every offer from a search URL
Input: a site search URL, e.g.
`https://www.olx.pl/oferty/q-gtx-1650-laptop/?search[order]=filter_float_price:asc&search[filter_float_price:from]=600&search[filter_float_price:to]=1400`
→ walk all result pages → collect every offer.

### R2. Runs are triggered on demand for now
- Now: manual trigger (CLI).
- Later: cron, and **AI agents with tools**.
- **Architecture impact:** use cases are the system's API. Cron, CLI, HTTP, and an
  agent tool server (e.g. MCP) are all just *driving adapters* in `presentation/`, or
  separate packages calling the same use cases. Nothing in application/domain may
  assume who the caller is. Runs must be **idempotent** so any caller can retry safely.

### R3. Offer depth: description is required
- List page alone is not enough: **description is mandatory** → we must open each offer page.
- Also "the most valuable data" (params, seller, location, dates — to be specified).
- Pictures: later. For now, store image **URLs** only, no downloading.
- **Architecture impact:** scraping is a **two-phase pipeline**:
  1. *Discovery*: paginate search results → offer references (id, url, list-level data).
  2. *Enrichment*: fetch each offer page → full details.
  Phase 2 is ~40× more requests than phase 1. That makes these first-class concerns:
  skipping offers we already have, rate limiting, partial failure, and resumability.

### R4. Deduplication
- Within a run: the same offer on several pages / promoted ads repeated → one offer.
- Across runs: an offer seen before is **updated, not inserted**.
- Identity = `(source, external_id)`. Reposts with a new id and cross-site matching are
  **out of scope**.

### R5. Use of data: browse and filter
- Stored offers must be queryable (CLI now, web UI later).
- **Architecture impact:** persistence is required even without monitoring. Filtering
  by offer attributes (GPU, RAM…) needs those attributes stored in a queryable form.

## Round 2 — run lifecycle and change tracking

### R6. Runs are resumable
- A **ScrapeRun** is a tracked entity: status (`running / completed / failed / partial`),
  progress for each phase, error log.
- Re-running a failed run continues where it stopped: pages already discovered and
  offers already enriched are skipped.
- **Architecture impact:** progress is persisted as work items (pages to visit, offers to
  enrich) with per-item status. This is effectively a small durable job queue. It's also
  the base for cron and agent triggers later (R2).

### R7. Changes are kept as history
- An offer has a **current state** plus **snapshots** recorded whenever tracked fields
  change (price, title, description, status…).
- A run that sees no change writes no snapshot, only `last_seen_at`.
- Makes price analytics possible later without rescraping.

### R8. Detail re-fetch policy: new offers or changed list data
- Fetch the offer page when the offer is **new**, or when its **list-level data changed**
  (price, title, refreshed date).
- Unchanged offers: only `last_seen_at` is updated. No detail request is made.
- The policy is a domain rule (pure function, unit-testable), so it can be swapped later
  (e.g. "also if older than N days").

### R9. Offers missing from a search: keep it simple
- No automatic "disappeared" logic. We store each offer's URL; whenever the offer page
  is fetched (any run, or an explicit "refresh this offer"), its status is read from the
  page: `active / removed / sold / unknown`.
- `last_seen_at` per (search, offer) is recorded anyway, at no extra cost.

## Round 3 — searches, attributes, storage, volume

### R10. Saved, named searches
- `SavedSearch` entity: name (e.g. `gtx-laptops`), source, search URL, created/last-run.
- Offers ↔ searches is **many-to-many**: one offer can be found by several searches, and
  `first_seen_at` / `last_seen_at` are tracked per (search, offer).
- Offers themselves are global and deduplicated by `(source, external_id)`.

### R11. Spec extraction with an LLM from the start (no regex)
- Normalized attributes (GPU, CPU, RAM…) are extracted by an LLM (a cheap model via
  OpenRouter) from title + description + site params.
- **Architecture impact:**
  - New application port `AttributeExtractor`. This is a business capability, unlike
    fetching. Adapter: `OpenRouterAttributeExtractor` (OpenAI-compatible API). The model
    is a config value.
  - Extraction is a **third pipeline phase**: Discovery → Enrichment → **Extraction**.
    It is a separate stage so it can be **re-run without re-scraping** (better model,
    changed schema).
  - LLM output is validated against a schema (structured output + pydantic). Invalid
    output is rejected like any parse failure (ADR 0005).
  - Results store **provenance**: model, prompt/schema version, timestamp. This makes it
    possible to know which offers to re-extract.
  - **Cost control:** extract only when the content hash (title + description + params)
    changed. Unchanged offers are never sent again.
  - An LLM failure doesn't fail the scrape. The offer stays stored, marked
    "extraction pending".
  - Offer descriptions are untrusted input to the LLM. Output is schema-validated and
    never executed or used as instructions.

### R12. Storage: SQLite now, Postgres-ready
- SQLite (WAL mode) behind repository ports. SQLAlchemy Core for portable SQL.
- SQLite-specific features (FTS5 full-text, JSON1) stay inside the persistence adapter,
  behind a query port, so the Postgres adapter can use `tsvector` / JSONB instead.

### R13. Volume: medium
- Tens of saved searches, tens of thousands of offers, runs several times a day.
- **Architecture impact:**
  - A **worker process** separate from CLI/API triggers. Triggers *enqueue*; the worker
    *executes*. The R6 work items become a **durable job queue** behind a `JobQueue`
    port: a SQLite table now, Postgres `SKIP LOCKED` (or Redis) later.
  - Politeness is the real limit, not the database. Example: at 1 request / 3 s, 1000
    offer pages ≈ 50 min. So "fetch details only for new/changed offers" (R8) is
    essential, not an optimization.
  - SQLite is fine at this size with a single writer (the worker). If several writer
    processes appear (worker + web + agents), that's the trigger to move to Postgres.

## Round 4 — LLM extraction details

### R14. Category schemas, offer-level classification, per-search relevance
- Attribute schemas are defined **per category** (e.g. `laptop`), versioned.
  A saved search targets one category.
- The LLM classifies each offer into a category **once**; relevance is stored per
  `SearchOffer` link (`is_relevant`), derived from category match, with a manual override.
- The LLM is a **pure function** over prepared, already-scraped data: no tools, no
  browsing. The trigger (auto after enrichment / on demand) is configurable.
- No cost cap; usage is recorded and reported per run.
- Details: [ADR 0006](adr/0006-pipeline-and-jobs.md), [ADR 0007](adr/0007-llm-extraction.md),
  [domain-model.md](domain-model.md).

### Not now
Notifications, export, price analytics, cross-site duplicate matching, image download.

## Round 5 — runtime

### R15. Runs locally now, Docker-ready from day one
- Development and use: the user's Windows machine.
- Everything must also run in Docker: `Dockerfile` for the server image, `docker compose`
  with a `worker` service and a volume for the SQLite DB, raw pages, and config.
- Config comes only from environment variables plus config files (`sources.yaml`,
  `categories.yaml`). Paths are configurable and secrets (OpenRouter key) come from env/`.env`.
- Browser engines (Chromium/Camoufox) go in an optional image variant, not the base
  image: the base stays small while tier-1 HTTP is enough.

## Round 6 — OLX access (after spike)

### R16. olx.pl via internal JSON API with browser TLS impersonation (approved)
- Plain httpx gets CloudFront 403. `curl_cffi` with Chrome impersonation gets 200 with
  no challenge. The user approved TLS impersonation as the default engine for `olx_pl`,
  with polite rate limits kept. No CAPTCHA solving, no logins, no stealth browsers.
- Discovery uses `/api/v1/offers/` (search items already contain full details incl.
  description), so for OLX the EnrichOffer stage is skipped. A parser for the embedded
  `__PRERENDERED_STATE__` in the HTML is kept as a tested fallback.
- Searches are capped at ~1000 results; the run report warns when a search is truncated.

## Round 7 — extraction redesign (after measuring a real run)

### R17. Extraction is decoupled from scraping and uses provider batching
- Measured: scraping ~1 min vs sequential LLM extraction ~47 min for one run (368 offers).
- Extraction becomes a reconciling loop over the database (backlog = offers without an
  up-to-date extraction), not jobs enqueued by the scraper. Failures, schema/model
  changes and a missing key heal automatically.
- One `worker` process runs both loops (`--only scrape|extract` to split them).
  A run = scraping only; `run --inline` scrapes only.
- LLM calls go through OpenRouter's **Batch API** (about 50% cheaper, results usually
  within minutes, ≤ 24 h). Sync mode stays as a fallback. The user will pick a faster,
  batch-capable model.
- Details: [ADR 0010](adr/0010-decoupled-batch-extraction.md).

### R18. Free-tier data terms are acceptable
- Google AI Studio's free tier may use prompts for product improvement and human review.
  The user accepts this: extraction input is public OLX listing text.
- Still don't send what isn't needed: the extraction input contains title, description,
  params and price only (no seller data). It stays that way for every provider.

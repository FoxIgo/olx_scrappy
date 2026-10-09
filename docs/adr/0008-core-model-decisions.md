# ADR 0008: Core model decisions (domain + application)

Status: **proposed**

## Context

Phase 1 implemented `scrappy.domain` and `scrappy.application` (see ADRs 0002, 0004–0007,
`domain-model.md`) together with in-memory fakes of every port (`tests/unit/fakes/`).
The OLX spike (`research/olx-pl-spike.md`) arrived during the work and changed some shapes.
This ADR records the decisions that go beyond the earlier docs. Adapter authors
(SQLite, scraping, OpenRouter, CLI/worker) build against these ports. The port docstrings
are the detailed contract, and the fakes are the reference behaviour.

## Decisions

### Domain

1. **Observations, not "ScrapedListing".** A source produces one type, `OfferObservation`,
   with a `level`: `LISTING` (search-card data) or `DETAILS` (detail-complete: it has a
   description, plus params/status where the site has them). Every field except identity
   is optional, and `None` means *not observed*. This replaces separate list/detail types,
   because OLX's search API returns full offers (spike section 3): such a source emits
   `DETAILS` observations from discovery, `needs_details` returns False for them, and no
   EnrichOffer job is created.
2. **Change rules (R7, ADR 0005).** `Offer.apply(observation, at) -> list[FieldChange]`:
   - `None` (and `OfferStatus.UNKNOWN`) never overwrite anything and are never changes.
   - A field seen for the first time is filled in silently. Creating an offer or enriching
     it for the first time writes **no snapshot**; history starts at the first real
     change, which carries the old value.
   - Tracked fields: title, price, location, description, params, status. Other fields
     (url, dates, thumbnail, images, seller) update silently.
   - Snapshots can be written at discovery too: a price change seen on the list page is
     recorded at once, so the enrichment that follows sees no difference.
3. **Price** is `Price(kind, amount, negotiable)` with `PriceKind` FIXED / EXCHANGE / FREE.
   Only FIXED has a `Money` amount; a `0` amount is never used as a marker (spike section 4).
   Negotiable-only changes count as price changes. OLX "budget"/"arranged" map to FIXED in
   the mapper (open issue 6).
4. **`needs_details` (R8)** is True for a new offer, for an offer never enriched
   successfully (`details_fetched_at is None`, so a failed enrichment is retried next
   run), or when price, title or refreshed date differ, where both values must be known.
   It is evaluated *before* the observation is applied.
5. **Status from fetch outcome (R9)**, `status_after_fetch(outcome, observed, offer_known)`:
   - GONE: SOLD/REMOVED if the page says so, else REMOVED.
   - NOT_FOUND: REMOVED for a known offer, nothing for an unknown id (spike section 5).
     Sources never decide this; they report what the site said.
   - BLOCKED/TRANSIENT: no information.
   GONE/NOT_FOUND also set `details_fetched_at`, so a removed offer that still shows up in
   search results is not re-fetched every run.
6. **Content hash** = SHA-256 over canonical JSON
   `{"description","params":[[k,v]...sorted],"title"}` (compact separators, UTF-8, raw
   stored description). It is computed only once a description is known. A golden value
   is pinned in `test_values.py`: changing the algorithm re-extracts everything.
7. **`FetchOutcome` lives in the domain** (`domain.shared`), because status rules and run
   metrics depend on it.
8. **Categories.** `other` is a reserved implicit category with no schema and no version.
   Attribute types are string/integer/number/boolean/enum; `number` uses `Decimal`.
   `AttributeSpec.coerce` is shared by LLM-output validation and CLI filter coercion.
   `CategoryCatalog.fingerprint` (12 hex chars over every `name@version`) identifies a
   catalog state.
9. **`needs_extraction`**: content hash changed, never extracted, or the classified
   category's schema version changed (a category removed from config counts as changed).
   `other` is not redone for schema changes. Model or prompt changes are handled by a
   forced re-extraction, not by this rule.
10. **Relevance** is tri-state (`True/False/None` = not classified yet). `SearchOffer` stores
    `derived_relevance` and `relevance_override` separately; `is_relevant` = override
    first. When a new search links an offer that is already classified, relevance is
    derived immediately, with no second LLM call.
11. **Attribute predicates** (`AttributePredicate.matches`) are the reference semantics
    for filtering:
    - null never matches, not even `!=`;
    - strings compare case-insensitively, and `~` is a substring match;
    - ordering operators work only on numbers;
    - mixed types never match.
12. **Run outcome.** `run_health` → COMPLETED/DEGRADED, with reasons (rejected ratio per
    phase, minimum fill rates per phase/field, ignored below `min_sample`).
    `conclude_run` precedence: **FAILED** (no search page fetched OK) > **DEGRADED** >
    **PARTIAL** (work items out of retries) > **COMPLETED**. Truncation is a *warning*,
    not a status. `RunStatus` has no separate "resumable" state; any finished run can be
    resumed.
13. **Fill rates** count `present / applicable` per field. Detail fields only apply to
    detail-complete records, so mixing listing and details in one phase does not distort
    them. Extraction fill rates are keyed `category.attribute`.

### Application ports

14. **`ListingSource`** (async):
    - `fetch_search_page(PageRef) -> SearchPageResult`
    - `fetch_offer_details(OfferDetailsRequest) -> OfferDetailsResult`

    `PageRef(cursor, number)`: the cursor is an opaque string chosen by the recipe (page
    URL or the site's `links.next` API URL). Page 1's cursor is the saved search URL.
    The application stores the next `PageRef` in the next job, which makes pagination
    resumable.

    `SearchPageResult` carries `observations`, `rejections`, `next_page`,
    `total_results`, `truncated` (OLX ~1000 cap), `retry_after`, `raw_ref`. A page past
    the end is OK with no records and no next page.

    `OfferDetailsResult` has factories `ok / rejected / gone(status) / not_found / failed`.
    Invariants are checked in `__post_init__`. Sources never raise for expected failures;
    unexpected exceptions count as TRANSIENT.

    The registry is `Mapping[SourceId, ListingSource]` (`ListingSources`), as in ADR 0004.
    There is no separate registry port.
15. **Repositories** (async): `OfferRepository` (incl. snapshots and a keyset scan
    `list_with_content`), `SavedSearchRepository`, `SearchOfferRepository`,
    `ExtractionRepository` (append-only history, `latest` / `latest_many`),
    `ScrapeRunRepository` (`find_running`).
    - `save` is an upsert.
    - Returned entities are detached copies: changes persist only through `save`.
    - `SearchOffer` has its own repository, because it has its own lifecycle and per-search
      queries; folding it into either aggregate would load every link.
    - The categories are a read-only `CategoryProvider.catalog()` outside the unit of work,
      since they are config.
16. **`UnitOfWork`** (async context manager with `commit` / `rollback`, exposing all
    repositories plus `jobs`) is the only transaction boundary. Rollback happens unless
    `commit` is called. Use cases **never do network I/O inside a unit of work**. Handlers
    read, close, fetch or call the LLM, then open a new unit of work to write. Transactions
    stay short and a single SQLite writer (`BEGIN IMMEDIATE`) is enough. Units of work are
    created by `UnitOfWorkFactory = Callable[[], UnitOfWork]`.
17. **`JobQueue` is inside the unit of work** (`uow.jobs`). Follow-up jobs are therefore
    committed atomically with the state change that caused them (an outbox for free).
    Methods:
    - `enqueue(job) -> bool`
    - `claim(types, limit, now)`: FIFO by `(available_at, insertion)`, attempts +1
    - `complete(id, result, now)`
    - `fail(id, error, retry_at, result, now)`
    - `get`, `count_unfinished(run_id)`, `list_for_run(run_id)`
    - `requeue_failed(run_id, now)`: FAILED and orphaned RUNNING jobs go back to PENDING
      with attempts reset

    `now` is passed in explicitly; the adapter never reads the clock.
18. **`AttributeExtractor.extract(ExtractionInput) -> ExtractionResult | ExtractionRejection`**.
    - Invalid output (after one retry inside the adapter) gives `retryable=False`.
    - Provider/network trouble gives `retryable=True`.
    - Neither case raises. Usage is always reported.
    - The domain validates the result again (`OfferExtraction.validated`).
19. **Read side**: `OfferQueries.list_offers(OfferFilter) -> list[OfferListItem(offer, link,
    latest extraction)]`. Filters: search, `RelevanceFilter` (ALL / RELEVANT /
    NOT_IRRELEVANT / IRRELEVANT; it needs a search), statuses, category, and AND-ed
    attribute predicates. `matches_filter` is the normative semantics. Order: last seen
    descending, then offer id.
20. `Clock.now()`, `IdGenerator.new_id()` (sync). `ports/__init__.py` re-exports nothing,
    to keep `ports ↔ jobs.model` acyclic.

### Jobs

21. **Dedup keys are unique forever** (a UNIQUE index plus insert-or-ignore). Each key
    encodes its scope:

    | Job | Key |
    | --- | --- |
    | DiscoverPage | `discover:{run_id}:{page_cursor}`: each page once per run; also stops pagination loops |
    | EnrichOffer | `enrich:{offer_id}:{run_id}` (ADR 0006) |
    | EnrichOffer (refresh) | `enrich:{offer_id}:refresh:{tag}` (explicit refresh, no run) |
    | ExtractOffer | `extract:{offer_id}:{content_hash}:{catalog_fingerprint}[:{tag}]` |

    The catalog fingerprint is in the extract key because without it a schema bump could
    never re-extract the same content: the old key already exists. A unit test caught
    exactly that. A forced re-extraction needs a request tag.
22. **Job results carry metrics**, as `JobResult(RunMetrics, notes)`. A run's metrics are
    the **sum of its jobs' stored results**, computed by `FinalizeRun` once
    `count_unfinished == 0`. A job that is re-run replaces its contribution, so at-least-once
    delivery never double-counts. Only the final attempt of a job is counted (open issue 3).
23. **Handlers** return `JobResult`, or raise `RetryableJobError(retry_after)` /
    `PermanentJobError`. Any other exception is retryable. `JobDispatcher` maps outcomes:
    - success → `complete`
    - retryable → `fail(retry_at = RetryPolicy.retry_at(attempts, now, hint))`; the result
      is FAILED when attempts are exhausted
    - permanent → FAILED

    After every final outcome, the dispatcher calls `FinalizeRun(run_id)` (idempotent). The
    worker loop (presentation) calls `dispatcher.run_once(types, limit)` repeatedly.
24. **Handler rules:**
    - **DiscoverPage**: dedup observations by offer id (a DETAILS duplicate wins over a
      LISTING one), apply, snapshot, and upsert the link. Then enqueue EnrichOffer if
      `needs_details`, else ExtractOffer if auto-extraction is on and `needs_extraction`.
      The next page is enqueued unless `max_pages` is reached, which marks the run
      truncated.
    - **EnrichOffer**:
      - A detail rejection is counted and the job completed, not retried (parsing is
        deterministic); the next run tries again.
      - An unknown id is created on OK and ignored on NOT_FOUND.
    - **ExtractOffer** skips without an LLM call in three cases:
      - the content changed since the job was enqueued;
      - `needs_extraction` is false (not forced);
      - a forced job already ran (idempotency).

      It stores the extraction and re-derives relevance on every link of the offer.
25. **Policies are plain config values**: `PipelinePolicy` holds
    - `extraction.auto` (= `pipeline.extract.auto`) and `description_max_chars`
    - `discovery.max_pages`
    - `retry` (`max_attempts`, exponential backoff, honours the `Retry-After` hint, no
      jitter: jitter belongs to the engines)
    - `health` (default and per-source `HealthThresholds`)

### Use cases

26. Use cases accept domain VOs (`SearchName`, `SourceId`, ...). Driving adapters parse
    strings and map `InvalidValueError` and the application errors (`NotFoundError`,
    `ConflictError`, `InvalidRequestError`) to user-facing messages.
    - `AddSavedSearch`: idempotent for an identical definition, ConflictError otherwise;
      validates the source against the registry keys and the category against the
      catalog.
    - `StartRun`: idempotent while a run of the search is RUNNING (returns it). Writes the
      run plus the first DiscoverPage job and returns at once.
    - `ResumeRun`: `requeue_failed`, reopens a finished run, finalizes if nothing is left.
    - `RefreshOffer(offer_id, tag)`: explicit R9 refresh outside runs.
    - `RequeueExtractions(category?, force?, request_tag?)`: covers `extract --pending`,
      re-extraction after a schema bump (`--category laptop`), and forced re-extraction.
      Jobs have `run_id = None`.
    - `ListOffers`: validates and coerces attribute predicates against the category schema
      (filter category, else the search's category). Ordering operators only apply to
      numeric attributes, `~` only to text.
    - `SetRelevanceOverride(search, offer, True/False/None)`.
27. **Extraction input** (`prepare_extraction_input`):
    - all catalog categories are candidates, because classification must not depend on
      which searches found the offer;
    - HTML is stripped with the stdlib `HTMLParser` (block tags and `<br>` become line
      breaks; raw newlines are whitespace when the text contains markup, so OLX's
      `<br />\n` gives one break);
    - whitespace is normalized;
    - text is truncated to `description_max_chars` at a word boundary, with a
      `description_truncated` flag.

## Open issues

1. **Concurrency beyond one worker.** `ResumeRun` re-queues RUNNING jobs, which assumes
   no live worker owns them. Multiple workers need leases (`claimed_until`) in the queue.
   - **Update:** under the single-worker assumption, `run_worker` and `run_until_idle`
     (`run --inline`, `resume --inline`) call `JobQueue.requeue_orphaned` once at start.
     It sets every RUNNING job back to PENDING (available now, `attempts` kept) and logs
     the count, so a hard-killed worker (docker stop after the grace period, a crash) no
     longer leaves jobs and their run RUNNING forever. It would steal jobs from a live
     worker, so the multi-worker future needs leases with heartbeat/expiry instead.
2. **Auto re-extraction after a schema bump.**
   - For detail-complete sources (OLX API), the next run re-extracts affected offers
     automatically, because discovery checks `needs_extraction`.
   - For enrichment sources, it only happens through `RequeueExtractions`, since unchanged
     offers are not enriched.
   - Decide whether that asymmetry is acceptable. A cheap fix: have discovery also check
     `needs_extraction` for LISTING observations of already-enriched offers.
3. **Usage of failed attempts.** Token usage of retried extraction attempts is not
   counted, because only the final job result counts. It could be accumulated in the
   queue if cost reports must be exact.
4. **Requeue extraction jobs have no run**, so their usage appears in no run report. An
   "extraction run" entity may be wanted later.
5. **Stopping early on known pages** (spike section 7, newest-first sort) is not
   implemented. It needs a policy plus a "page fully known" signal from discovery.
6. **Price kinds.** OLX "budget"/"arranged" price kinds need a mapping decision (currently
   FIXED/unknown in the recipe).
7. **Observation completeness.** A DETAILS observation requires only a description. If a
   source's detail data lacks params/status, fill-rate thresholds will show it.
8. **Raw page archive (open question 4).** `raw_ref` is carried on results and rejections
   but not stored by the application beyond job notes.

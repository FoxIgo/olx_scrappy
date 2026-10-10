# ADR 0010 — Extraction as a reconciling, batch-based process, decoupled from scraping

Status: **proposed**. Supersedes the extraction parts of ADR 0006 (the `ExtractOffer`
job type and its enqueue rule) and ADR 0007 "When it runs".

## Context

Measured on a real run (`acer-nitro-5`, 16 result pages, 368 offers):
- Scraping itself: ~16 requests at 1 req / 3 s, so **about 1 minute**.
- LLM extraction: a median of **7.7 s per call**, strictly sequential, so **about 47 minutes**.
- The FIFO job queue put each next result page behind the ~40 extraction jobs of the
  previous page, which stretched scraping over the full hour.

The deeper flaw: extraction was **edge-triggered**. The scraper enqueued a job per offer,
and the job's dedup key lived forever. So a failed extraction was never retried by later
runs, a schema or model change needed manual requeueing, and a missing API key left
permanent failures. Extraction is really **derived state**: "every offer whose current
content has an up-to-date extraction". Everything it needs is already in the database.

User decisions (planning round):
- One process, two independent loops (they can also run as separate services).
- A run = scraping only. Extraction progress is reported separately.
- **Provider Batch API** instead of parallel calls: OpenRouter's Batch API (launched
  2026-09-22) charges about 50% of the per-token price, returns results within 24 h
  (beta: median 7 min, p90 < 1 h), and runs each batch on a single provider.
- `run --inline` = scrape only.

## Decision

### 1. Two independent loops

```
 Scraper loop                               Extractor loop (reconciler)
 DiscoverPage / EnrichOffer jobs            every tick:
   │ per-host politeness                      1. backlog = offers needing extraction
   ▼                                          2. claim a batch (lease) → submit
 offers table  ◄──────── reads ───────────    3. poll open batches → ingest results
 (content_hash)                               4. failed items → backoff, back to backlog
```

- **No `EXTRACT_OFFER` jobs.** The scraper never enqueues extraction work. The job queue
  serves only scraping stages. Existing `extract_offer` rows are marked obsolete by a
  migration.
- A **run ends when scraping ends.** Its report shows the extraction backlog for its
  search instead of extraction metrics.
- `scrappy worker` runs both loops. `--only scrape|extract` runs one, so Docker Compose
  can split them into two services. `scrappy extract --inline` runs the extractor until
  the backlog is empty (or until open batches are submitted, with `--no-wait`).

### 2. The backlog is a query (level-triggered)

An offer needs extraction when it has content, it isn't leased, it isn't in backoff, and:
- it has no extraction, or
- the latest extraction's `content_hash` ≠ the offer's current `content_hash`, or
- the latest extraction's catalog fingerprint / prompt version ≠ the current one.

Consequences: retries, schema bumps, prompt changes, model switches and "API key added
later" all **heal automatically** on the next tick. `extract requeue` survives only as
`--force` (re-extract even if up to date).

### 3. Extraction state per offer

A small `extraction_state` record per offer (application-owned, not part of the Offer
aggregate):
- `lease_until`, `lease_owner` (a batch id or worker id): claimed work can't be claimed
  twice; expired leases return to the backlog, so a crashed extractor loses nothing.
- `attempts`, `last_error`, `next_attempt_at`: exponential backoff per offer. After N
  failures the offer is parked as `failed` and shown in `q health`, until content or
  schema changes, or a manual retry.

### 4. Batch lifecycle

```
 backlog ─claim(limit)─► SUBMITTED ──poll──► COMPLETED ─ingest─► extractions written
                            │                    └─ partial: failed items → backoff
                            └──► EXPIRED/FAILED ─► leases released, items → backoff
```

- An `extraction_batches` record: id, provider batch id, model, prompt version, catalog
  fingerprint, status, submitted/completed timestamps, item count, token usage and cost.
- Each batch item carries `custom_id = <source>:<external_id>@<content_hash>`. On
  ingest, a result whose content hash no longer matches the offer is **discarded as
  stale** (the offer changed while the batch was running). The offer is already back in
  the backlog through the hash rule.
- Ingest reuses the existing validation (schema → domain coercion → provenance →
  relevance derivation). Invalid items count as failures for that offer, with no
  corrective retry inside a batch: they go back to the backlog with backoff.
- Submission policy (config): submit when the backlog ≥ `batch.min_size` or the oldest
  backlog item is older than `batch.max_wait`, at most `batch.max_size` items per batch,
  at most `batch.max_open` open batches.

### 5. Ports

The application gets an `ExtractionBackend` port with two capabilities, so the
reconciler doesn't care which is used:

```python
class BatchExtractionBackend(Protocol):
    async def submit(self, items: Sequence[ExtractionInput], *, batch_ref: str) -> SubmittedBatch: ...
    async def poll(self, batch: SubmittedBatch) -> BatchStatus: ...            # status + counts
    async def results(self, batch: SubmittedBatch) -> AsyncIterator[BatchItemResult]: ...
    async def cancel(self, batch: SubmittedBatch) -> None: ...
```

- The existing synchronous `AttributeExtractor` stays as the **sync mode**: for models
  without batch support, tiny backlogs, or `scrappy extract --now`. The mode is a config
  value (`extraction.mode: batch | sync | auto`). `auto` = batch when the backlog ≥
  `min_size`, otherwise sync.
- Adapter: `OpenRouterBatchBackend` (shares the prompt builder and response schema with
  the sync adapter, so outputs are identical).
- Repositories: `ExtractionStateRepository` (backlog query, claim with lease, backoff)
  and `ExtractionBatchRepository`.

### 6. Reporting

- `scrappy runs show`: scraping metrics + "extraction backlog for this search: N".
- `q health` / `scrappy extract status`: backlog size, open batches (age, items),
  completed batches (tokens, cost), parked failures with reasons, model in use.

### 7. Adjustments from the API spike ([research/openrouter-batch-spike.md](../research/openrouter-batch-spike.md))

- **Raw httpx adapter.** The `openai` SDK's batches API (file upload) is incompatible.
  Requests are inline JSON (`POST /api/v1/batches`, `requests[]` of `{custom_id, body}`);
  results come back inline from `GET /batches/{id}`. That's why `batch.max_size` is capped
  (default 200).
- **No provider cancel.** `cancel` is local only: release the leases, mark the batch
  `abandoned`, and ignore its results if they arrive.
- **Whole-batch failure.** One invalid item can fail the batch at validation. Handle it
  with a `failed` batch path: release the leases with **no** attempt penalty, then
  resubmit in halves (bisect) to isolate the bad item, which then gets the penalty.
- **`expired` gives no partial results.** Treat it like a failed batch: leases released,
  no penalty, resubmitted.
- **Crash-safe submission.** Persist the batch row as `submitting` **before** the POST.
  On restart, reconcile `submitting` rows against `GET /batches` (matched by model + item
  count + submission time window). The API has no idempotency key, so this prevents
  orphaned paid batches.
- **Cost:** reported per batch. Per-offer cost is allocated by token share and marked
  as an estimate.
- **Response format per batch, not per call.** `json_schema` strict vs `json_object` is
  decided once from config/capabilities. There is no per-call fallback in batch mode.
- **Startup capability check:** the configured `<model>:batch` must exist in the public
  `/models` list with `structured_outputs`; otherwise warn and run in sync mode.
- **402 (insufficient balance):** park the backlog and surface it in `q health`. No
  retry storm.
- **Polling:** every 60 s while batches are open (configurable). Beta turnaround: median
  7 min, p90 1 h, p99 ~10 h.

### 8. Room for choice: provider profiles (user decision)

Batching is a **capability**, not a requirement. Many providers and local runtimes don't
have it. Cheap remote models are still not cheap enough for a "dumb" extraction task, so
local models (Ollama / LM Studio on the user's GPU) and free tiers (e.g. Google AI
Studio) must be first-class options.

Configuration in `config/extraction.yaml`: named **profiles**, one default, and an
optional fallback chain (the chain was replaced by a parallel `pool` in section 9; the
snippet below shows the original shape):

```yaml
default_profile: local
fallback: [local, openrouter]          # next profile if one is unavailable or out of quota
profiles:
  local:                               # Ollama (LM Studio: base_url http://localhost:1234/v1)
    provider: openai_compatible
    base_url: http://localhost:11434/v1
    model: qwen2.5:7b-instruct
    mode: sync
    concurrency: 1                     # one GPU: keep it serial
    structured_output: json_schema     # json_schema | json_object | prompt_only
  openrouter:
    provider: openrouter
    model: openai/gpt-4.1-nano
    mode: auto                         # batch when the backlog is big enough, else sync
    api_key_env: OPENROUTER_API_KEY
  google:
    provider: gemini
    model: gemini-2.5-flash-lite
    mode: sync
    api_key_env: GEMINI_API_KEY
    rate_limit: 15/min                 # free-tier limits
```

- **Provider adapters** implement capability ports. Every adapter implements the sync
  `AttributeExtractor`; adapters that can batch also implement `BatchExtractionBackend`.
  The reconciler asks the profile what it can do. It never checks provider names.
  - `openai_compatible`: any `/v1/chat/completions` server (Ollama, LM Studio, vLLM,
    llama.cpp server, and also hosted OpenAI-compatible APIs). Sync only.
  - `openrouter`: sync (the existing adapter, refactored onto the generic one) + batch.
  - `gemini`: sync (Google's OpenAI-compatible endpoint or the native API); batch possible
    later through the same port.
- **Structured-output levels** per profile: `json_schema` (strict), `json_object`, or
  `prompt_only` (schema in the prompt + our validation). Small local models and some
  free models don't support strict schemas, and our validation catches bad output anyway.
- **Concurrency + rate limit per profile** in sync mode: 1 for a single local GPU, higher
  for remote APIs, a requests/min cap for free tiers. That's sync-mode tuning, not a
  substitute for batching.
- **Health check per profile** at extractor start and on failures: the endpoint is
  reachable, the model is loaded/available, and capabilities match. An unavailable
  profile → next in `fallback`, reported in `q health`.
- **Google AI Studio free-tier chain (shipped default).** Google's OpenAI-compatible endpoint
  (`https://generativelanguage.googleapis.com/v1beta/openai`, `provider: openai_compatible`,
  key `GOOGLE_API_KEY`) needs no separate adapter. Free quotas are **per model**, so several
  models are several budgets: `fallback: [gemini-lite (gemini-3.5-flash-lite), gemini-lite-31
  (gemini-3.1-flash-lite), gemma-31b (gemma-4-31b-it), gemma-26b (gemma-4-26b-a4b-it)]`;
  `lmstudio` (too slow) and the paid `openrouter` are defined but kept out of the chain.
  - Limits sit slightly below the quotas (RPM/RPD: lite 14/min, 480/day; Gemma 15/min,
    14000/day). Gemma's 16K TPM (~820 tokens per offer) caps it near 19 offers/min, so
    its rate limit is 15/min; its ~25 s latency is covered by `concurrency: 8`. There is
    no TPM limiter; the rate limit stands in for it.
  - Daily quotas reset at **midnight Pacific time**: profile field `quota_timezone`
    (IANA name, default `UTC`) decides when `daily_limit` counting resets.
  - **Gemma thinking cannot be disabled on Google**: `reasoning_effort` (any thinking
    option) is an HTTP 400, so the config loader refuses it for Gemma on that host. Only
    `json_schema` works reliably (the others leak `<thought>` text), and parsing strips a
    leading `<thought>`/`<think>` block and trailing chatter anyway. Gemma often answers
    500/503 ("high demand"): the adapter retries 5xx twice (2 s, 6 s); if it persists
    it becomes `UNAVAILABLE` (like timeouts and connection errors): no attempt penalty,
    the profile is marked unhealthy and the chain moves on (ADR 0011 slice 1).
  - **429 classification** (quota details in the body): `...PerDay...` quotaId ->
    `QUOTA` + `day_exhausted`: the profile is blocked until the next midnight in its
    `quota_timezone` and the chain moves on, no attempt penalty; `...PerMinute...` ->
    the adapter waits `RetryInfo.retryDelay` (<= 90 s, twice), then `QUOTA` with
    `retry_after_seconds`: the profile is paused that long, still no penalty. A 429
    without quota details stays `TRANSIENT`.
- **Provenance** records the profile, provider and model per extraction, so results from
  different models can be compared (`q stats` grouped by model) and selectively redone:
  `scrappy extract --force --profile openrouter --where "model=..."`.
- **CLI:** `scrappy extract --profile NAME` (one-off override), `scrappy extract
  profiles` (list profiles with health and capabilities), `scrappy extract bench
  --profiles a,b --sample 30` (later: same offers through several profiles, compare fill
  rate, agreement, speed, cost).

### 9. Parallel pool of profiles (user decision, 2026-10-10)

**Supersedes the sequential chain** (`default_profile` + `fallback`) of section 8. A chain
wastes capacity: re-extracting 877 offers took ~1 h at ~14/min while two Gemma profiles
(14,000 requests/day each) sat idle. Every free tier has its own quota, so all of them are
used **at the same time**; total throughput is the sum of the lanes.

- **Config:** `pool: [profile, ...]` replaces `default_profile` and `fallback` (the loader
  refuses the old keys with a pointer to `pool`). The first pool member is the "default"
  profile (backlog counting, `q health`). `scrappy extract --profile X` still means "only X".
- **Lanes.** One reconcile tick starts one lane per pool profile, concurrently
  (`asyncio.gather`). A lane takes chunks (2 x `concurrency` offers) from the **shared
  backlog** with the existing lease mechanism (`claim` leases the offer, so lanes never take
  the same one) and works within its own `RequestPacer` (`rate_limit`), `concurrency` and
  `daily_limit`. A faster profile naturally claims more. There is no weight/priority field:
  speed is the priority.
- **A blocked lane** (daily limit used up, quota block, unhealthy, 402) stops claiming and
  gives its claimed offers back without penalty; the others continue. Offers it released are
  offered to the other lanes again within the same tick. It resumes by itself once unblocked
  (the block is persisted per profile). Forced work pinned to a profile outside the pool
  (`extract force --profile`) gets a lane of its own, restricted to the pinned offers.
- **End of the run.** `ReconcileReport.unavailable` is true when there is a backlog but every
  lane that had work is blocked. `extract --inline` / `extract_until_idle` then stops, except
  that when the soonest block is short (a per-minute pause of at most 5 min,
  `report.retry_in`) it waits for it, at most 5 times. `--max N` is one claim budget shared
  by all lanes.
- **Shared quotas.** Profiles may name a `quota_group` defined once under `quota_groups:`
  (`daily_limit`, `quota_timezone`). The group's counter lives in the same
  `extraction_profile_status` table under the key `group:<name>`; every member checks it,
  counts into it, and a per-day 429 blocks the whole group until the next reset. Calls in
  flight are subtracted from the remaining requests, so concurrent lanes cannot overshoot
  the limit. A profile in a group must not set its own `daily_limit`/`quota_timezone`.
- **OpenRouter free models.** `openrouter-free-nemotron` (`nvidia/nemotron-3-super-120b-a12b:free`,
  `openai_compatible` against `https://openrouter.ai/api/v1`, 20/min, concurrency 2) is in
  the pool; all `:free` models share one account-wide daily limit, configured as the group
  `openrouter_free` with **50/day**. Raise it to 1000/day only if the account has ever bought
  >= $10 of credits (unknown, so the safe value is configured). OpenRouter does not document
  the reset time; UTC midnight is an assumption (a per-day 429 blocks the group until then,
  and a wrong guess only means one more 429 after the real reset, no data is affected).
- **Upstream 429.** A free model also answers 429 "temporarily rate-limited upstream"
  (`metadata.limit_source = upstream_provider_shared_pool`): not our quota and not per day.
  It is classified `QUOTA` with `retry_after_seconds = 60` and **no in-adapter wait**, so
  that lane pauses for a minute (offers released without penalty) while the others go on.
- **Safety: never pay by accident.** A profile on OpenRouter (provider `openrouter`, or a
  base URL containing `openrouter.ai`) whose model id does not end in `:free` is paid. The
  loader refuses it as a pool member unless the profile says `paid: true`. The paid
  `openrouter` profile stays defined outside the pool; the no-file fallback profile (derived
  from `SCRAPPY_LLM_*`) is `paid: true` because the user configured it knowingly.
- **Reporting.** `extract` / `extract profiles` show a `Pool` column (`lane`) and the day
  count of the quota key with the group name; `q health` lists `pool`; `extract --inline`
  prints stored offers per lane.
- **Not done: "retry on a different profile".** An offer whose answer was invalid on profile
  A should preferably be retried by B. There is no place to record the failing profile
  (`ExtractionState` has no such column; a migration was out of scope). In practice the
  retry backoff (1 min, 2, 4, ...) lets another lane claim it first with high probability.
  Possible follow-up: `last_failed_profile` on `extraction_state` and a claim filter.
- No weights, no cross-profile token-per-minute limiter, and a group has no shared
  per-minute pacer (only one OpenRouter free profile exists today).

## Not chosen

- **Parallel synchronous calls** (for one profile; parallel *profiles* are section 9):
  they solve latency but not cost, and need rate-limit handling. Batch gives ~50% lower cost with acceptable latency, because nothing waits
  on extraction any more.
- **Several offers per prompt** (prompt-level batching): one bad answer would affect the
  whole group and per-offer validation gets harder. Provider batching gets the
  discount without that risk. It could still be added later inside the adapter.

## Open points (spike before implementation)

- Exact OpenRouter Batch API contract: request format (JSONL / inline), structured-output
  support inside batches, item-level errors, result retrieval, cancellation, limits.
- Which cheap models support batch with structured output (the configured model must).
- Model choice: compare 2–3 batch-capable models on the same offers for fill rate,
  accuracy, cost, and batch turnaround.

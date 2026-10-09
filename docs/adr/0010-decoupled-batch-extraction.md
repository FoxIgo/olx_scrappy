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
optional fallback chain:

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
- **Provenance** records the profile, provider and model per extraction, so results from
  different models can be compared (`q stats` grouped by model) and selectively redone:
  `scrappy extract --force --profile openrouter --where "model=..."`.
- **CLI:** `scrappy extract --profile NAME` (one-off override), `scrappy extract
  profiles` (list profiles with health and capabilities), `scrappy extract bench
  --profiles a,b --sample 30` (later: same offers through several profiles, compare fill
  rate, agreement, speed, cost).

## Not chosen

- **Parallel synchronous calls:** they solve latency but not cost, and need rate-limit
  handling. Batch gives ~50% lower cost with acceptable latency, because nothing waits
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

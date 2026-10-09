# Spike: OpenRouter Batch API for LLM attribute extraction

Date: 2026-10-09. Feeds ADR 0010 (decoupled batch extraction). Nothing was submitted and no
paid call was made. The only live call was the public, key-less `GET /api/v1/models` (and
`/models/{id}:batch/endpoints`) for pricing and capability metadata.

## Sources

- Announcement: https://openrouter.ai/blog/announcements/batch-api/
- Quickstart (the main contract doc): https://openrouter.ai/docs/batch-quickstart
- Create: https://openrouter.ai/docs/api/api-reference/batch/create-a-batch
- Get: https://openrouter.ai/docs/api/api-reference/batch/get-a-batch
- List: https://openrouter.ai/docs/api/api-reference/batch/list-batches
- Delete: https://openrouter.ai/docs/api/api-reference/batch/delete-a-batch
- Python SDK batch module: https://openrouter.ai/docs/client-sdks/python/sdks/batch/README
- Rate limits (general, no batch section): https://openrouter.ai/docs/api/reference/limits
- Models list: https://openrouter.ai/api/v1/models ; UI filter: https://openrouter.ai/models?variant=batch

Caveat on examples: the docs were read through a summarising fetcher that refused verbatim
JSON. The JSON below is **reconstructed from the published schemas and the quickstart's
described examples**, not copy-pasted. Field names and enums are from the schemas; values are
illustrative. Re-check against the live reference page before coding against exact shapes.

## 1. Contract

| Operation | Call |
|---|---|
| Create | `POST https://openrouter.ai/api/v1/batches` -> `202 Accepted`, `status: "validating"` |
| Get (+ results) | `GET /api/v1/batches/{id}` |
| List | `GET /api/v1/batches?limit=1..100&after=<last_id>&status=..&created_after=..&created_before=..` (newest first, `results` always null; scoped to the key's workspace; `status` filter does not accept `finalizing`/`cancelling`) |
| Delete | `DELETE /api/v1/batches/{id}`: terminal batches only, in-flight -> `409`; purges stored artifacts, later GET -> `404` |
| Cancel | **None documented** (see risks) |

Format: **inline JSON array, no JSONL upload, no Files API.** Auth is the normal
`Authorization: Bearer` key.

Create body (`BatchSubmitBody`):

| Field | Required | Notes |
|---|---|---|
| `endpoint` | yes | `/v1/chat/completions`, `/v1/responses`, `/v1/messages`, `/v1/embeddings`; one endpoint per batch |
| `model` | yes | **plain slug** (`openai/gpt-4.1-nano`), not the `:batch` id. No `:batch` endpoint for the model -> `400` |
| `requests[]` | yes | non-empty; each `{custom_id (unique, non-empty), body}`; `body` is a normal request for the chosen endpoint |
| `completion_window` | no | only `"24h"` |
| `provider` | no | only `only` (slug list, merged with account allowlist) and `allow_fallbacks`; nothing else accepted. `only` matching no eligible provider -> `404` |

The quickstart says to put `requests` **last** in the JSON; a `requests`-first body returns `400`.
Serialise with that key order.

```json
{
  "endpoint": "/v1/chat/completions",
  "model": "openai/gpt-4.1-nano",
  "provider": { "only": ["openai"], "allow_fallbacks": false },
  "requests": [
    {
      "custom_id": "olx:12345@3fa9c1",
      "body": {
        "messages": [
          { "role": "system", "content": "..." },
          { "role": "user", "content": "..." }
        ],
        "temperature": 0,
        "response_format": {
          "type": "json_schema",
          "json_schema": { "name": "extraction", "strict": true, "schema": { "type": "object" } }
        },
        "usage": { "include": true }
      }
    }
  ]
}
```

Response `202`:

```json
{
  "id": "batch_123", "object": "batch", "endpoint": "/v1/chat/completions",
  "model": "openai/gpt-4.1-nano", "completion_window": "24h", "status": "validating",
  "created_at": 1791500000, "finalized_at": null,
  "request_counts": { "total": 1, "completed": 0, "failed": 0 },
  "usage": null, "results": null, "error": null
}
```

Structured outputs inside items: the docs do not list `response_format` as unsupported
(rejected per request: empty input, `stream: true`, `speed`, output cap < 1, some Anthropic
beta features; audio/video; `:online`). The only `response_format` statement is for **Google
models: every request in a batch must use the same `response_format`** (all omit, all
`json_object`, or all `json_schema` with the same schema). The `/models` metadata lists
`structured_outputs` and `response_format` in `supported_parameters` for all 76 `:batch`
variants, and the `:batch` endpoints checked list `structured_outputs`. **Not proven end to end;
needs a tiny real test batch (cost is a fraction of a cent).** Items are otherwise passed
through the normal chat-completions path, so `usage: {include: true}` should be harmless but is
unneeded (see section 3).

Provider routing: each batch runs on **one provider**. Default is the cheapest eligible `:batch`
endpoint after account allowlist / data policy / BYOK. Per-item routing params are not used;
batch-level `provider.only|allow_fallbacks` only.

## 2. Lifecycle

Statuses (enum): `validating`, `in_progress`, `finalizing`, `completed`, `failed`, `expired`,
`cancelling`, `cancelled`. Terminal: `completed`, `failed`, `expired`, `cancelled`.

```
 POST -> validating -> in_progress -> finalizing -> completed
             |             |                          (results inline on GET)
             +-> failed    +-> expired (24h window)
                           +-> cancelling -> cancelled   (trigger undocumented)
```

- Polling: `GET /batches/{id}` until terminal. **No recommended interval is documented.**
  Beta timings (blog): median 7 min, p90 1.0 h, p99 10.3 h; single-request batches 5-11 min,
  1000+ requests 12-21 min; 5am-noon Pacific slower (slowest decile 2-4.5 h). Suggest poll
  every 60 s with jitter for the first hour, then 5 min.
- Results: **inline in the `results` array of the GET response** once terminal; no download
  endpoint, no pagination of results. `results` is `null` while running and for
  failed/expired/cancelled batches. The whole result set arrives in one response (a large
  batch means a large body).
- `request_counts`: `{total, completed, failed}`.
- Validation failures: per-request rejections are detected after the `202`; the batch then goes
  to `failed` and batch-level `error: {message}` explains it. So one bad item can fail the
  whole batch at validation time (contrast with execution-time item errors below).
- Expiry: window is 24 h; `expired` is a listed terminal status but the docs do not say what
  results (if any) are available. Assume none (`results: null`).
- Retention: inputs and results deleted 30 days after creation; GET then returns `410 Gone`.
  Delete is manual and optional.
- Billing edge: GET can return `402` when finalized cost exceeds balance (metadata only,
  `results: null`); add credits and poll again, results are kept, the batch is not re-run.
  Submit can return `402` when the estimated cost exceeds balance.
- No `expires_at` field exists; compute `created_at + 24h` (units of `created_at` not stated;
  looks like epoch seconds).

Completed batch (reconstructed):

```json
{
  "id": "batch_123", "object": "batch", "status": "completed",
  "created_at": 1791500000, "finalized_at": 1791500600,
  "request_counts": { "total": 2, "completed": 1, "failed": 1 },
  "usage": {
    "prompt_tokens": 1800, "completion_tokens": 240, "total_tokens": 2040,
    "cost": 0.0000705, "is_byok": false,
    "cost_details": { "upstream_inference_prompt_cost": 0.00005, "upstream_inference_completions_cost": 0.0000205 }
  },
  "error": null,
  "results": [
    {
      "id": "batch_req_1", "custom_id": "olx:12345@3fa9c1",
      "response": {
        "status_code": 200, "request_id": "req_...",
        "body": { "id": "gen-...", "object": "chat.completion", "model": "openai/gpt-4.1-nano",
                  "choices": [ { "message": { "role": "assistant", "content": "{...}" }, "finish_reason": "stop" } ],
                  "usage": { "prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020 } }
      },
      "error": null
    },
    {
      "id": "batch_req_2", "custom_id": "olx:67890@a1b2c3",
      "response": null,
      "error": { "type": "invalid_request_error", "message": "...", "param": null, "error_type": "context_length_exceeded" }
    }
  ]
}
```

## 3. Item errors, cost reporting

- Each result has `id`, `custom_id`, `response`, `error`; **exactly one of `response` /
  `error` is populated**. Item failures do not fail the batch (docs: "each result returns
  independently, so bad rows don't fail the job"), but see validation failures above.
- `error` shape: `{type, message, param|null, error_type}` where `error_type` is an enum:
  context_length_exceeded, max_tokens_exceeded, token_limit_exceeded, string_too_long,
  authentication, permission_denied, payment_required, rate_limit_exceeded, provider_overloaded,
  provider_unavailable, invalid_request, invalid_prompt, not_found, precondition_failed,
  payload_too_large, unprocessable, content_policy_violation, refusal, invalid_image,
  image_too_large, image_too_small, unsupported_image_format, image_not_found,
  image_download_failed, server, timeout, unmapped. (The quickstart gives no error example, and
  the schema pages differ on whether `error_type` is required, so parse defensively.) Retryable
  candidates: `rate_limit_exceeded`, `provider_overloaded`, `provider_unavailable`, `server`,
  `timeout`. Permanent: `context_length_exceeded`, `content_policy_violation`, `refusal`,
  `invalid_*`.
- `response.status_code` can presumably be non-200 with a body; handle both channels.
- `response.body.id` is a generation id (usable with the feedback API).
- **Cost is reported per batch**: `usage.cost` (USD, what OpenRouter charges; for BYOK only the
  BYOK fee, with `cost_details` holding the upstream estimate), plus `prompt_tokens`,
  `completion_tokens`, `total_tokens`, `*_tokens_details` (incl. `reasoning_tokens`,
  `cached_tokens`). Per-item cost is **not documented**; the per-item examples show token counts
  only. Per-item cost for the ADR: allocate batch cost pro rata by per-item tokens (or compute
  from the `:batch` price x item tokens). Treat as estimate; record `estimated: true`.
- The sync adapter reads `usage.cost` from the response; for batches read `usage` from each
  `response.body.usage` for tokens and from the batch object for cost.

## 4. Limits

| Limit | Value |
|---|---|
| Payload size | **200 MB** (`413`), from the Create reference |
| Max items per batch | **not documented** (only `minItems: 1`; quickstart hints "very large" is OK; beta saw 1000+) |
| Max open batches | not documented |
| Rate limits | not documented for batch; `429` "Batch API rate limit exceeded for the billable entity", no numbers, no `Retry-After` promise. General guidance: exponential backoff, honor `Retry-After` |
| Window | 24 h fixed |
| Retention | 30 days |
| Balance | `402` at submit if the estimate exceeds balance |

Other restrictions: images/files must be public URLs, no audio/video, no `stream`, no
`:online`/web-search plugin. Irrelevant to text extraction.

Submit error codes: 400 (malformed, model has no batch endpoint), 401, 402, 403 (policy), 404
(`provider.only` unmatched), 413, 422 (constraints / custom_id), 429, 500, 502. Envelope
`{"error": {"code": int, "message": str}}`.

## 5. Model discovery

Public, key-less `GET /api/v1/models` returns each batch variant as a **separate model entry
with id `<slug>:batch`** (76 of 458 on 2026-10-09), carrying its own `pricing` (already the batch
price) and `supported_parameters`. List batch-capable models programmatically with
`[m for m in models if m["id"].endswith(":batch")]`. Per-provider detail:
`GET /api/v1/models/{slug}:batch/endpoints`. Submit with the plain slug (the `:batch` id is a
catalogue entry, not a submit parameter). Some entries carry `pricing.overrides` (e.g. Haiku 5.5:
higher price above 100k prompt tokens); irrelevant at our prompt sizes.

## 6. SDK compatibility

The `openai` Python SDK's batches API (`client.files.create` -> `client.batches.create(input_file_id=...)`,
`client.batches.retrieve`, `client.files.content`) is **not compatible**: OpenRouter has no Files
API and no JSONL upload, create takes an inline `requests` array with a different top-level
shape, results are inline in the batch object, and there is no cancel. Nothing in the docs
claims OpenAI-SDK compatibility for `/batches`. Options:

1. **Raw `httpx`** (recommended): 3 calls (POST, GET, optional DELETE), tiny surface, full
   control of key order, retries and typed parsing with pydantic. The project already depends on
   httpx.
2. `client.post("/batches", body=..., cast_to=dict)` on the existing `AsyncOpenAI` instance as an
   escape hatch (shares base_url and auth), untested.
3. OpenRouter's own Python SDK (`open_router.batch.create_batches`): extra dependency; would
   need dependency vetting. Not worth it.

## 7. Model shortlist (cheap, fast, structured outputs)

Prices per 1M tokens, USD, from `/api/v1/models` on 2026-10-09 (input/output). All have
`structured_outputs`; the `:batch` endpoints for the first four were checked and list
`structured_outputs`. Polish extraction quality is **not verified**; these are candidates for the
ADR's comparison round.

| Model (slug) | Sync in/out | Batch in/out | Batch provider(s) | Notes |
|---|---|---|---|---|
| `openai/gpt-4.1-nano` | 0.10 / 0.40 | **0.05 / 0.20** | OpenAI | non-reasoning, fast, 1M ctx; safest default |
| `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | **0.05 / 0.20** | Google AI Studio, Vertex EU | all items must share one `response_format` (we do); strong multilingual |
| `mistralai/mistral-small-2603` | 0.15 / 0.60 | **0.075 / 0.30** | Mistral | good Polish/EU languages, 262k ctx |
| `openai/gpt-5-nano` | 0.05 / 0.40 | **0.025 / 0.20** | OpenAI | cheapest of the group but a reasoning model: reasoning tokens bill as output, set low reasoning effort and measure |

Runners-up: `openai/gpt-4o-mini` (0.15/0.60 -> 0.075/0.30), `mistralai/ministral-8b-2512`
(0.15/0.15 -> 0.075/0.075; small model, likely weaker on specs), `google/gemini-3.1-flash-lite`
(0.25/1.50 -> 0.125/0.75). Beware of anomalies: for some entries the catalogue batch price is
**not** half the sync price (e.g. `openai/gpt-oss-20b` batch 0.024/0.112 vs sync 0.018/0.090;
`z-ai/glm-5.3` batch 0.45/2.00 vs sync 0.05/6.00), so the discount is per model, not a flat 50%
(the blog: "generally 50%, sometimes less"). Compare actual `:batch` price per candidate.

Rough scale: at ~1.5k input + ~150 output tokens per offer, 368 offers on gpt-4.1-nano batch is
about 0.03 USD, so model price is nearly irrelevant next to accuracy; pick on fill rate and
accuracy.

## 8. Implications and risks for ADR 0010

1. **No cancel.** The port's `cancel()` has no API behind it. Statuses `cancelling/cancelled`
   exist but no endpoint is documented (DELETE is explicitly not cancellation, `409` in flight).
   Drop `cancel` from `BatchExtractionBackend` or make it local-only (abandon: release leases,
   mark batch `abandoned`, ignore results if they appear; you may still be billed).
2. **Results are one inline blob, no pagination.** `results()` as an `AsyncIterator` is fine
   as an interface, but the adapter must read the whole GET body (large batches = big JSON).
   Cap `batch.max_size` (e.g. 500-2000) to keep bodies and per-batch blast radius small.
3. **Validation failure kills the entire batch** (`status: failed`, batch-level `error.message`),
   unlike item-level execution errors. ADR's "failed items -> backoff" must be complemented by
   "failed batch -> items back to backlog with backoff, and quarantine suspicious items after a
   repeated batch failure" (bisect or single-item retry to find a poison item; also keep
   `custom_id` unique and non-empty).
4. **`expired` returns no results** (`results: null`): the whole batch is lost, and partial
   completion is not salvageable. ADR 0010 lists EXPIRED/FAILED correctly; no partial ingest
   is possible. Worst-case 24 h latency, p99 about 10 h. Keep `max_wait` and the `auto` mode
   sync fallback.
5. **Per-item cost does not exist.** ADR 0007/0010 store "token usage and cost" per extraction
   and per batch: per batch is exact (`usage.cost`), per item must be allocated pro rata by
   tokens. Mark it as an estimate.
6. **`custom_id` format.** `<source>:<external_id>@<content_hash>` is allowed (any non-empty
   unique string); the length limit is undocumented, keep it short (hash prefix).
7. **Model selection must be batch-aware.** The configured model must have a `:batch` catalogue
   entry or submit returns `400`. Add a startup/`extract status` check against `/models`
   (`id + ":batch"` present and `structured_outputs` in `supported_parameters`) and fall back to
   sync mode otherwise (consistent with `extraction.mode: auto`).
8. **Structured output must be proven.** Not documented for batch; run a 5-item real test batch
   before relying on `json_schema strict`. Keep the existing `json_object` fallback decision
   per **batch** (not per item): the sync adapter downgrades on a `BadRequestError`, but in
   batch the rejection arrives asynchronously as a failed batch or item errors, so the choice
   (`structured_output` flag) must be config-time. Gemini needs an identical `response_format`
   across the batch; send one schema per batch (our categories schema is fixed per batch
   anyway, as the catalog fingerprint is part of the batch).
9. **No corrective retry in a batch** (already in the ADR); the sync adapter's one corrective
   retry does not carry over. Expect a slightly higher invalid-output rate; the backlog loop
   re-submits them in the next batch.
10. **Provider pinning.** Batch-level `provider.only/allow_fallbacks` only; set
    `allow_fallbacks: false` plus `only` if the account data policy matters. Different
    providers behind the same model can differ in quality, and a batch is single-provider, so
    record the provider if it is surfaced (not shown in the batch object; check logs tab).
11. **Polling.** No documented interval or rate limit: use adaptive polling (60 s early,
    5 min after an hour), honor `429`/`Retry-After`, and use `GET /batches?status=...` to
    reconcile after a crash (list is workspace-wide: include a recognisable marker, e.g. the
    `custom_id` prefix, because batches carry no metadata/name field; persist the provider
    batch id immediately after the `202` so it is never lost).
12. **Idempotent submit is not offered** (no idempotency key documented). A crash between the
    POST and persisting the id can orphan a paid batch. Mitigation: write the local
    `extraction_batches` row (status `submitting`) before POST; on restart list recent batches
    and match by `created_at` window + `request_counts.total` + `custom_id` set before
    resubmitting.
13. **Retention.** 30 days is plenty; delete after ingest (optional) to limit data held at the
    provider. Persist raw results only if wanted for audit: after 30 days GET returns `410`.
14. **Auth/cost guards.** `402` at submit when the estimate exceeds the balance: treat as a
    non-retryable-for-now state (park the backlog, surface in `q health`) rather than backoff
    spam.
15. ADR "Open points" answered: contract (inline array, 202/poll/inline results), structured
    output (likely yes, unproven), batch-capable models (76 `:batch` ids, shortlist above), model
    comparison still to run. Unknowns left: max items, max open batches, rate limits, the
    `expired` semantics, the exact failed-batch `error` content, item `error` for
    structured-output refusals.

# Research spike: cheap / free extraction providers

Date: 2026-10-09. Scope: docs only. No paid or authenticated API calls were made; everything
below comes from public documentation pages read on this date. Context: ADR 0010 section 8
(provider profiles, structured-output levels `json_schema | json_object | prompt_only`) and
ADR 0007. Task: ~900 input tokens + ~150 output tokens per offer, ~7 typed fields, Polish text.

Legend: **[doc]** = stated on an official page; **[3rd]** = third-party, unverified;
**[est]** = my estimate, benchmark before relying on it.

## 1. Decision table

| Option | Cost | Speed (400 offers) | Privacy | `structured_output` to configure | Setup |
|---|---|---|---|---|---|
| **Ollama, local** (recommended default) | 0 (electricity) | ~20-35 min [est] | Fully local | `json_schema` (try first), fall back to `json_object` | Install Ollama, `ollama pull`, set `OLLAMA_KEEP_ALIVE=-1`, bind `0.0.0.0` if the app runs in Docker |
| **LM Studio, local** | 0 | same as Ollama (llama.cpp) [est] | Fully local | `json_schema` (grammar-based for GGUF) | Install, download model, enable server, JIT load or `lms load` |
| **Gemini free tier** (AI Studio key) | 0 | rate-limit bound, see 2.1 | **Free-tier content is used to improve Google products and humans may read it** [doc]. Only use data you are fine sharing. | `json_schema` via native API; `json_object` fallback | AI Studio key, no card |
| **Gemini paid, sync/batch** | Flash-Lite $0.25 in / $1.50 out per 1M (3.1) or $0.30 / $2.50 (3.5); batch is half [doc]. 400 offers is about 0.36M in + 0.06M out, so roughly 10 US cents sync, 5 cents batch | seconds to 24 h for batch | Paid data terms: not used for training [doc] | `json_schema` | Enable billing on the Cloud project |
| **Groq free** | 0 | fast, limits tight (e.g. 30 RPM, 8K TPM on gpt-oss-120b [doc]) | Hosted; check terms | `json_schema` only on gpt-oss-20b/120b, qwen3.8-27b; others `json_object` [doc] | Key, OpenAI-compatible |
| **Cerebras** | No permanent free tier; $5 credit expires after 30 days [doc] | fast | Hosted | not verified | skip |
| **Mistral Experiment (free)** | 0 | low RPM [3rd] | Free tier requires accepting data use for training [3rd] | `json_schema` (not verified) | Not recommended |
| **OpenRouter `:free`** | 0 | 50 req/day without credits, 1000/day with 10 credits purchased [doc] | Free model providers may log | model-dependent | Existing adapter |
| **OpenRouter paid + batch** (ADR 0010 main path) | cents | 7 min median in beta | Prompt not logged by default [doc] | `json_schema` | Existing |

Recommendation: default profile `local` (Ollama), `fallback: [local, google, openrouter]`.
Gemini free only for non-sensitive marketplace text. Public offer text is arguably fine, but
it is the user's decision (sections 2.1 and 6).

## 2. A. Google AI Studio / Gemini API

### 2.1 Free tier

- Pricing page: Flash and Flash-Lite models are "free of charge" on the standard free tier;
  Batch and Flex are **not** available on the free tier; Gemma 4 is free with no paid tier.
  https://ai.google.dev/gemini-api/docs/pricing
- Current lineup (stable): `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`,
  `gemini-3.5-flash` (legacy), **`gemini-3.5-flash-lite`**, **`gemini-3.1-flash-lite`**.
  2.5 models (`gemini-2.5-flash-lite`) are limited to users who already used them; 2.0 models
  are shut down. https://ai.google.dev/gemini-api/docs/models
  The ADR example `gemini-2.5-flash-lite` is therefore stale: use `gemini-3.1-flash-lite`.
- **Exact free-tier RPM/RPD/TPM are not published in the docs.** The rate-limit page says they
  are per project, vary by model, and are only visible in AI Studio (aistudio.google.com/rate-limit).
  https://ai.google.dev/gemini-api/docs/rate-limits
  Third-party figures (unverified and contradictory): Flash-Lite about 15 RPM / 250K TPM / 500
  RPD, Gemma 4 about 15 RPM / 1,500 RPD [3rd]. Limits were cut before (Dec 2025 per one blog).
  **Action: open AI Studio once, read the real numbers for the chosen model, put them in
  `rate_limit`.** At 15 RPM, 400 offers take about 27 min; at 500 RPD it fits in one day.
- **Data use (important):** for unpaid services Google "uses submitted content and generated
  responses to provide, improve, and develop" its products and ML; human reviewers may read
  inputs and outputs (disconnected from account/key); the terms say not to submit sensitive,
  confidential or personal information. Paid services: not used to improve products, prompts
  logged only for abuse detection/legal. In the EEA, Switzerland and UK the paid terms apply to
  all services, including free quota. https://ai.google.dev/gemini-api/terms
  Marketplace offers contain seller phone numbers or names sometimes; strip them before sending.

### 2.2 Gemma via the Gemini API

- Models: `gemma-4-31b-it` and `gemma-4-26b-a4b-it`. Documented features: system instructions,
  thinking toggle (`thinkingLevel` "minimal" to disable), function calling, image input,
  Search grounding. https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- **JSON mode / `responseSchema` for Gemma is not documented** on the Gemma page or the
  structured-output page. A third-party guide claims Gemma 4 supports structured output
  (https://www.philschmid.de/gemma-4-gemini-api), but treat it as unverified.
  So: for Gemma use `json_object`/`prompt_only` until a smoke test proves `json_schema`.
  Gemini Flash-Lite is the safer free option for strict schemas.

### 2.3 OpenAI-compatible endpoint vs native

- OpenAI-compat: base URL `https://generativelanguage.googleapis.com/v1beta/openai/`,
  `Authorization: Bearer <GEMINI_API_KEY>`. Docs call it **beta**; structured output is shown
  only through the SDK `parse()` helper, and the page does not explicitly document
  `response_format: {type: json_schema}`; thinking cannot be disabled on 3.x models;
  batch file upload is not supported through it. https://ai.google.dev/gemini-api/docs/openai
- Native: `generateContent` with JSON mime type + schema. Documented (in current docs, via the
  `response_format` object with `mime_type: application/json` and `schema`, in the Interactions
  API; classic `generationConfig.responseMimeType` + `responseSchema`/`responseJsonSchema` still
  exists in the REST API). Supports a **subset** of JSON Schema: types, enum, properties,
  required, additionalProperties, min/max, items, anyOf, $ref; very large or deeply nested
  schemas may be rejected. https://ai.google.dev/gemini-api/docs/structured-output
- **Recommendation: the `gemini` adapter should use the native REST API** (matches ADR 0010
  "native API"; documented structured output, system instruction, batch, thinking control,
  safe `rate_limit`/429 handling). Keep the OpenAI-compatible URL only as a manual
  `openai_compatible` profile for experiments. Keep our schema inside the supported subset
  (enums for category/storage_type/condition, nullable numbers) and always validate ourselves.
- Pin a non-thinking configuration for 3.x if possible (thinking tokens count against output
  and latency); verify the current thinking parameter for the chosen model.

### 2.4 Gemini Batch API

- 50% of standard price; target turnaround 24 h, often faster; expires after 48 h; results kept
  6 weeks. Two input modes: **inline** requests (total under 20 MB) or **JSONL file** via File
  API (up to 2 GB; recommended for big jobs). Supports system instructions and JSON schema per
  request. Job creation is not idempotent (resubmit = duplicate job). Check `failedRequestCount`.
  https://ai.google.dev/gemini-api/docs/batch-api
- **Not on the free tier** [doc, pricing page]. Paid Flash-Lite batch: 3.1 = $0.125 in /
  $0.75 out per 1M; 3.5 = $0.15 / $1.25. 400 offers cost about 1-2 US cents. A later
  `BatchExtractionBackend` for `gemini` is feasible but pointless for free use.

## 3. B. Local on RTX 5060 Ti 16 GB (Windows)

### 3.1 Ollama vs LM Studio

| | Ollama | LM Studio |
|---|---|---|
| OpenAI base URL | `http://localhost:11434/v1/` (key ignored, any string) | `http://localhost:1234/v1` |
| Structured output | Native `format` = JSON schema (grammar-constrained); OpenAI-compat `response_format` is listed as supported and the structured-outputs doc says it works through `/v1`, but the compat page does not spell out `json_schema`: **smoke test it** | `response_format: {type: json_schema, json_schema: {...}}` in OpenAI format; GGUF uses llama.cpp grammar sampling, MLX uses Outlines. Docs warn that models under 7B may not support it well |
| Keep loaded | `OLLAMA_KEEP_ALIVE=-1` (default 5 min) or `keep_alive: -1` per request | JIT-loaded models auto-unload after a TTL; use `lms load` / set TTL, or keep the UI-loaded model |
| Parallel | `OLLAMA_NUM_PARALLEL` (default 1); VRAM scales with parallel x context | not documented on the pages I read; keep `concurrency: 1` |
| Context | Default 4096; set `OLLAMA_CONTEXT_LENGTH=8192` (prompt 900 + desc + output fits) | set in model load settings |
| Docker reach | Binds 127.0.0.1 by default; set `OLLAMA_HOST=0.0.0.0:11434`; from a container use `http://host.docker.internal:11434/v1` | server must listen beyond localhost ("serve on network" setting; not verified in docs read); use `http://host.docker.internal:1234/v1` |
| Windows | Tray app; env vars via "Edit environment variables for your account", restart Ollama | GUI, or headless `llmster` daemon (`lms daemon up`) |

Sources: https://docs.ollama.com/faq, https://docs.ollama.com/api/openai-compatibility,
https://docs.ollama.com/capabilities/structured-outputs,
https://lmstudio.ai/docs/developer/openai-compat/structured-output,
https://lmstudio.ai/docs/developer/core/headless.
Ollama Cloud does not support structured outputs (do not use `:cloud` tags for this).
Docker Desktop on Windows resolves `host.docker.internal` out of the box. Windows firewall
may prompt on first bind to 0.0.0.0.

Recommendation: **Ollama** as the primary (simple, `keep_alive`, native `format`), LM Studio
as a second profile for people who prefer a GUI. Both go through the same
`openai_compatible` adapter.

### 3.2 Model shortlist (16 GB)

Speeds: only two **measured** numbers exist for this card (Ollama, Q4_K_M, generation only):
Llama 3.1 8B 75 tok/s and Qwen2.5 14B 42 tok/s, per
https://computingforgeeks.com/rtx-5070-ti-vs-5060-ti-local-ai/. Everything else is [est]
scaled by size (memory-bandwidth bound). Sizes from the Ollama library pages.

| Model (Ollama tag) | Size / quant | tok/s gen | Polish | JSON reliability with constrained decoding |
|---|---|---|---|---|
| `qwen2.5:7b-instruct` | ~4.7 GB Q4 [est] | ~70-80 [est] | decent | good |
| `qwen3:8b` | 5.2 GB [doc] | ~65-75 [est] | good | good; **disable thinking** (`think:false` / `reasoning_effort:none`) |
| `qwen2.5:14b-instruct` | ~9 GB Q4 [doc via 3rd] | **42 (measured)** | good | very good |
| `qwen3:14b` | 9.3 GB [doc] | ~35-42 [est] | good | very good, disable thinking |
| `gemma3:12b` | ~8 GB | ~36-40 [est, 3rd] | good (Gemma is strong multilingual) | good |
| `gemma4:12b` | 7.7-8.0 GB, 256K ctx [doc] | ~40 [est, 3rd] | likely good | unverified; test |
| `qwen3.5:9b` | 6.6-7.6 GB [doc] | ~55-65 [est] | good | thinking by default; disable it |
| `llama3.1:8b` | ~4.9 GB | 75 (measured) | weak-medium in Polish | ok |
| Bielik 11B v3 (`SpeakLeash/bielik-11b-v3.0-instruct`) | ~7 GB Q4 [est] | ~40-45 [est] | **best Polish** (native Polish model) | ok with constrained decoding; weaker instruction following than Qwen |
| Bielik 4.5B/7B minitron v3 | 3-5 GB | 70+ [est] | very good for size | ok |

Ollama library: https://ollama.com/library/qwen3, https://ollama.com/library/gemma4,
https://ollama.com/library/qwen3.5, https://ollama.com/search?q=bielik.
Note: MoE models (Gemma 4 26B-A4B, Qwen3.x 35B-A3B) hit 90-150 tok/s on a 16 GB 4080
(https://glukhov.org/llm-performance/benchmarks/best-llm-on-16gb-vram-gpu/) but need 13-18 GB
quants; on 16 GB with context they offload and slow down, so they are not "comfortable".

**Picks (to be confirmed by `scrappy extract bench` on ~30 labelled offers):**
1. **Fastest acceptable: `qwen3:8b` (or `qwen2.5:7b-instruct`), thinking off.** About 70 tok/s.
2. **Best quality: `qwen2.5:14b-instruct`** (or `qwen3:14b` thinking off). Measured 42 tok/s,
   9 GB, leaves room for 8K context. Challenger worth benching: Bielik 11B v3 for Polish
   slang in descriptions ("sprawna, bez rys, bateria 4h").

### 3.3 Time estimate for 400 offers

Per offer: prefill 900 tokens at roughly 1,000-2,500 tok/s for 8-14B on this card [est] =
0.4-0.9 s; generation 150 tokens at 42 tok/s (14B) = 3.6 s, at 70 tok/s (8B) = 2.1 s. Add
schema-grammar overhead and model-side JSON whitespace.

| Model | Per offer | 400 offers |
|---|---|---|
| 8B | ~2.5-3.0 s | ~17-20 min |
| 14B | ~4.5-5.0 s | ~30-35 min |

Output tokens dominate, so keep the output schema compact (short keys, no prose, no
reasoning fields). Cold model load is 5-15 s: keep it resident. With
`OLLAMA_NUM_PARALLEL=2`, throughput may rise 1.3-1.6x [est] at the cost of VRAM; start at 1.

**Grammar-constrained decoding:** it guarantees syntactically valid JSON and schema-conformant
keys/enums, which removes most failures of small models (broken braces, extra prose, invented
enum values). It does not improve correctness of the values (a 7B can still pick the wrong GPU),
so keep our post-validation, a `null`-allowed schema, and "unknown" instead of guessing.
Put the schema also in the prompt (Ollama docs recommend this) and use temperature 0.
Caveat: constraining on a thinking model can fight the reasoning, so disable thinking.

## 4. C. Hosted alternatives (short)

- **Groq:** free plan, org-level limits; example gpt-oss-120b 30 RPM, 1K RPD, 8K TPM, 200K TPD
  [doc]. 8K TPM means about 8 offers/min at ~1K tokens. Strict `json_schema` only on
  `openai/gpt-oss-20b`, `gpt-oss-120b`, `qwen/qwen3.8-27b`; other models `json_object` only.
  https://console.groq.com/docs/rate-limits, https://console.groq.com/docs/structured-outputs
  Viable free overflow: gpt-oss-20b, 400 offers in about 50 min at TPM cap.
- **Cerebras:** no permanent free tier, $5 credit for 30 days. Skip.
  https://inference-docs.cerebras.ai/support/rate-limits
- **Mistral free (Experiment):** official limits not found; third parties say ~1B tokens/month,
  low RPM, and data used for training. Not recommended.
- **Together / DeepInfra:** no relevant permanent free tier found; paid per-token, cheap but not
  free. Not researched further.
- **OpenRouter `:free` models:** 50 req/day without credits [doc]. Not enough alone.
  https://openrouter.ai/docs/faq

## 5. Ready-to-paste `config/extraction.yaml` profiles (ADR 0010 section 8 format)

```yaml
default_profile: local
fallback: [local, google, openrouter]
profiles:
  local:                                # Ollama on the host GPU
    provider: openai_compatible
    # app on host:    http://localhost:11434/v1
    # app in Docker:  http://host.docker.internal:11434/v1  (needs OLLAMA_HOST=0.0.0.0:11434)
    base_url: http://host.docker.internal:11434/v1
    model: qwen2.5:14b-instruct         # fast alternative: qwen3:8b (thinking off)
    mode: sync
    concurrency: 1
    structured_output: json_schema      # fall back to json_object if the smoke test fails
    temperature: 0
    extra_body:                         # adapter should pass through
      keep_alive: -1                    # keep the model resident
      options: {num_ctx: 8192}
    # for qwen3 / qwen3.5 / gemma4 add: reasoning_effort: none  (disable thinking)
    api_key: ollama                     # ignored by Ollama, required by clients
  lmstudio:
    provider: openai_compatible
    base_url: http://host.docker.internal:1234/v1   # http://localhost:1234/v1 on host
    model: qwen2.5-14b-instruct         # id as shown by GET /v1/models
    mode: sync
    concurrency: 1
    structured_output: json_schema      # llama.cpp grammar sampling for GGUF
    temperature: 0
    api_key: lm-studio
  google:                               # Gemini free tier; see privacy caveat
    provider: gemini                    # native API; model must support responseSchema
    model: gemini-3.1-flash-lite        # or gemini-3.5-flash-lite
    mode: sync                          # Batch is NOT available on the free tier
    api_key_env: GEMINI_API_KEY
    rate_limit: 10/min                  # placeholder: read real RPM/RPD in AI Studio
    daily_limit: 400                    # placeholder, same
    structured_output: json_schema
    temperature: 0
  google_gemma:                         # optional, schema support undocumented
    provider: gemini
    model: gemma-4-26b-a4b-it
    mode: sync
    api_key_env: GEMINI_API_KEY
    rate_limit: 10/min
    structured_output: prompt_only      # promote to json_schema only after a smoke test
```

Keys beyond ADR 0010 (`extra_body`, `temperature`, `daily_limit`, `api_key`) are proposals;
add them to the profile schema or drop them.

## 6. Caveats

1. Gemini free-tier numeric limits could not be confirmed from official pages. Read AI Studio.
2. Gemini free tier trains on and may human-review prompts. For this project (public offers)
   probably acceptable, but strip phone numbers and names first; the user decides.
3. Gemma on the Gemini API: JSON schema support is undocumented. Prefer Flash-Lite for strict mode.
4. The OpenAI-compat Gemini endpoint is beta and its `response_format` json_schema support is not
   explicitly documented. Native adapter recommended.
5. Ollama `/v1` `response_format` json_schema: per the Ollama docs it works but the compat page
   does not list it explicitly. The adapter's health check should run a tiny schema request and
   downgrade the profile to `json_object`/`prompt_only` on failure (matches ADR 0010 health check).
6. Qwen3 / Qwen3.5 / Gemma 4 think by default; thinking text inflates latency and may break
   constrained output. Disable it (`reasoning_effort: none` on the OpenAI endpoint, `think:false`
   on the native one) and verify.
7. Windows + Docker: container reaches the host through `host.docker.internal`; Ollama must bind
   `0.0.0.0` (and Windows Firewall may block it). Run Ollama on the host, not in Docker, on Windows
   to keep GPU access simple.
8. Speeds are mostly estimates except Llama 3.1 8B (75 tok/s) and Qwen2.5 14B (42 tok/s). The
   bench command in ADR 0010 should decide, using `eval_count / eval_duration` from Ollama.
9. Context default in Ollama is 4096 tokens: a 4000-char description (~1.5K tokens) plus prompt
   fits, but set 8192 to avoid silent truncation.
10. Model names/limits above move quickly (Gemini 2.0/2.5 already retired or restricted). Re-check
    before implementation.

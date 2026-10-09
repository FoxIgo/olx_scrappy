# Implementation plan

Built in phases by subagents. Sonnet does well-specified work; Opus does the core
modelling. Each phase ends with `uv run poe check` green (lint, types, layer contracts, tests).

| # | Phase | Model | Depends on | Status |
| --- | --- | --- | --- | --- |
| 0a | Scaffold: uv package, layer skeleton, import-linter, Docker, compose | Sonnet | — | done (Docker build not yet tested: daemon was off) |
| 0b | Spike: what structured data olx.pl exposes, plus test fixtures | Sonnet | — | done → [research/olx-pl-spike.md](research/olx-pl-spike.md) |
| 1 | Domain + application: entities, value objects, rules, ports, use cases, job handlers, in-memory fakes, unit tests | **Opus** | 0a | done → [adr/0008](adr/0008-core-model-decisions.md), 188 tests |
| 2a | Persistence: SQLite repositories, migrations, `SqliteJobQueue` | Sonnet | 1 | done (async SQLAlchemy + aiosqlite, Alembic, unit scenarios re-run on SQL) |
| 2b | Scraping engines: `PageFetcher`, httpx / Scrapling adapters, decorators (rate limit, retry, fallback, archive) | Sonnet | — (engines don't depend on application) | done. Note: Scrapling 0.4.15 needs `playwright` even for HTTP fetchers, so `curl_cffi` is the practical tier-1 engine |
| 2c | OLX recipe: urls, parser, mapper, classifier, fixture tests | Sonnet | 1, 0b | done (category-path URLs not yet supported) |
| 2d | LLM extractor: OpenRouter adapter, prompt builder, schema → pydantic, + config loading | Sonnet | 1 | done (default model openai/gpt-4o-mini) |
| 3 | Presentation + composition root: Typer CLI, worker loop, `main.py` wiring, URL validation on `search add` | Sonnet | 2* | done |
| 4 | End-to-end: real run of one saved search (`--inline`), Docker run, run report | Sonnet | 3 | done without LLM (173 offers, re-run: 0 duplicates, 0 snapshots); LLM + Docker pending |

## First vertical slice (definition of done)

```
scrappy search add gtx-laptops "<olx url>" --category laptop
scrappy run gtx-laptops --inline
scrappy offers list gtx-laptops --relevant --where "ram_gb>=16"
```

All offers are discovered and enriched with descriptions, then deduplicated, classified,
and given attributes. Re-running fetches only new or changed offers. The same works via
`docker compose up worker`.
| 5 | Decoupled batch extraction ([adr/0010](adr/0010-decoupled-batch-extraction.md)): extraction state + leases, profiles (`config/extraction.yaml`), reconciler (sync mode, fallback chain, backoff/parking), `scrappy extract` (`--inline`, `--max N`, `status`, `profiles [--probe]`, `force`), generic OpenAI-compatible adapter | Opus | 4 | done for sync mode: pyright, import-linter, ruff and 825 offline tests green; live smoke test against LM Studio (`google/gemma-4-12b-qat`, `reasoning_effort: none`, ~5.5 s and ~120 output tokens per offer). Default profile is now the Google AI Studio free-tier chain `gemini-lite` -> `gemini-lite-31` -> `gemma-31b` -> `gemma-26b` (per-model quotas, `quota_timezone` America/Los_Angeles daily reset, 429 per-day/per-minute classification without offer penalty, 5xx retry, `<thought>` stripping); `lmstudio` and paid `openrouter` stay defined outside the chain. ADR 0011 slice 1 done: laptop schema v2 (vram, refresh, resolution, battery, RAM upgrade facts; better `screen_in`/`condition`/`gpu`/`cpu` descriptions), all-null extractions rejected, persistent 5xx/timeouts cost no attempt (851 tests). **Open:** OpenRouter batch adapter (batch mode is modelled and tested against a fake backend only), native Gemini batch (the OpenAI-compatible endpoint covers sync), no tokens-per-minute limiter, extraction prompt quality (e.g. `gpu`/`screen_in` nulls, local-vs-OpenRouter comparison via `extract force --where`) |
| 6 | Components and benchmarks ([adr/0011](adr/0011-components-benchmarks-scoring.md) slice 2): domain `Component`/`ComponentAlias`/`Benchmark` and the pure `component_slug` normalizer, tables `components`, `component_aliases`, `component_benchmarks` (migration 0003), `ImportBenchmarks` (idempotent upsert) and `ListComponents`, Blender Open Data adapter (streams the zip, pinned Blender 4.5.0, median of the summed scene scores) with a download helper, `scrappy benchmarks import [--file PATH \| --download]` / `list [--kind] [--search] [--limit]` | Opus | 4 | done: gate green (967 tests). Real snapshot (2026-10-09): 942 components (653 CPU, 289 GPU) imported in ~10 s. **Open:** Intel Iris Xe / generic iGPUs are absent from the data (named just "Intel(R) Graphics"); "GTX 1650"-style names mix desktop and laptop runs; slice 3 (offer -> component resolution) and slice 4 (scoring) not started |

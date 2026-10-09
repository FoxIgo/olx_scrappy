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

# ADR 0006 — Pipeline as stages connected by a durable job queue

Status: **proposed**

## Context

Requirements R3, R6, R8, R11, R13: three phases with very different costs (discovery,
offer pages, LLM), resumable runs, medium volume, a separate worker, and the ability to
add stages later (images, notifications, agents) without rewriting the flow.

## Decision

### Stages are job handlers; stages talk only through the queue

```
 trigger (CLI / cron / API / agent)
        │  StartRun(search)
        ▼
 ┌──────────────┐  per page   ┌───────────────┐ new/changed ┌───────────────┐
 │ DiscoverPage │────────────►│  EnrichOffer  │────────────►│ ExtractOffer  │
 │ (list page)  │ next page ↺ │ (offer page)  │ content     │ (LLM, no tools│
 └──────────────┘             └───────────────┘ hash changed│  no browsing) │
        │                            │                      └───────────────┘
        ▼                            ▼                              ▼
  upsert offer (list data)    update offer + snapshot       attributes + category
  link search↔offer           FetchOutcome → status (R9)    → relevance on links
```

| Job | Input | Does | Enqueues |
| --- | --- | --- | --- |
| `DiscoverPage` | run_id, page_url | fetch + parse results page, dedup, upsert list data, link search↔offer | next page; `EnrichOffer` for offers that are new or whose list data changed (R8) |
| `EnrichOffer` | offer_id | fetch offer page, classify outcome, update state, write snapshot if changed | `ExtractOffer` if `content_hash` changed |
| `ExtractOffer` | offer_id, content_hash | build extraction input → `AttributeExtractor` → validate → store | — |

- A run is **complete** when it has no pending jobs left. Its status and metrics are
  aggregated from its jobs (ADR 0005).
- **Resumability (R6) comes for free:** a failed job stays `failed/pending` with its
  attempt count. Resuming a run = re-queueing its unfinished jobs.
- **Idempotent handlers:** each job can run twice safely (upserts, content-hash checks).
  At-least-once delivery is enough; no exactly-once machinery needed.
- **Dedup within a run:** a job key such as `enrich:{offer_id}:{run_id}` is unique, so an
  offer that appears on 3 pages is enriched once.

### Why "elastic"

- **Trigger policy is config, not code.** E.g. `pipeline.extract.auto: true` means
  `EnrichOffer` enqueues `ExtractOffer`; `false` means extraction runs only via
  `scrappy extract --pending`. Same handler either way.
- **Re-running one stage on its own:** `scrappy extract --category laptop --schema-version 3`
  re-queues extraction from stored data, with no re-scraping.
- **New stage = new job type + handler + one enqueue rule.** Image download,
  notifications, and agent hooks all slot in the same way.
- **Per-stage concurrency:** HTTP stages are limited by politeness per host; the LLM
  stage can run in parallel at its own limit. Different worker pools later if needed.

### Ports

```python
class JobQueue(Protocol):            # application/ports
    def enqueue(self, job: Job, *, dedup_key: str) -> None: ...
    def claim(self, types: set[JobType], limit: int) -> list[Job]: ...
    def complete(self, job_id, result) -> None: ...
    def fail(self, job_id, error, *, retry_at: datetime | None) -> None: ...
```

- Now: `SqliteJobQueue` (a table in the same DB, polled by the worker).
- Later: Postgres `FOR UPDATE SKIP LOCKED`, or Redis/arq, without changing handlers.

### Processes

- **Trigger side** (CLI, later API/agents): writes `ScrapeRun` + the first job.
  Returns immediately (or `--wait` to follow progress).
- **Worker** (`scrappy worker`): claims and runs jobs. One process = one SQLite writer (R12).
- For development, `scrappy run gtx-laptops --inline` runs the worker loop in-process.

## Not chosen

- **Celery / Dramatiq / Temporal:** a broker and ops overhead at a scale that a DB-table
  queue handles fine. The `JobQueue` port keeps them available as options later.
- **One big `run()` function:** simplest at first, but it can't resume, can't re-run a
  single stage, and gets rewritten as soon as cron or agents arrive.

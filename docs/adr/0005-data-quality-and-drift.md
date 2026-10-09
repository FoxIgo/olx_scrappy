# ADR 0005 — Data quality and parser drift detection

Status: **proposed**

## Context

Sites change their markup without notice. A broken parser usually still gets HTTP 200
and returns records with **missing fields**, not errors. Combined with change history
(R7), that is dangerous: a broken price selector would record "price changed → null"
for every offer and corrupt the history.

## Decision

### 1. Validate every parsed record at the boundary

Each recipe's mapper produces a `ScrapedListing` validated by a schema (pydantic in
infrastructure). Required fields per phase:

| Phase | Required | Optional |
| --- | --- | --- |
| Discovery (list page) | external_id, url, title, price | location, thumbnail, dates |
| Enrichment (offer page) | external_id, description, status | params, seller, images |

A record that fails validation is **rejected, logged with the raw page reference, and
counted**. It never reaches the domain.

### 2. Missing ≠ changed

Domain rule for history (R7): a field that is absent in a new observation means
**"unknown"**, not "now empty". Snapshots are written only for fields that were actually
observed with a different value. A parser bug therefore can't produce fake changes.

### 3. Per-run fill-rate metrics

Each `ScrapeRun` records, per phase:
- records seen / accepted / rejected
- fill rate per field (share of non-null values)
- fetch outcomes (OK / BLOCKED / NOT_FOUND / …)

Thresholds per source in config (e.g. `price fill rate < 95%` or `rejected > 5%`). When
a threshold is crossed, the run ends as **`degraded`** and reports which fields dropped.
That points directly at the broken selector.

### 4. Raw page archive makes recovery possible

With raw pages archived (open question 7), a fixed parser can **re-process** a degraded
run's pages without fetching them again. Strongly recommended, at least for degraded runs.

## Consequences

- `ScrapeRun` gets a `degraded` status alongside `completed / failed / partial`.
- Recipe tests must include "page from the real site → expected record" fixtures; when a
  site changes, a new fixture reproduces the break.
- Small cost: computing metrics per run. No external monitoring stack needed; the CLI
  prints the run report.

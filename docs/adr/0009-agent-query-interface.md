# ADR 0009 — Agent query interface (`scrappy q`) and the database skill

Status: **proposed**

## Context

Agents (Claude Code now, other agents later, R2) need to answer questions about the
scraped data: attribute facets, price statistics by attribute, deals, history, and data
quality. If they improvise SQL, they couple to the table layout and SQLite JSON syntax,
get medians and the "latest extraction" logic wrong, and waste tokens on wide result sets.

Decisions from the user (planning round):
- Access path: **app commands first, raw SQL as a read-only fallback.**
- Permissions: **read + safe actions** (actions that already exist as use cases).
- Questions to support: **facets, price stats by attribute, deals, history + data quality.**

## Decision

### 1. A `scrappy q` command group: read-only, JSON-first, made for agents

Every `q` command prints **one JSON document** to stdout (UTF-8, compact by default,
`--pretty` optional). Errors print the same envelope with `ok: false` and exit code 1.

```json
{
  "ok": true,
  "command": "q.facets",
  "params": {"search": "gtx-laptops", "attributes": ["gpu"], "filters": []},
  "count": 12,
  "truncated": false,
  "data": [...],
  "notes": ["17 offers have no extraction yet; they are excluded"]
}
```

`notes` exists so commands can tell the agent about caveats (excluded rows, small
samples, stale data) instead of the agent drawing wrong conclusions silently.

Common options (wherever they make sense):
- `--search NAME` (scope to a saved search), `--category NAME`
- `--relevant/--all` (default `--relevant`: junk excluded, ADR 0007)
- `--status active` (default `active`), `--where EXPR` (repeatable; same syntax as
  `offers list`: `= != < <= > >= ~`, over attributes and the pseudo-fields `price`,
  `title`, `location`)
- `--limit N` (always bounded, with a default), `--fields a,b,c` (projection for list
  outputs)

### 2. Commands

| Command | Answers | Output `data` |
| --- | --- | --- |
| `q overview` | "What's in the DB?" Entry point for agents | searches (name, category, offer counts total/relevant/extracted, last run status + time), categories, totals |
| `q schema [--category NAME] [--tables]` | "Which attributes and fields exist?" | category attribute specs (name, type, unit, enum values, description) read from the live catalog; with `--tables`: tables + columns reflected from the DB (for the SQL fallback) |
| `q offers` | filtered list of offers | rows with id, title, price, location, url, status, first/last seen, selected attributes (`--fields`) |
| `q offer ID [ID...]` | full detail for specific offers | offer + latest extraction (attributes, provenance) + snapshots + searches it belongs to |
| `q facets --attr A [--attr B]` | "Which values exist, how often?" | per attribute: value → count (+ `null` count). Numbers: also min/max/buckets |
| `q stats --by A [--by B] [--metric price]` | price by attribute group | per group: n, min, p25, median, p75, max, mean (Decimal as strings) |
| `q deals [--compare-by A,B] [--min-group N] [--max-ratio R]` | underpriced offers | offer + group key + group median + ratio + group size + reason text |
| `q history [--offer ID] [--since DATE] [--field price]` | changes over time | snapshots (offer, field, old → new, at), new offers since date |
| `q health [--search NAME] [--runs N]` | data quality | recent runs (status, metrics, warnings), extraction coverage (pending/failed/done), per-attribute null rates, stale offers |
| `q sql "SELECT ..."` | anything else (fallback) | rows; **read-only connection**, single `SELECT`/`WITH` statement, enforced row limit and timeout |

### 3. Where the logic lives (hexagonal)

- **Domain** (pure, unit-tested):
  - `deals`: comparable-group key from chosen attributes, group median, ratio,
    min group size, explanation text. Groups too small produce no deal.
  - Numeric stats helpers (percentiles over Decimals).
- **Application**: an `AnalyticsQueries` read-side port plus `q` use cases. These
  resolve the latest extraction per offer, relevance, and filters, and add the `notes`.
- **Infrastructure**: SQL adapter. SQL handles filtering by search/status/relevance and
  JSON attribute extraction (dialect-specific: `json_extract` on SQLite, `->>` on
  Postgres, isolated in the adapter). Percentiles are computed in Python over the
  filtered rows; that's fine at medium volume (R13) and dialect-independent.
  `q sql` uses a separate **read-only** connection (`mode=ro` for SQLite; a
  `READ ONLY` transaction for Postgres).
- **Presentation**: Typer `q` group, JSON envelope rendering.

### 4. Safe actions stay on existing commands

`search add`, `run`, `resume`, `offers relevance`, `extract requeue` already exist as use
cases. The skill documents them as the only allowed writes. There's no write access
through `q` and none through `q sql`.

### 5. The skill

A project skill (`.claude/skills/<name>/`) that teaches the protocol:

1. Orient: `q overview`, then `q schema` for the category in question.
2. Choose the narrowest command for the question (decision table).
3. Read `notes` and sample sizes before concluding anything.
4. Use `q sql` only when no command fits, after `q schema --tables`.
5. Actions only via the safe-action commands, with the user's request behind them.

A bundled wrapper script locates the server package and runs `uv run scrappy q ...`,
so agents don't need to know paths. The skill contains no table names, counts, or
paths: everything is discovered live through `overview` / `schema`.

## Consequences

- Agents get correct medians, latest-extraction semantics, and relevance handling for free.
- The same port can later back an HTTP API for the frontend and an MCP tool server (R2).
- New questions become new `q` commands; `q sql` usage in practice shows which ones are
  missing.

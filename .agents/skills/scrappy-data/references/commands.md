# Command Reference (`scrappy q`)

All commands output a single JSON envelope on stdout:

```json
{
  "ok": true,
  "command": "q.<name>",
  "params": {...},
  "count": <n>,
  "truncated": <bool>,
  "data": [...],
  "notes": ["..."]
}
```

On failure: `"ok": false` with `"error": {"type": ..., "message": ...}` and exit code 1.

All commands support `--pretty` to indent JSON output.

---

## 1. `overview`
Provides high-level database state: saved searches, total offer counts, last runs, categories, and database engine dialect.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py overview [--pretty]
  ```
- **Key Output Fields in `data`:**
  - `database`: Engine dialect (e.g., `sqlite`, `postgresql`).
  - `searches`: Array of saved searches, each with name, category, offer count, relevant count, extracted count, last run status and timestamp.

---

## 2. `schema`
Inspects category attribute specifications from the live catalog, and optionally lists raw DB tables and columns.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py schema [--category <name>] [--tables] [--pretty]
  ```
- **Options:**
  - `--category <name>`: Filter attributes to a specific category.
  - `--tables`: Also list database tables and column definitions (useful for `q sql`).
- **Key Output Fields in `data`:**
  - `categories`: Map of category names to their defined attributes, data types, units, and enum options.
  - `tables`: (When `--tables` is provided) Map of table names to columns and types.

---

## 3. `offers`
Returns a filtered list of offers matching specific criteria.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py offers [options]
  ```
- **Options:**
  - `--search <name>`: Scope to a saved search.
  - `--category <name>`: Filter by category of latest extraction.
  - `--relevant / --all`: Default `--relevant` (hides junk). Use `--all` to include irrelevant/unclassified offers.
  - `--status <status>`: Filter by status (`active`, `removed`, `sold`, or `any`). Repeatable. Default is `active`.
  - `-w, --where <filter>`: Filter condition (repeatable), e.g. `--where "ram_gb>=16"` or `--where "price<2000"`.
  - `-n, --limit <int>`: Max offers to return (default: `50`).
  - `--fields <csv>`: Comma-separated list of fields or attribute names to return (e.g. `--fields title,price,location,gpu,ram_gb`).
  - `--sort <sort>`: Sort order: `seen` (default), `price`, or `price-desc`.
- **Key Output Fields in `data`:**
  - Array of offer summaries matching the requested fields and filters.

---

## 4. `offer`
Retrieves full details for one or more specific offers, including full extraction history, snapshots, and search associations.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py offer <source:external_id> [<source:external_id>...] [--pretty]
  ```
- **Arguments:**
  - `<source:external_id>`: One or more composite IDs (e.g., `olx_pl:123456789`).
- **Key Output Fields in `data`:**
  - Detailed object for each offer: raw snapshots, all extraction iterations, relevance overrides, and price history.

---

## 5. `facets`
Counts the frequency of distinct values for attributes. For numeric attributes, computes buckets/ranges.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py facets --attr <attr_name> [options]
  ```
- **Options:**
  - `--attr <attr_name>`: Attribute to facet (repeatable, required).
  - `--search <name>`, `--category <name>`, `--relevant / --all`, `--status <status>`, `--where <filter>`.
- **Key Output Fields in `data`:**
  - Value counts, null count, and distributions per requested attribute.

---

## 6. `stats`
Calculates aggregated price statistics (`n`, `min`, `p25`, `median`, `p75`, `max`, `mean`) grouped by one or more attributes.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py stats --by <attr_name> [options]
  ```
- **Options:**
  - `--by <attr_name>`: Group by this attribute (repeatable). E.g. `--by gpu --by ram_gb`.
  - `--metric <name>`: Metric to calculate (currently only `price`).
  - `--search <name>`, `--category <name>`, `--relevant / --all`, `--status <status>`, `--where <filter>`.
  - `-n, --limit <int>`: Maximum groups returned (default: `100`).
- **Key Output Fields in `data`:**
  - Groups with respective quartile breakdown and sample count `n`.

---

## 7. `deals`
Finds offers priced significantly below the median of comparable offers.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py deals --compare-by <attr1,attr2> [options]
  ```
- **Options:**
  - `--compare-by <csv>`: Comma-separated list of attributes defining comparable items (e.g. `--compare-by gpu,ram_gb`).
  - `--min-group <int>`: Minimum group size required to consider an offer (default: `2`).
  - `--max-ratio <decimal>`: Price / group median ratio threshold (default: `0.85`). Offers with ratio <= this are returned.
  - `-n, --limit <int>`: Max deals returned (default: `20`).
  - `--search <name>`, `--category <name>`, `--relevant / --all`, `--status <status>`, `--where <filter>`.
- **Key Output Fields in `data`:**
  - Ranked list of underpriced offers including `ratio`, group `median`, `group_size`, `price`, `title`, and `url`.

---

## 8. `history`
Tracks attribute changes over time (price drops, title updates, status changes) and new listings since a given date.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py history [options]
  ```
- **Options:**
  - `--offer <id>`: Scope changes to a single offer ID (`source:id`).
  - `--since <date>`: ISO-8601 date or string (`YYYY-MM-DD`).
  - `--field <field_name>`: Scope to changes of a specific field (e.g. `price`, `status`).
  - `-n, --limit <int>`: Max history records (default: `100`).
  - `--search <name>`, `--category <name>`, `--relevant / --all`, `--status <status>`, `--where <filter>`.
- **Key Output Fields in `data`:**
  - Array of change events with `field`, `old_value`, `new_value`, `changed_at`, and offer metadata.

---

## 9. `health`
Reports database health, extraction completeness, scraper status, and null rates.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py health [--search <name>] [--runs <int>] [--pretty]
  ```
- **Options:**
  - `--search <name>`: Scope health check to a specific saved search.
  - `--runs <int>`: Number of recent scraping runs to inspect (default: `5`).
- **Key Output Fields in `data`:**
  - `runs`: Status (`ok`, `degraded`, `failed`), offers scraped, fill rates, warnings.
  - `extractions`: Counts for `done`, `pending`, `failed`.
  - `null_rates`: Map of attributes to their percentage of unpopulated values.

---

## 10. `sql`
Fallback read-only SQL query execution. Used when built-in `q` commands cannot answer the query.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py sql "<SELECT ...>" [--limit <int>] [--pretty]
  ```
- **Options:**
  - `<query>`: Argument containing a single `SELECT` or `WITH ... SELECT` query.
  - `--limit <int>`: Row limit enforcement (default: `100`).
- **Notes:**
  - Connection is strictly read-only.
  - Always check `q schema --tables` before writing raw queries.

---

## 11. `export`
Exports a flat table of offers (one row per offer, with `attr_*` columns) for analysis with pandas or DuckDB.

- **Usage:**
  ```bash
  python <skill-dir>/scripts/q.py export [--format csv|jsonl] [--out <path>] [options]
  ```
- **Options:**
  - `--format <fmt>`: `csv` (default) or `jsonl`.
  - `--out <path>`: File path to save output. If omitted, streams raw text directly to stdout.
  - `--search <name>`, `--category <name>`, `--relevant / --all`, `--status <status>`, `--where <filter>`.
- **Usage with `frame.py`:**
  ```bash
  python <skill-dir>/scripts/q.py export --search <search> --out scratch/offers.csv
  uv run --with pandas python <skill-dir>/scripts/frame.py scratch/offers.csv "<pandas_expr>"
  ```

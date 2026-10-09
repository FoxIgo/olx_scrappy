---
name: scrappy-data
description: Query and act on the scrappy marketplace database (scraped offers, LLM-extracted attributes, saved searches, runs) through the purpose-built `scrappy q` JSON commands instead of improvised SQL. Use this whenever the user asks anything about scraped offers or listings: what was found, cheapest or best deals, prices by GPU/RAM/CPU/condition or any other attribute, which values exist, price changes, new offers since a run, run or extraction health, missing or failed extractions. Also use it before writing any SELECT against the scrappy database, and when the user wants to add a search, start or resume a run, mark an offer relevant or irrelevant, or re-extract attributes.
---

# Working with the scrappy database

The database holds marketplace offers scraped by saved searches, the LLM-extracted
attributes of each offer (typed per category, e.g. a laptop's GPU and RAM), change
history, and run/job bookkeeping. The `scrappy q` commands answer the common questions
correctly and compactly. Improvised SQL usually gets the subtle parts wrong:

- **Latest extraction:** an offer can have several extractions (re-extracted with a new
  model or schema). Only the latest one counts.
- **Relevance:** offers the LLM classified as junk for a search (chargers, cases…) are
  hidden by default, and a user's manual override beats the LLM.
- **Price kinds:** only fixed prices have an amount. Exchange/free offers must not enter
  price statistics.
- **JSON attributes:** attribute storage and JSON syntax differ per database engine.
  The commands hide this.

So use the commands first, and raw SQL only as a fallback (see below).

## Running commands

Use the bundled wrapper. It finds the project and runs the CLI through `uv`, from any
working directory:

```bash
python .agents/skills/scrappy-data/scripts/q.py <subcommand> [options]
python .agents/skills/scrappy-data/scripts/q.py --data-dir <dir> <subcommand> ...   # another database
python .agents/skills/scrappy-data/scripts/q.py --cmd <command> [options]           # safe actions (below)
```

`<skill-dir>` refers to `.agents/skills/scrappy-data`. Every `q` command prints one JSON document:

```json
{"ok": true, "command": "q.<name>", "params": {...}, "count": <n>, "truncated": <bool>,
 "data": [...], "notes": ["..."]}
```

On failure: `"ok": false` with `"error": {"type": ..., "message": ...}` and exit code 1.
For the options and output fields of each command, read `references/commands.md`.

## Protocol

1. **Orient first.** Run `q overview`. It lists the saved searches, their categories,
   how many offers are relevant/extracted, and the last run. Never assume search or
   category names; take them from here.
2. **Learn the attributes** for the category in question: `q schema --category <name>`.
   Attribute names, types, units and enum values come from the live catalog. Use those
   exact names in `--attr`, `--by`, `--where` and `--compare-by`.
3. **Pick the narrowest command** for the question:

   | Question shape | Command |
   | --- | --- |
   | "what values/options exist", "how many have X" | `q facets --attr <a>` |
   | "how much does X cost", "is 16GB worth it", price by group | `q stats --by <a> [--by <b>]` |
   | "good deals", "underpriced", "what should I buy" | `q deals --compare-by <a>,<b>` |
   | "show me offers with …" | `q offers --where ... --fields ...` |
   | one or a few specific offers | `q offer <source:id> ...` |
   | "what changed", "price drops", "new since…" | `q history ...` |
   | "is the data OK", failed runs, missing extractions | `q health` |
   | correlations, derived metrics, crosstabs, multi-step analysis | `q export` + pandas (`scripts/frame.py`) |
   | none of the above | `q sql` (fallback, below) |

   `references/recipes.md` has worked chains for multi-step questions (e.g. find
   deals → inspect the top ones → check their price history).
4. **Keep outputs small.** Use `--fields` and `--limit` on list commands, and filter in
   the command (`--where`, `--search`, `--status`) rather than fetching everything and
   filtering mentally. When `truncated` is true, the answer is incomplete; narrow the
   query or raise `--limit` deliberately.
5. **Read `notes` and sample sizes before concluding anything.** Notes report excluded
   rows (unextracted offers, non-fixed prices, groups below the minimum size, mixed
   currencies). A median over 3 offers is an anecdote; say so. If many offers are
   unextracted, attribute-based answers cover only part of the data: tell the user and
   point to the extraction state in `q health`.
6. **Answer with evidence.** Quote the numbers you used (n, median, ratio), name the
   filters, and link offers by URL when recommending them.

## Filters

`--where` is repeatable (all conditions must hold). It works on attributes and the
pseudo-fields `price`, `title`, `location`:

```
--where "ram_gb>=16"   --where "gpu=GTX 1650"   --where "title~gaming"   --where "price<1000"
```

Operators: `= != < <= > >=` and `~` (case-insensitive contains). Default scope is
relevant, active offers. Use `--all` to include junk/other-category offers, and
`--status <s>` for removed or sold ones.

## Raw SQL fallback

Use `q sql "<SELECT ...>"` only when no command fits. Before writing it, run
`q schema --tables` to see the live tables and columns. Don't rely on memory: the schema
evolves. The connection is read-only, accepts a single `SELECT`/`WITH` statement and
enforces a row limit. Read `references/sql-fallback.md` first: it covers the
latest-extraction rule, relevance, price kinds and JSON access, which every correct
query has to reproduce. If you need the same SQL twice, suggest adding a `q` command.

## Actions (writes)

Writes go only through the application's own commands, never through SQL, and only when
the user asked for the change. The allowed actions are adding a search, starting or
resuming a run, overriding relevance, and requeueing extractions. Commands, effects and
caveats are in `references/actions.md`. Before you act, state what will change. Scraping
runs make real requests to the marketplace and extraction calls a paid LLM, so confirm
before starting either unless the user explicitly asked for it.

# ADR 0011 — Components, benchmarks and configurable deal scoring

Status: **proposed** (design round in progress, open questions at the end).

## Context

The main goal is **ranking deals by price per performance**. Price history is not a goal.

Today an offer's extraction is a JSON of free-text attributes (ADR 0007). The CPU and GPU
appear in many spellings ("RTX 3050 Ti", "rtx3050ti 4GB", "GeForce RTX 3050 Ti Laptop"),
so they can't be compared, and there's no performance number to rank by.

User principle (2026-10-09): **separate facts from interpretation.**
- *Facts* are strict and not vague: RAM in GB, VRAM, a component's benchmark score, price.
- *Interpretation* is what matters right now and for whom: gaming, work, battery life.
  It changes with strategy and purpose, so it must never be hardcoded. It is a formula
  with multipliers, defined in config.

## Decision

### 1. Three layers

```
 FACTS (stored)                         INTERPRETATION (config, computed at query time)
 ─────────────────────────────────      ─────────────────────────────────────────────
 offers            price, …             config/scoring.yaml
 extractions       ram_gb, screen_in,   strategies:
                   condition, raw cpu/    gaming:  weights, filters, transforms
                   gpu text, …            work:    …
 component links   offer → cpu/gpu id     battery: …
 components        canonical CPU/GPU
 benchmarks        component → score    score(offer, strategy) → value, coverage
```

- Only facts are persisted. Scores are **computed when queried**, so changing a weight
  needs no re-extraction, re-resolution or migration.
- A strategy never writes facts. A fact never depends on a strategy.

### 2. Components: CPU and GPU only

RAM, storage, storage type, screen size and condition stay scalar or enum attributes in
the extraction JSON. A lookup table would add nothing to them.

- `components`: id, kind (`cpu` | `gpu`), canonical name, slug, vendor, family,
  generation, segment (`mobile` | `desktop` | `integrated`).
- `component_aliases`: normalized alias text → component id (seeded from benchmark
  names, then grown from resolved offers).
- `component_benchmarks`: component id, source, metric, score, sample count, fetched_at.

### 3. Resolution: a separate reconciling stage

This is another reconciler in the ADR 0010 style. The backlog is the set of extractions
whose raw CPU/GPU text has no up-to-date link.

- `offer_components`: offer id, kind, component id (nullable), confidence, method
  (`exact` | `alias` | `fuzzy` | `llm` | `unresolved`), resolver version.
- Matching order: normalize, then exact slug, then alias, then fuzzy. An LLM is used only
  for leftovers. It picks from a **short candidate list** and never invents IDs.
- Partial text ("i7", "GTX") stays `unresolved`. It is not guessed.
- Bumping the resolver version re-resolves without re-extracting.

Implementation notes (slice 3, done):

- **Storage.** `offer_components` (migration 0004), primary key `(offer, kind)`:
  `component_id` (null when unresolved), `raw_text` (what was resolved), `confidence`
  0..1, `method`, `resolver_version`, `resolved_at`. Unresolved texts get a row too, so the
  backlog shrinks and `components status` can list them.
- **Backlog = a query** over the *current* extraction of each offer (any category with a
  `cpu`/`gpu` attribute): non-blank raw text and no link, or a link with a different
  `raw_text`, or one with an older `resolver_version`. `RESOLVER_VERSION`
  (`domain/component/resolution.py`) is bumped when the rules change. `ResolveComponents`
  works in chunks, one transaction each.
- **Matcher** (`ComponentMatcher`, pure). Order: (1) manual alias that points at a part
  other than the text's own slug (a human decision wins; seeded aliases only repeat the
  slug match), (2) text without a model number is unresolved ("i7", "GTX", "Intel",
  "integrated", "Iris Xe", "brak"), (3) exact slug, (4) fuzzy, always with the same model
  number, (5) unresolved. Method `llm` exists in the enum and in the
  `ComponentLlmFallback` port (candidate list in, id out) but nothing calls it yet.
  **Follow-up:** an LLM pass over the leftover texts, picking from a short candidate list
  (same-model-number components), never inventing ids.
- **Laptop variant.** Extractions say "RTX 4060" (the prompt strips "Laptop GPU") but a
  laptop has the mobile part, so for laptop offers (`MOBILE_CATEGORIES`) the variant order
  is `-laptop`, then the plain slug, then `-maxq`/`-laptop-maxq`; other categories prefer the
  plain slug. A text that already says Laptop/Max-Q is taken literally. Chosen variants
  score confidence 0.95, literal matches 1.0. Max-Q is a lower-power variant, so it is
  chosen only when the text says so (resolver v2); for names with no `-laptop` row
  (GTX 1650) the plain row wins, whose Blender score mixes desktop and laptop runs.
  CPUs: a laptop offer whose number matches a desktop part (`i7-12700`) is moved to its
  only mobile sibling (`i7-12700H`), fuzzy 0.8.
- **Memory size variants** (`rtx-3050-6gb-laptop` vs `rtx-3050-laptop`): the extraction's
  `vram_gb` selects the sized row when it exists, otherwise the plain one. "6GB" in the
  text itself wins over `vram_gb`.
- **Fuzzy rules** (all keep the model number, never cross Ti/Super/XT, ambiguous ties stay
  unresolved): Blender's "w/ Radeon 780M" tail is ignored (`Ryzen 7 7840HS`); Intel `HF`
  matches `H`; a bare NVIDIA number (`1660ti`, `3060`) matches when one family has it; a
  close slug (difflib ratio >= 0.8, unique by a 0.1 margin) with the same model token.
  Text cleanup: `4 GB` -> `4GB`, `6/12` core counts and clock speeds are dropped.
- **Human loop.** `scrappy components status` lists the most frequent unresolved texts;
  `scrappy components alias add <cpu|gpu> "<raw text>" <component-id>` stores the alias
  and marks the links of that text stale, so the next `components resolve` redoes exactly
  those offers.

### 4. Benchmark source: Blender Open Data

| Source | Verdict |
|---|---|
| Blender Open Data | **Chosen.** Open data, daily snapshot (`opendata-latest.zip`, ~100 MB), CPU and GPU, laptop GPUs listed separately |
| Geekbench Browser | Its JSON feeds sit behind a Cloudflare bot challenge (HTTP 403). We don't bypass bot protection |
| PassMark | Its terms forbid scraping and redistribution |
| UL 3DMark API | Commercial licence |

Known limits:
- Blender measures **rendering, not gaming**.
- NVIDIA (OptiX/CUDA), AMD (HIP) and Intel (oneAPI) use different backends, so
  cross-vendor GPU scores are skewed.
- Older integrated GPUs may be missing.

A benchmark is just a `(source, metric)` row, so another source can be added later
without schema changes.

#### Snapshot format and aggregation (implemented, slice 2)

`opendata-latest.zip` holds one `.jsonl` (about 1.9 GB unpacked, 432k lines, CC0). Each line
is one submission: `data` is a list of per-scene results with `blender_version.label`,
`device_info.device_type` (`CPU`, `OPTIX`, `CUDA`, `HIP`, `ONEAPI`, `METAL`, `OPENCL`),
`device_info.compute_devices[].name`, `scene.label` and `stats.samples_per_minute`. Lines of
`schema_version` v1/v2 have another shape and no `samples_per_minute`; they are ignored.
The adapter streams the zip line by line and never unpacks it.

- **Pinned version:** Blender **4.5.0** (an LTS with the most submissions: about 136k scene
  results, 1726 device names). Scores of different versions are not comparable, and newer
  versions have less data per device. Hardware missing in 4.5.0 is missing from the
  catalogue; the pin is a constructor argument.
- **Run score:** the **sum** of `samples_per_minute` over the three standard scenes
  (`monster`, `junkshop`, `classroom`) of one device in one submission. Incomplete runs and
  multi-GPU runs are dropped.
- **Device score:** the **median** of its run scores (robust to throttled laptops and
  outliers); `samples` is the number of runs. Devices with fewer than 3 runs are dropped.
- **Metric:** `source = blender_open_data`, `metric = samples_per_minute` for both CPU and GPU.
  The kind of the component says which hardware it measures.
- **GPU backends:** a GPU seen through several backends keeps one, in the order OptiX, HIP,
  oneAPI, Metal, CUDA (backends are never mixed in one median).
- **Result for the 2026-10-09 snapshot:** 942 components (653 CPU, 289 GPU).

#### Naming notes

- Laptop GPUs carry the marker in the name (`NVIDIA GeForce RTX 4060 Laptop GPU`,
  `... with Max-Q Design`). Laptop and desktop variants are different components and
  different slugs (`rtx-4060` vs `rtx-4060-laptop`). Older names with no marker
  (`GeForce GTX 1650`) pool desktop and laptop runs under one name; nothing can separate them.
- Mobile CPUs are told apart only by the model suffix (`i5-12450H`, `Ryzen 7 5800H`,
  `i7-1165G7`); there is no "Mobile" word. The vendor strings carry noise that the slug
  drops: `12th Gen`, `Intel(R) Core(TM)`, `@ 2.80GHz`, `with Radeon Graphics`, `4-Core Processor`.
- Generic names without a model (`AMD Radeon Graphics`, `Intel(R) Graphics`) are skipped.
  Intel Iris Xe is therefore not in the catalogue.
- `component_slug(text, kind)` (`scrappy.domain.component.slug`) is the one normalizer,
  reused by slice 3 to match free text from offers. It lower-cases, drops marketing words,
  splits glued GPU names (`rtx3050ti` -> `rtx-3050-ti`), maps `Mobile`/`Notebook` to `laptop`
  and moves `laptop` / `maxq` to the end of the slug. Memory sizes stay (`rtx-3050-6gb-laptop`
  is other silicon than `rtx-3050-laptop`).
- Component id is `<kind>:<slug>`. `segment`, `vendor`, `family` and `generation` are derived
  heuristically from the slug and are `unknown`/`null` when the name does not say. Aliases are
  the lower-cased original device names; re-importing never renames or deletes a component.
- CLI: `scrappy benchmarks import --file PATH|--download`, `scrappy benchmarks list
  [--kind cpu|gpu] [--search TEXT] [--limit N]`.

### 5. Scoring strategies (config) — implemented, slice 4

`config/scoring.yaml` defines named strategies (`gaming`, `work`, `balanced`, `battery`
ship). Each strategy has a `category`, a `description`, `filters` and `terms`.

**Term** = a fact plus `weight` (> 0), `baseline` (> 0), optional `cap` (> 0) and `transform`
(`linear` default, or `log`). A fact is:
- a category attribute: numeric (`ram_gb`, `vram_gb`, `refresh_hz`, `storage_gb`, `screen_in`,
  `battery_wh`, `max_ram_gb`), boolean (`ram_upgradeable`: true = 1, false = 0, and false still
  counts as *known*), or an enum with a `map` that must list every enum value
  (`storage_type: {map: {ssd: 1, hdd: 0.3, emmc: 0.2}}`); free text such as `resolution` is
  rejected at load;
- a part benchmark `<cpu|gpu>.<source>[.<metric>]` read through `offer_components` ->
  `component_benchmarks`, e.g. `gpu.blender_open_data.samples_per_minute`; the alias
  `gpu.blender` is accepted (registry in `domain/scoring/facts.py`, one entry per new source).
`baseline` is optional (default 1) only for booleans and mapped enums.

**Formula**, per offer and term:

```
x      = fact            (boolean -> 1/0, enum -> map value), clamped to 0 <= x <= cap
t      = x / baseline                       (linear)
       = log2(1 + x / baseline)             (log: diminishing returns; t == 1 at x == baseline)
points = weight * t
performance = sum of points over the terms whose fact is known
coverage    = sum of weights of known terms / sum of all weights
value       = performance / price * 1000    (per 1000 PLN, fixed prices only)
```

**Missing facts add 0 points and are NOT renormalised away.** Performance is not divided by
the covered weight, so an offer that hides its GPU cannot look better than one that states
it; `coverage` shows how much of the strategy was actually measured, and `--min-coverage`
(default 0.6) hides the thinly known offers (and the note says how many). A part whose text
is too vague to resolve ("Intel Core i5") is missing, never estimated.

**Filters** are hard requirements in the `q --where` syntax (`ram_gb>=8`,
`condition!=for_parts`, `price>=300`); query `--where` adds to them. A null attribute never
satisfies a filter (same rule as everywhere else), so unstated RAM fails `ram_gb>=8`.

**Validation at load** (`ConfigError` naming strategy and term): unknown attribute or
component source/metric, text attributes, enums without a full `map`, a `map` on a
non-enum, `weight`/`baseline`/`cap` <= 0, missing `baseline`, unknown category, bad filters.

**Query interface** (ADR 0009 envelope): `scrappy q rank --strategy NAME [--search S]
[--where ...]* [--min-coverage 0.6] [--limit 20] [--fields ...]` returns per offer `id`,
`title`, `url`, `price`, `currency`, `performance`, `value`, `coverage` and a `breakdown`
(per term: raw fact, `points`, the linked `part` and `link_confidence` if below 1, or
`"missing"`). Notes count the excluded offers by reason (filters, outside the category or not
extracted, no fixed price, below coverage). `q strategies` lists the strategies and terms;
`q components [--kind] [--search] [--linked] [--limit]` lists parts with benchmark scores and
how many offers link to each. Facts for all candidate offers come from one chunked query
(`ScoringQueries.component_facts`), no N+1.

**Shipped baselines** (Blender 4.5.0 sum of 3 scenes, samples/min): GPU 2100 = RTX 3060
Laptop (2136; RTX 3050 Laptop 1144, RTX 4060 Laptop 3276, GTX 1650 424); CPU 110 = i5-12450H
(i7-12700H 175, Ryzen 7 5800H 153, i5-1135G7 47). RAM 16 GB (cap 32, log), storage 512 GB,
screen 15.6 in, refresh 144 Hz, VRAM 6 GB, battery 50 Wh. The `battery` strategy uses only
the stated `battery_wh` (there is no "CPU efficiency" fact), so it ranks only offers that
state it.

### 6. Decisions from the design round (2026-10-10)

- **Facts are stored as measured** (a GPU score of 1800 stays 1800). Scaling exists only
  inside a strategy's formula. Each term has a `baseline`, meaning "what counts as solid"
  for this purpose. It is interpretation, so it lives in the strategy, never with the facts.
  Example: `gpu.blender: {weight: 0.6, baseline: 1500}` and
  `ram_gb: {weight: 0.4, baseline: 16, cap: 32}`.
- **Missing facts:** the offer is still ranked from the known terms, and `coverage` shows
  the share of weighted terms that had facts. Queries can filter with `--min-coverage`.
- **New laptop facts** (laptop schema version 2, then re-extraction on the free chain):
  - `vram_gb`
  - `refresh_hz` and `resolution` (this also stops "144hz" leaking into `screen_in`)
  - `battery_wh` and a battery-health note
  - `ram_upgradeable` and `max_ram_gb`

- **Transforms:** `baseline` (ratio), `cap`, and `log` for diminishing returns
  ("32 GB isn't twice as good as 16 GB").
- **Filters:** a strategy may define hard requirements, and a query may add more
  (`--where ram_gb>=16`). Both apply.

- **Vague part text is missing information** (user, 2026-10-10). "Intel Core i5", "Ryzen 5",
  "i7 11th gen" are not estimated from a family median, in facts or in strategies. The term
  counts as missing and lowers `coverage`.

## Implementation slices

Slice 1 is done (laptop schema v2 in `config/categories.yaml`; a real category with every
attribute null is an invalid extraction, in both the adapter and the domain; persistent
5xx and timeouts are `UNAVAILABLE`, so they cost the offer no attempt).

1. Extraction schema v2 (new facts plus prompt fixes), reject all-null laptop
   extractions, and make 5xx errors cost no attempt.
2. Component, alias and benchmark tables, plus the Blender Open Data import.
3. Resolution reconciler (offer → CPU/GPU).
4. `config/scoring.yaml` strategies plus a `q rank --strategy` query (done, see section 5).

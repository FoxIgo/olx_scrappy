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

### 5. Scoring strategies (config)

`config/scoring.yaml` defines named strategies. Each strategy has:
- **terms**: a fact (`cpu.blender`, `gpu.blender`, `ram_gb`, `vram_gb`, …), a transform
  (`ratio_to_reference`, `log`, `cap`, …) and a weight;
- **filters**: hard requirements, e.g. `ram_gb >= 16` or `condition != for_parts`;
- **missing-fact policy** (open question 2).

The result is `performance` and `value = performance / price`, plus `coverage`: the share
of weighted terms that had facts. Ranking is exposed through the query interface
(ADR 0009) with `--strategy <name>`.

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

## Implementation slices

Slice 1 is done (laptop schema v2 in `config/categories.yaml`; a real category with every
attribute null is an invalid extraction, in both the adapter and the domain; persistent
5xx and timeouts are `UNAVAILABLE`, so they cost the offer no attempt).

1. Extraction schema v2 (new facts plus prompt fixes), reject all-null laptop
   extractions, and make 5xx errors cost no attempt.
2. Component, alias and benchmark tables, plus the Blender Open Data import.
3. Resolution reconciler (offer → CPU/GPU).
4. `config/scoring.yaml` strategies plus a `rank --strategy` query.

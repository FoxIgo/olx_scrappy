# ADR 0012 — Tiered extraction: rules first, LLM for promising and uncertain offers

Status: **accepted** (decided with the user 2026-10-10; implemented the same day, see
"Implementation notes"). Motivation confirmed by the user: **speed**.

## Context

ADR 0007 sends every offer to an LLM. The input is already deterministic (title, cleaned
description, OLX params, price; `application/extraction/prepare.py`). LLM extraction for
all offers is slow, quota-bound on free tiers and costs money on paid ones, while much of
what we need is written in a regular form.

Findings from the 999 stored olx_pl laptop offers (2026-10-10):

| OLX param | Coverage | Use |
|---|---|---|
| `state` (Używane / Uszkodzone / Nowe / Odnowione / Powystawowe) | 100% | maps to `condition` |
| `harddisktype_laptops` (SSD / HDD / HDD + SSD / eMMC / Brak) | 70% | maps to `storage_type` (`Brak` → `storage_missing`) |
| `graphicscardtype_laptops` (Zintegrowana / Dedykowana) | 41% | dedicated-GPU hint for uncertainty checks |
| `ramsize`, `disksize`, `screendiagonal` | 68-87% | **ranges** only ("6GB - 12GB"): a sanity bound for parsed values, never the fact |
| `processorseries_laptops` | 70% | family only ("Intel Core i5"): too coarse for benchmarks |

Titles are often spec lists (`L490 / i5-8265U / 8GB-DDR4 / SSD-256GB NVME / FHD-IPS`), and
the component catalogue (ADR 0011, 942 CPUs/GPUs with aliases) already resolves CPU/GPU text.

## Decision

### 1. Three tiers

```
Tier 0  RULES        every offer, free, instant       → extraction (method: rules)
Tier 1  PROVISIONAL  score from rule facts (scoring.yaml strategies, ADR 0011)
Tier 2  LLM          top-N promising + uncertain only  → extraction (method: llm), supersedes
```

### 2. Rule extractor (Tier 0)

A new `AttributeExtractor` adapter (`RuleBasedAttributeExtractor`, version `rules-v1`),
pure and deterministic, over the same `ExtractionInput` the LLM gets:

- **Params mapping**: `state` → `condition`, `harddisktype` → `storage_type`, etc. The
  mapping tables live in source-recipe config (they are olx_pl-specific), not in the
  extractor.
- **Regex** over title + description: `ram_gb`, `storage_gb` (with the `8/256` shorthand),
  `screen_in` (never Hz), `refresh_hz`, `resolution` (FHD/QHD/4K aliases), `vram_gb`.
  Parsed values that fall outside the matching OLX param range are dropped as conflicts.
- **CPU/GPU**: scan the text with the component catalogue (slugs + aliases) and write the
  matched text into `cpu`/`gpu`. The existing resolver (ADR 0011) then links it as usual.
- **Damage / condition**: Polish keyword lists with stem regexes (`pękn\w* matryc\w*`,
  `na części`, `zalan\w*`, `nie włącza`, `brak (dysku|zasilacza|ramu?)`) map to `damage`
  values. No NLP library: spaCy adds a dependency and does not help with spec tokens;
  stem regexes cover Polish inflection well enough here.
- **Junk (conservative)**: classify as `other` only on clear signals: the title names a
  part or accessory as the item sold (`zasilacz`, `matryca`, `klawiatura`, `bateria do`,
  `torba`) without laptop words, or the price is below a configured floor. Anything
  unclear stays `laptop` with low confidence.
- Each field gets a confidence; the extraction records which fields came from params,
  regex or catalogue.

### 3. LLM gate (Tier 2)

An offer goes to the LLM backlog when **either**:

- **Promising**: in the top-N of any scoring strategy by provisional score (N configurable,
  per strategy), **or**
- **Uncertain**: the rule pass could not be trusted, e.g.
  - a rule value conflicts with an OLX param range,
  - damage/condition words were found but no damage type was matched,
  - `graphicscardtype = Dedykowana` but no GPU was found,
  - no CPU found, or the junk check was borderline,
  - the description is long and the rules matched little.

Uncertainty reasons are stored so `q health` can show why offers were sent to the LLM.
Manual `re-extract` keeps working for any offer.

### 4. Merge: the LLM supersedes

Rule and LLM results are both `OfferExtraction` rows. The current extraction is the LLM
one when it exists for the current `content_hash`, otherwise the rules one. No per-field
merge and no rule hints in the prompt (to avoid anchoring on wrong rules). Provenance gets
`method: rules | llm`; `model` is `rules-v1` for the rule adapter.

Bumping the rules version reruns Tier 0 from stored data only (no scraping, no LLM).

## Consequences

- Every offer gets usable facts and a provisional rank immediately after enrichment.
- LLM calls drop to roughly top-N per strategy plus the uncertain share; quota stops
  being the bottleneck.
- Rule quality is measurable: offers with both extractions give a per-field agreement
  rate (rules vs LLM), the way to grow the rules and tune N.
- Junk the rules miss can rank high provisionally; the top-N gate sends exactly those
  offers to the LLM, which then reclassifies them.

## Implementation notes

- **Port** `RuleExtractor` (`application/ports/extractor.py`): sync, pure, returns
  `RuleExtraction(result | None, uncertain reasons)`. Adapter `RuleBasedExtractor`
  (`infrastructure/extraction/rules/`): `hardware.py` (CPU/GPU), `specs.py` (RAM, storage,
  screen, Hz, resolution, battery), `damage.py` (damage lexicon, negation, junk titles),
  `olx_params.py` (exact params, range vetoes with a 10% edge margin because sellers file 128GB
  under "129GB - 256GB"), `extractor.py` (`LaptopRules`, one rule set per category; a new
  category adds a rule set, no rule set = `no_rules` = LLM). Rules version `rules-v1`.
- **Storage.** A rule result is an ordinary `OfferExtraction` (`model = rules`,
  `prompt_version = rules-v1`, `profile = provider = rules`), stored with relevance like an
  LLM answer, so `q` and `q rank` work on it unchanged. It is not stored when an LLM extraction
  of the same content exists (LLM supersedes).
- **State** (migration 0005): `extraction_state.rules_hash`, `rules_version`
  (`rules-v1:<catalog fingerprint>`), `escalation` (comma-separated reasons). The rules
  backlog is "no rule run for this content/version"; a gated LLM backlog is
  `forced OR (escalation set AND rules_hash = content_hash)`.
- **Use case** `TierExtractions`: rule pass in chunks -> component resolution (only once a
  benchmark catalogue exists, otherwise links would all be stored unresolved) -> promotion
  of each strategy's top `top_n` via `q rank` (`ProvisionalTop`). The extractor loop runs it
  before every reconcile tick and promotes again whenever LLM results arrived.
- **Config** `extraction.yaml` `tiering: {enabled, top_n, min_coverage, escalate}`; shipped
  enabled with `top_n: 25`, `min_coverage: 0.5`, all reasons.
- **CLI** `scrappy extract rules [--max N]`: run the pass now, show reasons and the gated
  backlog.
- **Decisions on the open questions:** N counts per strategy over all searches (`q rank`
  default scope); the junk price floor is 80 PLN in code (`JUNK_PRICE_FLOOR`), and below it
  the offer goes to the LLM rather than being classified; patterns stay in code, one rule set
  per category.

### Measured on the stored offers (1115 olx_pl laptop offers, 2026-10-10)

- Rule pass: ~1.3 ms per offer, all 1115 in ~1.5 s (CLI end to end ~10 s incl. ranking).
- 1106 rule extractions (37 `other`: tablets, phones, RAM sticks, chargers); 9 with no result.
- Fill rate: condition 87%, storage type 67%, RAM 51%, storage size 43%, screen 43%,
  CPU model 32% (titles often say only "i5"), resolution 19%, GPU 17%.
- Sent to the LLM: 263 of 1115 (24%): 229 unsure (damage_unclear 93, damaged 64,
  gpu_missing 28, storage_conflict 25, ram_conflict 17, ...) + 34 top deals. Without a
  benchmark catalogue only `work`/`battery` could rank; with benchmarks imported the
  gaming/balanced/repair tops add up to 3 x 25 more.

## Known limits

- A CPU written only as a family ("i5", "Ryzen 5") stays null; the LLM can't do better from
  the same text, so it is not a reason to escalate.
- Unresolved component links made before a later, larger benchmark import are not
  re-resolved by the import (pre-existing ADR 0011 behaviour); bump `RESOLVER_VERSION` or
  re-run resolution if that happens.

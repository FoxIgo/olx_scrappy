# ADR 0007 — LLM attribute extraction and category classification

Status: **proposed**

## Principle: the LLM is a pure function

```
ExtractionInput (prepared text)  ──►  LLM  ──►  ExtractionResult (validated JSON)
```

No tools, no browsing, no clicking, no follow-up requests. Everything the LLM sees was
already scraped and **prepared deterministically** by our code. The LLM only turns messy
text into structured fields. That makes it cheap, testable, replaceable, and safe.

## Flow

1. **Prepare** (application, deterministic): build `ExtractionInput` from the stored offer:
   - title, site params (key/value from the page), description (HTML stripped,
     whitespace normalized, truncated to a max length), price
   - the list of known categories + the attribute schema of each candidate category
2. **Extract** (`AttributeExtractor` port → `OpenRouterAttributeExtractor` adapter):
   one call returns
   - `category`: one of the known categories, or `other`
   - `attributes`: fields from that category's schema (unknown → `null`, never guessed)
   - optional `notes` (e.g. "for parts", "damaged screen")
3. **Validate** (infrastructure → domain): the JSON must match the category schema
   (pydantic model generated from it). Invalid output → retry once → else rejected,
   counted in run metrics (ADR 0005), offer stays `extraction_pending`.
4. **Store** with provenance: `model`, `schema_version`, `prompt_version`, `content_hash`,
   `extracted_at`, token usage.
5. **Derive relevance** on each `search_offer` link: `is_relevant = (offer.category ==
   search.category)`. A manual override is stored separately and always wins.

## Categories and schemas (R11, round 4)

- `Category` is defined by you, e.g. `laptop`:
  ```yaml
  laptop:
    version: 1
    attributes:
      gpu:        {type: string, description: "GPU model, e.g. GTX 1650"}
      cpu:        {type: string}
      ram_gb:     {type: integer}
      storage_gb: {type: integer}
      storage_type: {type: enum, values: [ssd, hdd, emmc]}
      screen_in:  {type: number}
      condition:  {type: enum, values: [new, used, damaged, for_parts]}
  ```
- `SavedSearch.category` says what the search is looking for (`gtx-laptops → laptop`).
- **Classification is per offer, relevance is per search.** An offer is classified
  once (it's a charger), no matter how many searches found it. Each search then decides
  relevance from it. No duplicate LLM calls.
- Junk ("charger", "desktop GTX 1650") → category `other` or a different category →
  `is_relevant = false` for the laptop search → hidden by default, still stored.
- Finer intent ("only GTX 1650, not RTX 3050") is **attribute filtering**
  (`gpu = 'GTX 1650'`), not relevance. Relevance only removes junk.

## When it runs

Configurable trigger (ADR 0006): automatically after enrichment when `content_hash`
changed, or only on demand. Re-extraction after a schema/model change uses stored data
only, with no scraping.

## Cost

No hard cap (decision R14). Still recorded: tokens + estimated cost per offer and per
run, shown in the run report. The content-hash cache means unchanged offers are never
sent again.

## Risks

- **Hallucinated values:** the prompt says "null if not stated"; the schema allows null;
  provenance allows re-extraction later with a better model.
- **Prompt injection via descriptions:** the input is untrusted text, but the LLM has no
  tools, and its output is only data validated against a schema. Worst case is a wrong
  field value, never an action.
- **Model/provider changes:** the provider is behind the port; the model is a config
  value; outputs are versioned.

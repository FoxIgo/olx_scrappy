# Recipes: question → command chain

Each recipe starts after orientation (`q overview`, `q schema --category <c>`).
Replace `<search>`, `<category>` and `<attr>` with names taken from those outputs.

## "What's the best deal?" / "What should I buy?"

1. Choose comparison attributes that drive the price for this category. Check
   `q schema` descriptions and pick 1–3 (for a laptop, typically GPU + RAM, sometimes
   condition). Too many attributes make groups tiny and nothing qualifies.
2. `q deals --search <search> --compare-by <a>,<b> --limit 10`
3. If `data` is empty, read `notes`: groups are probably below `--min-group`. Drop one
   comparison attribute, or lower `--min-group` and say that the comparison is weaker.
4. For the top candidates: `q offer <id> <id> ...` to read descriptions. Look for
   reasons for a low price the attributes don't capture (damage, "for parts", missing
   charger, locked BIOS). Condition may be null when the seller didn't state it.
5. Optional: `q history --offer <id>` to see whether the price dropped recently.
6. Answer with: offer link, price vs group median (ratio), group size, and caveats from
   the description.

## "How much does X cost?" / "Is upgrade A worth it?"

1. `q stats --search <search> --by <attr>` (add a second `--by` for a crosstab-like view)
2. Compare medians, not means: listings have outliers (broken units, typos in price).
3. Report n per group. Treat groups with n < 5 as indicative only.

## "Which options are on the market?"

1. `q facets --search <search> --attr <a> [--attr <b>]`
2. A large `null` count means the attribute is often missing from listings or the
   extraction; say so instead of treating the counts as the whole market.

## "Show me offers matching …"

1. Translate the request into `--where` conditions on attribute names from `q schema`.
2. `q offers --search <search> --where ... --fields title,price,location,url,<attrs> --limit 20`
3. If `truncated`, tell the user how many matched and offer to narrow down.

## "What changed?" / "Any price drops?" / "What's new?"

- Price drops: `q history --search <search> --field price --since <date>`
- New offers: `q offers --search <search> --fields title,price,first_seen_at,url --where ...`
  and compare `first_seen_at` with the last run time from `q overview`, or use
  `q history --since <date>`, which also lists offers first seen in that window.
- Removed/sold: `q offers --search <search> --status removed` (or `sold`)

## "Is the data OK?" / "Why are results missing?"

1. `q health --search <search>`
2. Interpret it:
   - Many unextracted or failed extractions: attribute queries cover only part of the
     offers. Failed extraction jobs mentioning a missing API key need the key, then
     `extract requeue` (see actions.md).
   - Run status `degraded`: the scraper's parser is probably broken for some field; the
     report names the fields whose fill rate dropped.
   - Run warning about truncation: the search hit the site's result cap; suggest
     splitting the search (e.g. by price range).
   - High null rate for an attribute: sellers rarely state it, or the category schema
     description is unclear to the LLM.

## Analysis that no command covers: pandas

For correlations, derived metrics (price per GB), crosstabs, or anything multi-step, export
a flat table and analyse it with pandas instead of writing complex SQL:

```bash
python <skill-dir>/scripts/q.py export --search <search> --out <tmp>/offers.csv
uv run --with pandas python <skill-dir>/scripts/frame.py <tmp>/offers.csv           # profile first
uv run --with pandas python <skill-dir>/scripts/frame.py <tmp>/offers.csv "<expr>"
```

The export already applies the latest extraction and relevance and flattens attributes
into `attr_<name>` columns. `frame.py` adds a numeric `price` column for fixed prices only.
Write exports to a temporary/scratch directory, not into the repository.

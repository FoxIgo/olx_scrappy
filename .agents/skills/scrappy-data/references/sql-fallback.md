# Raw SQL fallback (`q sql`)

Use it only when no `q` command (including `q export` + pandas) answers the question.

## Before writing a query

1. `q schema --tables`: live tables, columns and types. Table and column names are not
   listed in this skill on purpose; the schema evolves, so always read it fresh.
2. Check which database engine is in use (`q overview` reports it). JSON access syntax
   differs: SQLite uses `json_extract(col, '$.key')`, PostgreSQL uses `col ->> 'key'`.

## Rules every correct query must reproduce

The `q` commands apply these automatically. Raw SQL has to apply them by hand:

1. **Latest extraction only.** Offers can have several extraction rows. Pick the newest
   per offer (window function `row_number() over (partition by <offer key> order by
   <extracted timestamp> desc, <sequence> desc) = 1`). Joining all of them duplicates
   offers and mixes old and new attribute values.
2. **Relevance is per search.** It lives on the search↔offer link: a manual override,
   when set, beats the derived value. Use `coalesce(<override>, <derived>)`. Unless the
   user asked for everything, keep only relevant rows.
3. **Price kinds.** Only fixed prices carry an amount. Exclude other kinds from price
   math. Amounts are stored as exact decimal text: cast deliberately, and never compare
   them as strings.
4. **Offer identity** is the pair (source, external id), not the external id alone.
5. **Timestamps** are stored in UTC.

## Constraints of the command

- A single `SELECT` or `WITH … SELECT` statement. Anything else is rejected.
- A read-only connection: writes fail even when they get past validation.
- Results are capped (`--limit`, default shown in the envelope's `params`). Aggregate in
  SQL rather than pulling raw rows.

If a SQL query proves useful twice, propose adding it as a `q` command: that's the
intended way this interface grows.

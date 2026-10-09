# Domain model (draft)

```
 Category ◄────────── SavedSearch ──────┐
 (laptop, schema v1)   name, source,    │ 1
      ▲                url, category    │
      │ classified as                   │ *
      │                          ┌──────┴──────────┐
 OfferExtraction ◄──── Offer ◄───┤  SearchOffer    │  (many-to-many link)
 attributes,         source +    │  first_seen_at  │
 model, versions,    external_id │  last_seen_at   │
 content_hash        current     │  is_relevant    │  (derived from category)
                     state       │  relevance_override (manual, wins)
                       │         └─────────────────┘
                       │ 1..*
                 OfferSnapshot          ScrapeRun ── Jobs (application, ADR 0006)
                 changed fields only    status, phase metrics, fill rates
```

| Concept | Kind | Key points |
| --- | --- | --- |
| `SourceId` | value object | `olx_pl`, `allegro_pl` |
| `OfferId` | value object | `(source, external_id)`. Global identity, the dedup key (R4) |
| `Money` | value object | amount (Decimal) + currency. Never float |
| `Offer` | entity / aggregate root | url, title, price, location, site params, description, image URLs, seller ref, status (`active/removed/sold/unknown`), posted/refreshed dates, `content_hash`, `details_fetched_at` |
| `OfferSnapshot` | entity (child of Offer) | written only when an *observed* field changes; missing ≠ changed (ADR 0005) |
| `SavedSearch` | entity / aggregate root | unique name, source, search URL, target `Category` |
| `SearchOffer` | entity | per-search view of an offer: seen dates, relevance |
| `Category` | entity | user-defined attribute schema, versioned |
| `OfferExtraction` | entity | LLM output + provenance; latest one is current |
| `ScrapeRun` | entity / aggregate root | `running / completed / partial / degraded / failed`, metrics |

## Domain rules (pure functions, unit-tested)

- `needs_details(offer, observed_list_data) -> bool`: R8 re-fetch policy
- `apply_observation(offer, observation) -> list[FieldChange]`: diff + snapshot rules
- `needs_extraction(offer, latest_extraction) -> bool`: content-hash / schema-version check
- `relevance(search, extraction, override) -> bool`
- `run_health(metrics, thresholds) -> RunStatus`: degraded detection

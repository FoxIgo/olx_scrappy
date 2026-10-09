# olx_scrappy — docs

Planning and design notes. Nothing here is implemented yet.

| Doc | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | Big picture: repo layout, server layers, data flow |
| [adr/0001-monorepo.md](adr/0001-monorepo.md) | Why a monorepo, and how small to start |
| [adr/0002-hexagonal-server.md](adr/0002-hexagonal-server.md) | Server layering rules (domain / application / infrastructure / presentation) |
| [adr/0003-language-python.md](adr/0003-language-python.md) | Python for the server (driven by the scraping ecosystem), TS for the future frontend |
| [adr/0004-scraping-sources-and-engines.md](adr/0004-scraping-sources-and-engines.md) | Site recipes (olx_pl, allegro_pl) and fetch engines (httpx, Scrapling…) as two swappable axes |
| [adr/0005-data-quality-and-drift.md](adr/0005-data-quality-and-drift.md) | Record validation, "missing ≠ changed", per-run fill-rate metrics |
| [adr/0006-pipeline-and-jobs.md](adr/0006-pipeline-and-jobs.md) | Discover → Enrich → Extract stages over a durable job queue; worker process |
| [adr/0007-llm-extraction.md](adr/0007-llm-extraction.md) | LLM as a pure function: category + attributes, relevance, provenance |
| [adr/0008-core-model-decisions.md](adr/0008-core-model-decisions.md) | Port shapes, transactions, job dedup keys, metrics aggregation, domain rule details |
| [domain-model.md](domain-model.md) | Entities, value objects, domain rules |
| [requirements.md](requirements.md) | Requirements gathered round by round |
| [research/scraping-tools-evaluation.md](research/scraping-tools-evaluation.md) | Verdicts on scraping tools (Scrapling, Scrapy, Crawlee, Camoufox…) |
| [open-questions.md](open-questions.md) | Decisions still to make |

ADR status values: `proposed` → `accepted` → (`superseded by NNNN`).

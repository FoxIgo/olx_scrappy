# ADR 0003 — Python for the server

Status: **proposed** (replaces the TypeScript assumption in the first draft)

## Context

The first draft assumed TypeScript everywhere. Then the scraping tooling we want became
part of the picture: Scrapling (adaptive selectors, stealth/dynamic fetchers) is
Python-only, as are much of the rest of the scraping ecosystem (Scrapy, curl_cffi,
Camoufox bindings, selectolax, pandas for later analysis).

## Decision

- **Server: Python 3.12+**, managed with `uv`.
- **Frontend (later): TypeScript**, managed with `pnpm`, in the same repo.
- **Contract between them: OpenAPI.** If the HTTP API uses FastAPI, the OpenAPI spec is
  generated from it, and the TS client/types come from that spec (`openapi-typescript`).
  So there's no need for a hand-written `packages/contracts`.

## Why not TypeScript + calling Python tools from a sidecar?

That would add a process boundary and a second language right in the scraping path,
the most fragile part of the system. The business logic is the easy part; scraping is
the hard part, so the server language should be the one with the best scraping tools.

## Python-specific notes for the hexagon

- Ports = `typing.Protocol` (structural typing, no inheritance needed in adapters).
- Domain = `@dataclass(frozen=True)` for value objects; plain classes for entities.
  **No pydantic in the domain.** Pydantic belongs at the edges: raw payload validation
  in infrastructure, request/response models in presentation.
- Layer rules enforced with **`import-linter`** (a "layers" contract) in CI.
- Type checking with `mypy --strict` or `pyright`; it's what keeps ports honest in Python.
- Async throughout (`asyncio`): the fetchers are async-capable, and it allows fetching
  several sources at once.

## Layout note

You asked for `server/src/{domain,application,infrastructure,presentation}`. In Python's
`src` layout, the folders under `src/` are top-level importable packages, and
`import domain` / `import application` are generic names that easily clash. Proposal:

```
packages/server/src/scrappy/{domain,application,infrastructure,presentation}
```

Same four layers, one namespace (`from scrappy.domain.listing import Listing`).

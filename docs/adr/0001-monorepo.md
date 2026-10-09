# ADR 0001 — Monorepo, but start with one package

Status: **proposed**

## Context

The tool is for personal use now. A frontend may come later. The question is whether to
pay for monorepo structure up front.

## Decision

Use a monorepo, but create **only what exists today**:

```
olx_scrappy/
├── docs/
└── packages/
    └── server/          # Python (uv), the only package for now — see ADR 0003
```

When the frontend actually starts:

```
olx_scrappy/
├── docs/
├── package.json             # pnpm workspace root (JS side only)
├── pnpm-workspace.yaml
└── packages/
    ├── server/              # Python, uv — owns its own pyproject.toml
    └── web/                 # TypeScript, pnpm — types generated from server's OpenAPI
```

The repo is polyglot. Each package uses its own native tooling (uv / pnpm); a root
`justfile` or `Makefile` gives one entry point (`just dev`, `just test`).

## Why

- A monorepo folder costs nothing. Moving to one later means moving every file and
  churning git history.
- Empty `web/` or `shared/` packages *now* would be speculative: they rot, and they
  invite dumping "common" code into them before we know what is actually common.

## Critical notes

- **Do not share the domain with the frontend.** What gets shared is the *API contract*.
  With a Python server, that's the OpenAPI spec → generated TS types. Domain entities stay
  inside `server`.
- No Nx/Turborepo. With one Python and one TS package there is nothing to orchestrate.

## Consequences

- The frontend can be added without restructuring anything that exists.
- Two toolchains (uv, pnpm), but each one stays inside its own package.

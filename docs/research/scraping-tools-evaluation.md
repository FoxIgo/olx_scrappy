# Scraping tools: evaluation for this project

Source: a tool landscape report generated with Gemini (shared in planning). This
document records **our verdicts**, not a summary of the report.

> Caveat: the report is AI-generated. Some claims read like marketing (e.g. "autonomously
> bypassing Turnstile") and the benchmarks are unverified. Treat it as a map of the
> landscape and verify any claim with a spike before depending on it.

## What the report confirms in our design

| Report idea | Where it lives in our architecture |
| --- | --- |
| Tiered fallback: HTTP impersonation → patched browser → engine-level spoofing | `FallbackFetcher` decorator over a chain of `PageFetcher` adapters (ADR 0004 §4) |
| Prefer private JSON APIs / embedded hydration state over DOM parsing | Recipe extraction-strategy order (ADR 0004 §6) |
| Silent schema drift: HTTP 200 but empty fields | Data-quality checks per run (ADR 0005) |
| Per-host concurrency, jittered pacing, backoff on 429/503 | `PolitenessPolicy` in fetcher decorators (ADR 0004 §7) |
| Detect challenge pages that come back as 200 | `FetchOutcome` classification (ADR 0004 §8) |

## Tool verdicts

| Tool | Verdict | Why |
| --- | --- | --- |
| **Scrapling** (fetchers + `Selector`) | **Use**, as a library | Python, covers tiers 1–3 behind one API, parser usable without its fetchers. Its `Spider` framework: not used (it would take over control flow). |
| **curl_cffi** | **Use** (directly or via Scrapling) | Tier-1 TLS/HTTP2 impersonation without a browser. Cheapest way to look like a browser. |
| **httpx** | **Use** for official/JSON APIs | Plain, well-typed client for endpoints that don't fingerprint. |
| **Patchright / Camoufox** | **Adapter slot, not now** | Tier 2/3. Only add if a target actually blocks tier 1. Each is one `PageFetcher` file. |
| **Scrapy** | **No** | A framework with its own scheduler, pipelines, and reactor. It would replace our application layer instead of sitting behind a port. Built for volumes we don't have. |
| **Crawlee (Python)** | **No** (for now) | Same reason as Scrapy: it owns the lifecycle. Its ideas (session pool, autoscaling) are worth borrowing if we ever scale. |
| **Crawl4AI / Firecrawl** | **Later, as an extraction adapter** | Useful for the future "attribute extraction" slot and agent tooling (LLM-ready Markdown), not as the main fetch path. Firecrawl is a SaaS → it would be an external dependency. |
| **spider-rs, go-rod** | **No** | Other languages; built for throughput we don't need. |
| **Proxy fleets, residential IPs, geo/fingerprint sync** | **Not now** | Personal-scale volume. Keep a slot: proxy config is a fetcher concern, invisible to recipes. |

## Takeaways that change the design

1. **The extraction method matters more than the fetch engine.** If OLX serves a JSON
   endpoint or embedded state, most anti-bot and selector problems disappear. The
   first spike should be "what structured data does olx.pl expose?", not "which
   stealth browser?".
2. **"Blocked" is often a 200.** Fallback and retry need content-based classification,
   not just status codes.
3. **A parse failure must never look like a data change.** Combined with R7 (history),
   a broken selector would otherwise write "price changed to null" snapshots for every
   offer. See ADR 0005.

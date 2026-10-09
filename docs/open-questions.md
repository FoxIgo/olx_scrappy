# Open questions

Resolved items move to [requirements.md](requirements.md).

## Resolved
- Language → Python ([ADR 0003](adr/0003-language-python.md))
- What we track → R6–R9 · Saved searches → R10 · Specs → LLM (R11, R14)
- Database → SQLite, Postgres-ready (R12) · Volume → medium (R13)

## Still open
1. **Access method per site (spike needed).**
   - olx.pl: private JSON endpoints / embedded state JSON vs HTML parsing.
   - allegro.pl: official REST API vs scraping (strong anti-bot protection).
2. **Notification channel.** Out of scope for now. Revisit when cron arrives.
3. **Where does it run?** Local machine vs small VPS/container. Affects the worker
   setup and browser engines.
4. **Raw page retention.** Archive fetched pages for re-parsing (ADR 0005 §4)? Storing
   them compressed, at least for degraded runs, is recommended. How long to keep them?
5. **Interfaces.** Exact CLI commands and the browse/filter UX before the web UI exists.
6. **ToS check** for each site before building its recipe.

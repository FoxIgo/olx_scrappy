# Safe actions

Writes happen only through these application commands, which enforce validation,
idempotency and history. Never write through SQL. Run each one only when the user asked
for that change. Run them via the wrapper: `python <skill-dir>/scripts/q.py --cmd <command> ...`

| Action | Command | Effect / caveats |
| --- | --- | --- |
| Add a saved search | `search add <name> "<url>" --category <c>` | Validates the URL first; unsupported URL shapes are rejected with a reason. The category must exist (`q schema`). |
| Start a run | `run <search> --inline` | **Makes real requests to the marketplace** and, if extraction is enabled, **paid LLM calls**. Confirm first unless the user explicitly asked. Without `--inline` it only enqueues for the worker. Prints a run report. |
| Resume a run | `resume <run-id> [--inline]` | Re-queues unfinished/failed jobs of that run, e.g. after a block, a crash, or a missing API key was added. |
| Relevance override | `offers relevance <search> <source:id> --yes / --no / --clear` | Overrides the LLM's relevance for that search only; `--clear` returns to the derived value. Reversible. |
| Re-extract attributes | `extract requeue [--category <c>] [--force]` | Queues LLM extraction for offers whose extraction is missing/outdated (`--force`: all). **Paid LLM calls**; check the count with `q health` first and state it. |

After an action, verify the result with a `q` command (e.g. `q offer <id>` after a
relevance override, `q health` after a run), rather than assuming it worked.

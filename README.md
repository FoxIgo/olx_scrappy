# olx_scrappy

Personal tool that scrapes marketplace offers (OLX.pl first), tracks changes, and uses an
LLM to extract structured attributes. Python server in `packages/server`
(hexagonal layout, uv). Design notes live in [docs/](docs/README.md).

## Quick start (Windows)

`start.bat` at the repo root syncs dependencies, creates `packages/server/.env` from the
example on first use, and stores data in `./data`:

```bat
start.bat                                  :: interactive menu
start.bat offers list gtx-laptops --all    :: any scrappy command, passed through
```

## Develop

```sh
cd packages/server
uv sync
uv run poe check     # lint + pyright + import-linter + pytest
uv run scrappy version
```

Copy `packages/server/.env.example` to `.env` (repo root, used by compose) and fill in
`OPENROUTER_API_KEY`.

## Docker

```sh
docker compose build
docker compose up -d worker                       # runs `scrappy worker`
docker compose --profile tools run --rm cli version
```

One-off commands in the container use the `cli` service, e.g.
`docker compose --profile tools run --rm cli search list`.

Data is stored in `./data`; config is read from `packages/server/config` (mounted read-only).

## Usage

Categories (`config/categories.yaml`) and sources (`config/sources.yaml`) are read from
`SCRAPPY_CONFIG_DIR` (default `./config`); data (SQLite, raw page archive) goes to
`SCRAPPY_DATA_DIR` (default `./data`). The database is migrated automatically on every start.

```sh
cd packages/server
# 1. Save a search (the URL is validated right away; OLX supports /oferty/q-<query>/ URLs and category paths such as /elektronika/komputery/laptopy/q-acer-nitro-7/, optionally with ?search[...] filters)
uv run scrappy search add gtx-laptops "https://www.olx.pl/oferty/q-gtx-1650-laptop/" --category laptop
uv run scrappy search list
uv run scrappy search show gtx-laptops

# 2. Run it. --inline executes the jobs in this process and prints the run report;
#    without it the run is only queued for `scrappy worker` (--wait follows it).
uv run scrappy run gtx-laptops --inline
uv run scrappy worker                      # long-running worker (Ctrl+C / SIGTERM stops gracefully)

# 3. Look at the results
uv run scrappy runs list [gtx-laptops]
uv run scrappy runs show RUN_ID            # status, phases, fill rates, coverage, LLM cost, errors
uv run scrappy offers list gtx-laptops --relevant --where "ram_gb>=16" --where "gpu~gtx" --sort price
uv run scrappy offers show olx_pl:1098526767
uv run scrappy offers relevance gtx-laptops olx_pl:1098526767 --no     # or --yes / --clear

# Maintenance
uv run scrappy resume RUN_ID [--inline]    # re-queue the failed jobs of a run
uv run scrappy extract requeue [--category laptop] [--force]   # re-extract from stored data
uv run scrappy db upgrade
```

`--where` takes `ATTRIBUTE OP VALUE` with `OP` one of `= != < <= > >= ~` (`~` is a
case-insensitive substring match for text attributes); repeat it to AND filters.
Errors print as one red line with exit code 1; add `--debug` (before the command) for the
traceback. Without `OPENROUTER_API_KEY` pages are still fetched, but extraction jobs fail
with a clear message and the run ends `PARTIAL`; set the key and `scrappy resume RUN_ID`.

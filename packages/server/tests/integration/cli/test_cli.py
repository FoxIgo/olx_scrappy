"""CLI commands against a real SQLite database, with a fake source and a fake LLM."""

from __future__ import annotations

from typing import Any, cast

from typer.testing import CliRunner

from scrappy.application.ports.listing_source import ListingSource
from scrappy.domain.shared import SourceId
from scrappy.infrastructure.scraping.engines.base import FetchRequest, PageFetcher, RawPage
from scrappy.infrastructure.scraping.sources.olx_pl.source import OlxPlListingSource
from scrappy.main import make_cli_context
from scrappy.presentation.cli.app import app
from tests.integration.cli.conftest import SEARCH_URL, CliEnv


class NeverFetcher:
    async def fetch(self, req: FetchRequest) -> RawPage:
        raise AssertionError("adding a search must not touch the network")

    async def aclose(self) -> None:
        pass


# ------------------------------------------------------------------------------ search


def test_search_add_list_show(env: CliEnv) -> None:
    out = env.ok("search", "add", "gtx-laptops", SEARCH_URL, "--category", "laptop")
    assert "Added search" in out
    assert "Already exists" in env.ok("search", "add", "gtx-laptops", SEARCH_URL, "-c", "laptop")

    listing = env.ok("search", "list")
    assert "gtx-laptops" in listing
    assert SEARCH_URL in listing

    shown = env.ok("search", "show", "gtx-laptops")
    assert "Search gtx-laptops" in shown
    assert "olx_pl" in shown


def test_search_add_conflict_unknown_category_and_unknown_source(env: CliEnv) -> None:
    env.ok("search", "add", "s1", SEARCH_URL, "--category", "laptop")
    assert "already exists" in env.fail("search", "add", "s1", SEARCH_URL + "2", "-c", "laptop")
    assert "unknown category" in env.fail("search", "add", "s2", SEARCH_URL, "-c", "tv")
    assert "unknown source" in env.fail(
        "search", "add", "s3", SEARCH_URL, "-c", "laptop", "--source", "allegro_pl"
    )


def test_search_add_rejects_unsupported_url_immediately(env: CliEnv) -> None:
    real_olx = cast(PageFetcher, NeverFetcher())
    sources: dict[SourceId, ListingSource] = {SourceId("olx_pl"): OlxPlListingSource(real_olx)}
    context = make_cli_context(env.settings, sources=sources)

    def add(url: str) -> Any:
        return CliRunner().invoke(
            app, ["search", "add", "olx-phones", url, "-c", "laptop"], obj=context
        )

    bad = add("https://www.olx.pl/oferty/krakow/")
    assert bad.exit_code == 1
    assert "region paths are not" in " ".join(bad.output.split())
    assert "Traceback" not in bad.output
    assert "No saved searches" in env.ok("search", "list")

    good = add("https://www.olx.pl/oferty/q-gtx-1650-laptop/")
    assert good.exit_code == 0, good.output
    assert "olx-phones" in env.ok("search", "list")


def test_unknown_search_is_a_clean_error_but_debug_shows_traceback(env: CliEnv) -> None:
    out = env.fail("search", "show", "nope")
    assert "error:" in out
    assert "not found" in out
    debug = env.invoke("--debug", "search", "show", "nope")
    assert debug.exit_code != 0
    assert debug.exception is not None


def test_invalid_slug_is_a_clean_error(env: CliEnv) -> None:
    assert "invalid search name" in env.fail("search", "show", "Not A Slug")


# ---------------------------------------------------------------------------------- run


def test_run_inline_scrapes_only_and_reports_the_extraction_backlog(env: CliEnv) -> None:
    env.ok("search", "add", "gtx-laptops", SEARCH_URL, "--category", "laptop")
    out = env.ok("run", "gtx-laptops", "--inline")
    assert "Started run" in out
    assert "Run report" in out
    assert "COMPLETED" in out
    assert "discovery" in out
    assert "OK=1" in out.replace("ok=1", "OK=1")  # one search page fetched
    assert "backlog for this search: 4" in out
    assert "LLM tokens" not in out
    assert env.extractor is not None
    assert env.extractor.calls == []  # a run is scraping only (ADR 0010)

    extracted = env.ok("extract", "--inline")
    assert "stored 4" in extracted
    assert len(env.extractor.calls) == 4
    assert "backlog for this search: 0" in env.ok(
        "runs", "show", next(w for w in out.split() if len(w) == 32)
    )


def test_run_without_worker_only_enqueues(env: CliEnv) -> None:
    env.ok("search", "add", "gtx-laptops", SEARCH_URL, "--category", "laptop")
    out = env.ok("run", "gtx-laptops")
    assert "scrappy worker" in out
    assert "already has a running run" in env.ok("run", "gtx-laptops")


def test_runs_list_and_show(ran: CliEnv) -> None:
    listing = ran.ok("runs", "list")
    assert "gtx-laptops" in listing and "COMPLETED" in listing
    assert "COMPLETED" in ran.ok("runs", "list", "gtx-laptops")
    run_id = next(w for w in listing.split() if len(w) == 32)
    shown = ran.ok("runs", "show", run_id)
    assert run_id in shown and "Fill rates" in shown
    assert "not found" in ran.fail("runs", "show", "nope")


def test_second_run_fetches_no_extractions_again(ran: CliEnv) -> None:
    assert ran.extractor is not None
    calls = len(ran.extractor.calls)
    assert "COMPLETED" in ran.ok("run", "gtx-laptops", "--inline")
    assert len(ran.extractor.calls) == calls  # content unchanged -> no new LLM calls


# --------------------------------------------------------------------------- offers


def test_offers_list_shows_title_price_attributes_and_url(ran: CliEnv) -> None:
    out = ran.ok("offers", "list", "gtx-laptops")
    assert "Laptop 16GB GTX" in out
    assert "2000 PLN" in out
    assert "ram_gb=16" in out
    assert "https://example.test/olx_pl/a1" in out
    assert "olx_pl:a4" in out and "4 offer(s)" in out


def test_offers_list_relevant_hides_other_category(ran: CliEnv) -> None:
    out = ran.ok("offers", "list", "gtx-laptops", "--relevant")
    assert "olx_pl:a1" in out
    assert "olx_pl:a4" not in out


def test_offers_list_where_filters(ran: CliEnv) -> None:
    out = ran.ok("offers", "list", "gtx-laptops", "--where", "ram_gb>=16")
    assert "olx_pl:a1" in out and "olx_pl:a3" in out
    assert "olx_pl:a2" not in out and "olx_pl:a4" not in out

    out = ran.ok("offers", "list", "gtx-laptops", "-w", "ram_gb>=16", "-w", "gpu~gtx")
    assert "olx_pl:a1" in out and "olx_pl:a3" not in out

    out = ran.ok("offers", "list", "gtx-laptops", "--where", "ram_gb<16")
    assert "olx_pl:a2" in out and "olx_pl:a1" not in out

    out = ran.ok("offers", "list", "gtx-laptops", "--where", "ram_gb!=16", "--category", "laptop")
    assert "olx_pl:a2" in out and "olx_pl:a3" in out and "olx_pl:a1" not in out


def test_offers_list_bad_filters_are_clean_errors(ran: CliEnv) -> None:
    assert "cannot parse filter" in ran.fail("offers", "list", "gtx-laptops", "-w", "ram_gb")
    assert "no attribute" in ran.fail("offers", "list", "gtx-laptops", "-w", "color=red")
    assert "unknown sort" in ran.fail("offers", "list", "gtx-laptops", "--sort", "size")
    assert "unknown status" in ran.fail("offers", "list", "gtx-laptops", "--status", "zzz")


def test_offers_list_status_limit_and_sort(ran: CliEnv) -> None:
    assert "No offers match" in ran.ok("offers", "list", "gtx-laptops", "--status", "sold")
    assert "4 offer(s)" in ran.ok("offers", "list", "gtx-laptops", "--status", "active")

    asc = ran.ok("offers", "list", "gtx-laptops", "--sort", "price")
    ids = [i for i in ("a4", "a2", "a1", "a3") if f"olx_pl:{i}" in asc]
    assert ids == ["a4", "a2", "a1", "a3"]
    positions = [asc.index(f"olx_pl:{i}") for i in ("a4", "a2", "a1", "a3")]
    assert positions == sorted(positions)

    desc = ran.ok("offers", "list", "gtx-laptops", "--sort", "price-desc", "--limit", "2")
    assert "olx_pl:a3" in desc and "olx_pl:a1" in desc
    assert "olx_pl:a2" not in desc and "2 offer(s)" in desc


def test_offers_show(ran: CliEnv) -> None:
    out = ran.ok("offers", "show", "olx_pl:a1")
    assert "Laptop 16GB GTX" in out
    assert "Latest extraction: laptop" in out
    assert "gpu" in out and "GTX 1650" in out
    assert "gtx-laptops" in out
    assert "No recorded changes" in out
    assert "not found" in ran.fail("offers", "show", "olx_pl:zzz")
    assert "invalid offer id" in ran.fail("offers", "show", "nocolon")


def test_relevance_override_round_trip(ran: CliEnv) -> None:
    assert "olx_pl:a4" not in ran.ok("offers", "list", "gtx-laptops", "--relevant")

    out = ran.ok("offers", "relevance", "gtx-laptops", "olx_pl:a4", "--yes")
    assert "relevant" in out
    assert "olx_pl:a4" in ran.ok("offers", "list", "gtx-laptops", "--relevant")

    ran.ok("offers", "relevance", "gtx-laptops", "olx_pl:a1", "--no")
    assert "olx_pl:a1" not in ran.ok("offers", "list", "gtx-laptops", "--relevant")

    cleared = ran.ok("offers", "relevance", "gtx-laptops", "olx_pl:a1", "--clear")
    assert "override cleared" in cleared
    assert "olx_pl:a1" in ran.ok("offers", "list", "gtx-laptops", "--relevant")


def test_relevance_needs_exactly_one_flag_and_a_known_link(ran: CliEnv) -> None:
    both = ran.invoke("offers", "relevance", "gtx-laptops", "olx_pl:a1", "--yes", "--no")
    assert both.exit_code == 2
    none = ran.invoke("offers", "relevance", "gtx-laptops", "olx_pl:a1")
    assert none.exit_code == 2
    assert "not found" in ran.fail("offers", "relevance", "gtx-laptops", "olx_pl:zzz", "--yes")


# ------------------------------------------------------------------ extraction / misc


def test_extract_status_force_and_requeue_alias(ran: CliEnv) -> None:
    status = ran.ok("extract")
    assert "0 offer(s) waiting" in status and "custom" in status and "lane" in status
    assert "Nothing to queue" in ran.ok("extract", "requeue")
    assert "marked 3" in ran.ok("extract", "requeue", "--category", "laptop", "--force")

    out = ran.ok("extract", "force", "--where", "category=other")
    assert "Marked 1 offer(s) for re-extraction" in out
    assert "scrappy worker" in out
    assert "4 offer(s) waiting" in ran.ok("extract", "status")
    assert ran.extractor is not None
    calls = len(ran.extractor.calls)
    assert "stored 4" in ran.ok("extract", "--inline")
    assert len(ran.extractor.calls) == calls + 4
    assert "Marked 0" in ran.ok("extract", "force", "--parked")


def test_extract_errors_are_clean(ran: CliEnv) -> None:
    assert "unknown extraction profile nope" in ran.fail("extract", "--inline", "-p", "nope")
    assert "invalid --where" in ran.fail("extract", "force", "--where", "model")
    assert "unknown field 'colour'" in ran.fail("extract", "force", "--where", "colour=red")
    assert "unknown profile nope" in ran.fail("extract", "force", "--profile", "nope")


def test_extract_profiles_shows_health_without_network(ran: CliEnv) -> None:
    out = ran.ok("extract", "profiles")
    assert "custom" in out and "lane" in out and "ok: injected extractor" in out


def test_db_upgrade(env: CliEnv) -> None:
    assert "latest schema" in env.ok("db", "upgrade")


def test_missing_openrouter_key_leaves_a_backlog_that_heals_once_a_profile_works(
    env: CliEnv,
) -> None:
    """No extraction.yaml and no key: the derived ``openrouter`` profile is unavailable."""
    env.ok("search", "add", "gtx-laptops", SEARCH_URL, "--category", "laptop")
    out = env.ok("run", "gtx-laptops", "--inline", with_extractor=False)
    assert "COMPLETED" in out  # scraping does not depend on the LLM any more
    assert "backlog for this search: 4" in out

    stuck = env.ok("extract", "--inline", with_extractor=False)
    assert "No extraction profile is available" in stuck
    assert "OPENROUTER_API_KEY is not set" in stuck.replace("\n", " ")
    profiles = env.ok("extract", "profiles", with_extractor=False)
    assert "lane" in profiles and "UNAVAILABLE" in profiles
    assert "SCRAPPY_LLM_* settings" in profiles.replace("\n", " ")

    # discovery data is kept; nothing is extracted yet, nothing was penalized
    assert "olx_pl:a1" in env.ok("offers", "list", "gtx-laptops", with_extractor=False)
    assert "No offers match" in env.ok("offers", "list", "gtx-laptops", "--relevant")
    assert "4 offer(s) waiting" in env.ok("extract", "status", with_extractor=False)

    assert "stored 4" in env.ok("extract", "--inline")  # a working profile heals it
    assert "olx_pl:a1" in env.ok("offers", "list", "gtx-laptops", "--relevant")

"""``scrappy q ...`` end to end: real SQLite, fake source and LLM, JSON parsed back."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from tests.integration.cli.conftest import CliEnv

ENVELOPE_KEYS = {"ok", "command", "params", "count", "truncated", "data", "notes"}


def q(env: CliEnv, *args: str, code: int = 0) -> dict[str, Any]:
    result = env.invoke("q", *args)
    assert result.exit_code == code, result.output
    assert "Traceback" not in result.output
    document = json.loads(result.stdout)
    assert isinstance(document, dict)
    return document  # type: ignore[return-value]


def test_envelope_shape_and_compact_vs_pretty(ran: CliEnv) -> None:
    compact = ran.invoke("q", "offers").stdout
    assert compact.count("\n") == 1
    document = json.loads(compact)
    assert set(document) == ENVELOPE_KEYS
    assert document["ok"] is True and document["command"] == "q.offers"
    assert document["params"]["relevance"] == "relevant"
    assert document["params"]["status"] == ["active"]
    pretty = ran.invoke("q", "offers", "--pretty").stdout
    assert pretty.count("\n") > 10
    assert json.loads(pretty) == document


def test_overview(ran: CliEnv) -> None:
    document = q(ran, "overview")
    data = document["data"]
    assert data["database"] == {"dialect": "sqlite"}
    (search,) = data["searches"]
    assert search["name"] == "gtx-laptops" and search["category"] == "laptop"
    assert search["offers"] == {
        "total": 4,
        "relevant": 3,
        "irrelevant": 1,
        "relevance_unknown": 0,
        "extracted": 4,
        "extraction_backlog": 0,
    }
    assert data["extraction"]["backlog"] == 0 and data["extraction"]["default_profile"] == "custom"
    run_id = search["last_run"]["id"]
    assert len(run_id) == 32 and search["last_run"]["status"] == "completed"
    assert search["last_run"]["started_at"].endswith("Z")
    assert data["categories"] == [{"name": "laptop", "version": 1, "attributes": 7}]
    assert data["totals"]["offers"] == 4
    assert ran.ok("runs", "show", run_id)  # the id is usable with existing commands


def test_schema_and_tables(ran: CliEnv) -> None:
    data = q(ran, "schema", "--category", "laptop")["data"]
    attributes = {a["name"]: a for a in data["categories"][0]["attributes"]}
    assert attributes["storage_type"]["values"] == ["ssd", "hdd", "emmc"]
    assert attributes["ram_gb"]["type"] == "integer"
    assert "tables" not in data
    with_tables = q(ran, "schema", "--tables")["data"]
    names = {t["name"] for t in with_tables["tables"]}
    assert {"offers", "extractions"} <= names and "alembic_version" not in names
    error = q(ran, "schema", "--category", "tv", code=1)
    assert error["ok"] is False and error["error"]["type"] == "InvalidRequestError"


def test_offers_filters_fields_and_decimal_strings(ran: CliEnv) -> None:
    document = q(ran, "offers", "--search", "gtx-laptops")
    rows = document["data"]
    assert document["count"] == 3  # the charger is not relevant
    assert {r["id"] for r in rows} == {"olx_pl:a1", "olx_pl:a2", "olx_pl:a3"}
    first = next(r for r in rows if r["id"] == "olx_pl:a1")
    assert first["price"] == "2000" and first["currency"] == "PLN"
    assert first["attributes"]["ram_gb"] == 16 and first["attributes"]["gpu"] == "GTX 1650"
    assert first["first_seen_at"].endswith("Z") and first["relevant"] is True
    assert any("hidden" in n for n in document["notes"])

    allrows = q(ran, "offers", "--search", "gtx-laptops", "--all")["data"]
    assert len(allrows) == 4

    filtered = q(ran, "offers", "--search", "gtx-laptops", "-w", "ram_gb>=16", "-w", "price<3000")
    assert [r["id"] for r in filtered["data"]] == ["olx_pl:a1"]

    projected = q(
        ran, "offers", "--search", "gtx-laptops", "--fields", "id,price,ram_gb", "-n", "2"
    )
    assert projected["truncated"] is True and projected["count"] == 2
    assert set(projected["data"][0]) == {"id", "price", "attributes"}
    assert set(projected["data"][0]["attributes"]) == {"ram_gb"}

    cheapest = q(ran, "offers", "--search", "gtx-laptops", "--sort", "price", "-n", "1")
    assert cheapest["data"][0]["id"] == "olx_pl:a2"
    title = q(ran, "offers", "--search", "gtx-laptops", "-w", "title~16gb")
    assert [r["id"] for r in title["data"]] == ["olx_pl:a1"]
    assert q(ran, "offers", "--status", "sold")["count"] == 0
    assert q(ran, "offers", "--status", "any", "--all")["count"] == 4


def test_offer_detail(ran: CliEnv) -> None:
    document = q(ran, "offer", "olx_pl:a1", "olx_pl:zzz")
    (detail,) = document["data"]
    assert detail["id"] == "olx_pl:a1" and detail["price"]["amount"] == "2000"
    assert detail["extraction"]["category"] == "laptop"
    assert detail["extraction"]["provenance"]["model"] == "fake-model"
    assert detail["searches"][0]["search"] == "gtx-laptops"
    assert detail["description"] == "fast one"
    assert any("olx_pl:zzz" in n for n in document["notes"])
    assert q(ran, "offer", "olx_pl:zzz", code=1)["error"]["type"] == "NotFoundError"


def test_facets(ran: CliEnv) -> None:
    data = q(ran, "facets", "--search", "gtx-laptops", "--attr", "ram_gb", "--attr", "gpu")["data"]
    ram, gpu = data
    assert {v["value"]: v["count"] for v in ram["values"]} == {16: 1, 8: 1, 32: 1}
    assert ram["numeric"]["min"] == "8" and ram["numeric"]["max"] == "32"
    assert gpu["values"] == [{"value": "GTX 1650", "count": 1}] and gpu["null"] == 2
    bad = q(ran, "facets", "--search", "gtx-laptops", code=1)
    assert "at least one --attr" in bad["error"]["message"]


def test_stats(ran: CliEnv) -> None:
    document = q(ran, "stats", "--search", "gtx-laptops", "--by", "ram_gb")
    groups = {g["group"]["ram_gb"]: g for g in document["data"]}
    assert groups[16]["median"] == "2000.00" and groups[16]["n"] == 1
    assert groups[8]["min"] == "1000" and groups[32]["max"] == "3000"
    overall = q(ran, "stats", "--search", "gtx-laptops")["data"][0]
    assert overall["n"] == 3 and overall["median"] == "2000.00" and overall["mean"] == "2000.00"
    assert overall["p25"] == "1500.00" and overall["p75"] == "2500.00"


def test_deals(ran: CliEnv) -> None:
    document = q(ran, "deals", "--search", "gtx-laptops", "--min-group", "3", "--max-ratio", "0.6")
    (deal,) = document["data"]
    assert deal["offer"]["id"] == "olx_pl:a2"
    assert deal["ratio"] == "0.500" and deal["group_size"] == 3
    assert deal["group_median"] == "2000.00" and "50%" in deal["reason"]
    none = q(ran, "deals", "--search", "gtx-laptops", "--compare-by", "gpu")
    assert none["data"] == [] and any("no deals" in n or "lack" in n for n in none["notes"])
    bad = q(ran, "deals", "--search", "gtx-laptops", "--max-ratio", "abc", code=1)
    assert bad["ok"] is False


def test_history(ran: CliEnv) -> None:
    document = q(ran, "history", "--search", "gtx-laptops", "--since", "2000-01-01")
    assert {o["id"] for o in document["data"]["new_offers"]} == {
        "olx_pl:a1",
        "olx_pl:a2",
        "olx_pl:a3",
    }
    assert document["data"]["changes"] is not None
    future = q(ran, "history", "--search", "gtx-laptops", "--since", "2999-01-01")
    assert future["data"]["new_offers"] == []
    single = q(ran, "history", "--offer", "olx_pl:a1", "--field", "price")
    assert single["ok"] is True
    assert q(ran, "history", "--since", "garbage", code=1)["ok"] is False


def test_health(ran: CliEnv) -> None:
    document = q(ran, "health", "--search", "gtx-laptops", "--runs", "3")
    data = document["data"]
    assert data["runs"][0]["status"] == "completed"
    assert data["runs"][0]["phases"]["extraction"]["accepted"] == 0  # not part of runs
    extraction = data["extraction"]
    assert extraction["offers"] == 4 and extraction["without_extraction"] == 0
    assert extraction["backlog"] == 0 and extraction["open_batches"] == []
    assert extraction["parked"] == 0
    assert extraction["profiles"][0]["name"] == "custom"
    assert "jobs" not in extraction
    rates = {r["attribute"]: r for r in data["attribute_null_rates"]}
    assert rates["ram_gb"]["extracted"] == 3 and rates["ram_gb"]["null"] == 0
    assert rates["gpu"]["null"] == 2 and rates["gpu"]["null_rate"] == 0.667
    assert data["stale"][0]["stale_offers"] == 0
    assert q(ran, "health", "--search", "nope", code=1)["error"]["type"] == "NotFoundError"


def test_sql_read_only_fallback(ran: CliEnv) -> None:
    document = q(
        ran,
        "sql",
        "SELECT external_id, price_amount FROM offers ORDER BY external_id",
        "--limit",
        "2",
    )
    assert document["data"]["columns"] == ["external_id", "price_amount"]
    assert document["data"]["rows"] == [["a1", "2000"], ["a2", "1000"]]
    assert document["truncated"] is True and document["count"] == 2

    rejected = q(ran, "sql", "DELETE FROM offers", code=1)
    assert rejected["ok"] is False and "allowed" in rejected["error"]["message"]
    assert q(ran, "sql", "SELECT 1; DROP TABLE offers", code=1)["ok"] is False
    assert q(ran, "sql", "SELECT count(*) FROM offers")["data"]["rows"] == [[4]]  # still there
    syntax = q(ran, "sql", "SELEC 1", code=1)
    assert syntax["error"]["type"] == "InvalidRequestError"


def test_errors_are_envelopes_not_tracebacks(ran: CliEnv) -> None:
    missing = q(ran, "offers", "--search", "nope", code=1)
    assert missing["ok"] is False and missing["command"] == "q.offers"
    assert (
        missing["error"]["type"] == "NotFoundError" and "not found" in missing["error"]["message"]
    )
    assert "data" not in missing
    assert q(ran, "offers", "-w", "nonsense", code=1)["error"]["type"] == "InvalidRequestError"
    assert q(ran, "offers", "--search", "gtx-laptops", "-w", "zzz=1", code=1)["ok"] is False
    assert q(ran, "offers", "--status", "bogus", code=1)["ok"] is False
    debug = ran.invoke("--debug", "q", "offers", "--search", "nope")
    assert debug.exit_code != 0 and debug.exception is not None


# ---------------------------------------------------------------------------- export


def read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def test_export_to_file_writes_csv_and_prints_envelope(ran: CliEnv, tmp_path: Path) -> None:
    target = tmp_path / "out" / "laptops.csv"
    document = q(ran, "export", "--search", "gtx-laptops", "--out", str(target))
    data = document["data"]
    assert Path(data["path"]) == target.resolve() and data["rows"] == 3
    assert document["count"] == 3 and document["command"] == "q.export"
    assert any("3 row(s) exported" in n for n in document["notes"])

    columns, rows = read_csv(target.read_text(encoding="utf-8"))
    assert columns == data["columns"]
    assert columns[:15] == [
        "offer_id",
        "source",
        "title",
        "url",
        "status",
        "location",
        "price_kind",
        "price_amount",
        "currency",
        "negotiable",
        "first_seen_at",
        "last_seen_at",
        "search",
        "relevant",
        "category",
    ]
    assert columns[15:] == [
        "attr_gpu",
        "attr_cpu",
        "attr_ram_gb",
        "attr_storage_gb",
        "attr_storage_type",
        "attr_screen_in",
        "attr_condition",
    ]
    by_id = {r["offer_id"]: r for r in rows}
    assert set(by_id) == {"olx_pl:a1", "olx_pl:a2", "olx_pl:a3"}
    a1 = by_id["olx_pl:a1"]
    assert a1["attr_gpu"] == "GTX 1650" and a1["attr_ram_gb"] == "16"
    assert a1["price_amount"] == "2000" and a1["currency"] == "PLN"
    assert a1["search"] == "gtx-laptops" and a1["relevant"] == "true"
    assert a1["category"] == "laptop" and a1["source"] == "olx_pl"
    assert a1["attr_cpu"] == "" and by_id["olx_pl:a2"]["attr_gpu"] == ""  # stable, null = empty
    assert a1["first_seen_at"].endswith("Z")


def test_export_streams_to_stdout_without_envelope(ran: CliEnv) -> None:
    result = ran.invoke("q", "export", "--search", "gtx-laptops", "--all", "-w", "ram_gb>=16")
    assert result.exit_code == 0, result.output
    columns, rows = read_csv(result.stdout)
    assert "attr_ram_gb" in columns
    assert {r["offer_id"] for r in rows} == {"olx_pl:a1", "olx_pl:a3"}
    assert not result.stdout.lstrip().startswith("{")


def test_export_jsonl_and_without_search_uses_present_categories(
    ran: CliEnv, tmp_path: Path
) -> None:
    target = tmp_path / "all.jsonl"
    document = q(ran, "export", "--format", "jsonl", "--all", "--out", str(target))
    assert document["data"]["rows"] == 4
    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    laptop = next(row for row in lines if row["offer_id"] == "olx_pl:a1")
    assert laptop["attr_ram_gb"] == 16 and laptop["attr_cpu"] is None
    assert laptop["price_amount"] == "2000" and laptop["negotiable"] is False
    charger = next(row for row in lines if row["offer_id"] == "olx_pl:a4")
    assert charger["category"] == "other" and charger["relevant"] is False
    assert charger["attr_gpu"] is None  # laptop columns still present (only category here)


def test_export_errors_stay_envelopes(ran: CliEnv) -> None:
    assert q(ran, "export", "--format", "xlsx", code=1)["ok"] is False
    assert q(ran, "export", "--search", "nope", code=1)["error"]["type"] == "NotFoundError"

"""``scrappy benchmarks import|list`` end to end on real SQLite with a tiny snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.integration.cli.conftest import CliEnv
from tests.unit.infrastructure.benchmarks.snapshots import sample_lines, write_zip


def run(env: CliEnv, *args: str, code: int = 0) -> dict[str, Any]:
    result = env.invoke("benchmarks", *args)
    assert result.exit_code == code, result.output
    assert "Traceback" not in result.output
    return json.loads(result.stdout)


def test_import_then_list(env: CliEnv, tmp_path: Path) -> None:
    snapshot = write_zip(tmp_path / "opendata-latest.zip", sample_lines())

    report = run(env, "import", "--file", str(snapshot))
    assert report["ok"] is True
    assert report["components_total"] == {"cpu": 1, "gpu": 2}
    assert report["components_added"] == 3

    again = run(env, "import", "--file", str(snapshot))
    assert again["components_added"] == 0 and again["benchmarks_saved"] == 3

    listing = run(env, "list", "--kind", "gpu")
    assert listing["count"] == 2
    top, second = listing["data"]
    assert (top["slug"], top["segment"]) == ("rtx-4060", "unknown")
    assert (second["slug"], second["segment"]) == ("rtx-4060-laptop", "mobile")
    assert second["benchmarks"][0]["score"] == 345.0
    assert second["benchmarks"][0]["samples"] == 4

    searched = run(env, "list", "--search", "i5-12450h", "--limit", "5")
    assert [row["slug"] for row in searched["data"]] == ["i5-12450h"]


def test_import_needs_exactly_one_source(env: CliEnv) -> None:
    output = env.fail("benchmarks", "import")
    assert "exactly one" in output


def test_missing_file_and_bad_kind_are_one_line_errors(env: CliEnv, tmp_path: Path) -> None:
    assert "not found" in env.fail("benchmarks", "import", "--file", str(tmp_path / "nope.zip"))
    assert "unknown kind" in env.fail("benchmarks", "list", "--kind", "ram")

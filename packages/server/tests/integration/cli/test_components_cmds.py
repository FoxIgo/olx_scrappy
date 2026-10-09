"""``scrappy components resolve|status|alias add`` end to end on real SQLite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.integration.cli.conftest import CliEnv
from tests.unit.infrastructure.benchmarks.snapshots import sample_lines, write_zip


def run(env: CliEnv, *args: str, code: int = 0) -> dict[str, Any]:
    result = env.invoke("components", *args)
    assert result.exit_code == code, result.output
    assert "Traceback" not in result.output
    return json.loads(result.stdout)


def test_resolve_status_alias_cycle(ran: CliEnv, tmp_path: Path) -> None:
    snapshot = write_zip(tmp_path / "opendata-latest.zip", sample_lines())
    ran.ok("benchmarks", "import", "--file", str(snapshot))

    before = run(ran, "status")
    assert before["backlog"] == 1  # the one extracted "GTX 1650"
    assert before["counts"] == {} and before["top_unresolved"] == []

    resolved = run(ran, "resolve", "--max", "5")
    assert (resolved["processed"], resolved["remaining"]) == (1, 0)
    assert resolved["by_method"] == {"unresolved": 1}  # the sample catalog has no GTX 1650

    status = run(ran, "status")
    assert status["backlog"] == 0
    assert status["counts"] == {"gpu": {"unresolved": 1}}
    assert [(u["kind"], u["raw_text"], u["offers"]) for u in status["top_unresolved"]] == [
        ("gpu", "gtx 1650", 1)
    ]

    added = run(ran, "alias", "add", "GPU", "GTX 1650", "gpu:rtx-4060-laptop")
    assert (added["alias"], added["links_marked_stale"]) == ("gtx 1650", 1)

    again = run(ran, "resolve")
    assert (again["processed"], again["by_method"]) == (1, {"alias": 1})
    assert run(ran, "status")["counts"] == {"gpu": {"alias": 1}}


def test_bad_input_is_a_one_line_error(ran: CliEnv) -> None:
    assert "unknown kind" in ran.fail("components", "alias", "add", "ram", "x", "gpu:y")
    assert "unknown component" in ran.fail("components", "alias", "add", "gpu", "x", "gpu:nope")

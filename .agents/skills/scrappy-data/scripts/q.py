#!/usr/bin/env python3
"""Run `scrappy q ...` (or another scrappy command) from anywhere in the repository.

Usage:
    python q.py <q-subcommand> [args...]           -> scrappy q <q-subcommand> [args...]
    python q.py --cmd <command> [args...]          -> scrappy <command> [args...]   (safe actions)
    python q.py --data-dir <dir> <q-subcommand>    -> point the app at another data directory

It finds the Python project that defines the `scrappy` console script (env var
SCRAPPY_PROJECT overrides the search), then runs it through `uv run`, so the agent never
has to know where the package lives or activate a virtualenv. The command's stdout,
stderr and exit code are passed through unchanged.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_SCRIPT_RE = re.compile(r"^\s*scrappy\s*=", re.MULTILINE)


def _defines_scrappy(pyproject: Path) -> bool:
    try:
        return bool(_SCRIPT_RE.search(pyproject.read_text(encoding="utf-8")))
    except OSError:
        return False


def find_project() -> Path:
    override = os.environ.get("SCRAPPY_PROJECT")
    if override:
        path = Path(override).resolve()
        if _defines_scrappy(path / "pyproject.toml"):
            return path
        sys.exit(f"SCRAPPY_PROJECT={override} has no pyproject.toml defining `scrappy`")

    starts = [Path.cwd().resolve(), Path(__file__).resolve().parent]
    seen: set[Path] = set()
    for start in starts:
        for directory in (start, *start.parents):
            if directory in seen:
                continue
            seen.add(directory)
            if _defines_scrappy(directory / "pyproject.toml"):
                return directory
            # Monorepo layouts: look one and two levels down (e.g. <root>/<group>/<pkg>/).
            for candidate in sorted(directory.glob("*/pyproject.toml")) + sorted(
                directory.glob("*/*/pyproject.toml")
            ):
                if _defines_scrappy(candidate):
                    return candidate.parent
    sys.exit("Could not find a project defining the `scrappy` command; set SCRAPPY_PROJECT.")


def main(argv: list[str]) -> int:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    args = list(argv)
    if len(args) >= 2 and args[0] == "--data-dir":
        env["SCRAPPY_DATA_DIR"] = str(Path(args[1]).resolve())
        args = args[2:]

    if args and args[0] == "--cmd":
        command = args[1:]
    else:
        command = ["q", *args]
    if not command:
        sys.exit(__doc__)

    project = find_project()
    if "SCRAPPY_CONFIG_DIR" not in env and (project / "config").is_dir():
        env["SCRAPPY_CONFIG_DIR"] = str((project / "config").resolve())
    if "SCRAPPY_DATA_DIR" not in env:
        for root_cand in (project.parent, project.parent.parent, project):
            if (root_cand / "data" / "scrappy.db").is_file():
                env["SCRAPPY_DATA_DIR"] = str((root_cand / "data").resolve())
                break

    proc = subprocess.run(
        ["uv", "run", "--project", str(project), "--quiet", "scrappy", *command],
        env=env,
        check=False,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

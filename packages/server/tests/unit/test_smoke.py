from importlib.metadata import version

from typer.testing import CliRunner

import scrappy
from scrappy.presentation.cli.app import app


def test_import() -> None:
    assert scrappy.__doc__


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == version("scrappy")

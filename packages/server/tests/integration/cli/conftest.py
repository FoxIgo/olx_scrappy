"""Real SQLite + real config files in a temp dir; fake listing source and extractor."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
)
from scrappy.application.ports.listing_source import ListingSource, SearchPageResult
from scrappy.domain.category import OTHER_CATEGORY
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import Price
from scrappy.domain.shared import FetchOutcome, SourceId
from scrappy.infrastructure.config.settings import Settings
from scrappy.main import Container, build_app, make_cli_context
from scrappy.presentation.cli.app import app
from tests.unit.builders import LAPTOP, details
from tests.unit.fakes import ScriptedExtractor, ScriptedListingSource

SEARCH_URL = "https://example.test/search?q=laptop"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def classify(request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
    """Fake LLM: 'laptop' titles are laptops (RAM from '<n>GB', GPU if 'gtx'), rest 'other'."""
    usage = TokenUsage(100, 20)
    title = request.title.lower()
    if "laptop" not in title:
        return ExtractionResult(OTHER_CATEGORY, {}, "fake-model", "p1", usage)
    ram = re.search(r"(\d+)gb", title)
    attributes: dict[str, object] = {"ram_gb": int(ram[1]) if ram else None}
    if "gtx" in title:
        attributes["gpu"] = "GTX 1650"
    return ExtractionResult(LAPTOP, attributes, "fake-model", "p1", usage)


def scripted_source(source: ScriptedListingSource | None = None) -> ScriptedListingSource:
    source = source or ScriptedListingSource("olx_pl")
    offers = (
        details("a1", title="Laptop 16GB GTX", description="fast one", has_delivery=True),
        details("a2", title="Laptop 8GB", description="slow one"),
        details("a3", title="Laptop 32GB", description="huge one", has_delivery=True),
        details("a4", title="Charger 65W", description="a charger"),
    )
    # different prices so --sort price is observable
    prices = {"a1": "2000", "a2": "1000", "a3": "3000", "a4": "50"}
    observations = tuple(
        replace(o, price=Price.fixed(prices[o.offer_id.external_id])) for o in offers
    )
    source.script_page(SEARCH_URL, SearchPageResult(FetchOutcome.OK, observations, total_results=4))
    return source


@dataclass
class CliEnv:
    settings: Settings
    sources: Mapping[SourceId, ListingSource]
    extractor: ScriptedExtractor | None
    runner: CliRunner = field(default_factory=CliRunner)

    def invoke(self, *args: str, with_extractor: bool = True) -> Result:
        context = make_cli_context(
            self.settings,
            sources=self.sources,
            extractor=self.extractor if with_extractor else None,
        )
        return self.runner.invoke(app, list(args), obj=context, env={"COLUMNS": "250"})

    def ok(self, *args: str, with_extractor: bool = True) -> str:
        result = self.invoke(*args, with_extractor=with_extractor)
        assert result.exit_code == 0, result.output
        return result.output

    def fail(self, *args: str) -> str:
        result = self.invoke(*args)
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output
        return result.output

    async def container(self, *, with_extractor: bool = True) -> Container:
        return await build_app(
            self.settings,
            sources=self.sources,
            extractor=self.extractor if with_extractor else None,
        )


@pytest.fixture(autouse=True)
def _no_real_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real profiles must never get a real key in tests (no network, ever)."""
    for name in ("OPENROUTER_API_KEY", "SCRAPPY_OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config = tmp_path / "config"
    config.mkdir()
    shutil.copy(FIXTURES / "categories.yaml", config / "categories.yaml")
    shutil.copy(FIXTURES / "scoring.yaml", config / "scoring.yaml")
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        data_dir=tmp_path / "data",
        config_dir=config,
        openrouter_api_key=None,
    )


@pytest.fixture
def env(settings: Settings) -> CliEnv:
    source = scripted_source()
    return CliEnv(settings, {source.source_id: source}, ScriptedExtractor(classify))


@pytest.fixture
def ran(env: CliEnv) -> CliEnv:
    """An env where search ``gtx-laptops`` was added, run inline once and extracted."""
    env.ok("search", "add", "gtx-laptops", SEARCH_URL, "--category", "laptop")
    env.ok("run", "gtx-laptops", "--inline")
    env.ok("extract", "--inline")
    return env

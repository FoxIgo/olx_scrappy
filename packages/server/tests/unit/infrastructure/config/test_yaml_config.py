from __future__ import annotations

from pathlib import Path

import pytest

from scrappy.domain.category import AttributeType, CategoryName
from scrappy.domain.shared import SourceId
from scrappy.infrastructure.config.categories import YamlCategoryProvider, load_categories
from scrappy.infrastructure.config.errors import ConfigError
from scrappy.infrastructure.config.sources import load_sources, parse_sources

CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"


def write(tmp_path: Path, text: str, name: str = "categories.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_categories_load() -> None:
    catalog = load_categories(CONFIG_DIR / "categories.yaml")
    laptop = catalog.get(CategoryName("laptop"))
    assert laptop is not None
    assert laptop.version == 2
    for name in ("vram_gb", "refresh_hz", "resolution", "battery_wh", "battery_note", "max_ram_gb"):
        assert laptop.attribute(name) is not None, name
    upgradeable = laptop.attribute("ram_upgradeable")
    assert upgradeable is not None
    assert upgradeable.type is AttributeType.BOOLEAN
    screen = laptop.attribute("screen_in")
    assert screen is not None
    assert screen.description is not None
    assert "refresh" in screen.description
    storage = laptop.attribute("storage_type")
    assert storage is not None
    assert storage.type is AttributeType.ENUM
    assert storage.values == ("ssd", "hdd", "emmc")


def test_shipped_sources_load() -> None:
    config = load_sources(CONFIG_DIR / "sources.yaml")
    olx = config.get(SourceId("olx_pl"))
    assert olx is not None
    assert olx.enabled
    assert olx.engine.engine == "curl_cffi"
    assert olx.engine.rate_limit == "1/3s"


async def test_provider_reloads_on_change(tmp_path: Path) -> None:
    path = write(tmp_path, "phone: {version: 1, attributes: {model: {type: string}}}")
    provider = YamlCategoryProvider(path)
    assert len(await provider.catalog()) == 1
    path.write_text(
        "phone: {version: 2, attributes: {model: {type: string}}}\n"
        "tv: {version: 1, attributes: {}}\n",
        encoding="utf-8",
    )
    import os

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert len(await provider.catalog()) == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("laptop: {version: 0, attributes: {}}", "laptop.version"),
        ("laptop: {attributes: {}}", "laptop.version: Field required"),
        (
            "laptop: {version: 1, attributes: {gpu: {type: float}}}",
            "laptop.attributes.gpu.type",
        ),
        (
            "laptop: {version: 1, attributes: {s: {type: enum}}}",
            "laptop.attributes.s: Value error, enum attributes need",
        ),
        (
            "laptop: {version: 1, attributes: {s: {type: string, values: [a]}}}",
            "only allowed for enum",
        ),
        ("laptop: {version: 1, colour: red}", "laptop.colour: Extra inputs"),
        ("other: {version: 1, attributes: {}}", "'other' is reserved"),
        ("Bad Name: {version: 1, attributes: {}}", "category 'Bad Name'"),
        ("- a\n- b", "top level must be a mapping"),
        ("laptop: [unclosed", "not valid YAML"),
    ],
)
def test_category_errors_name_file_and_key(tmp_path: Path, text: str, expected: str) -> None:
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as info:
        load_categories(path)
    assert expected in str(info.value)
    assert "categories.yaml" in str(info.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_categories(tmp_path / "nope.yaml")


def test_sources_engine_passthrough_and_errors() -> None:
    config = parse_sources(
        {
            "sources": {
                "a_b": {
                    "enabled": False,
                    "page_size": 40,
                    "engine": ["curl_cffi", "scrapling_stealthy"],
                    "rate_limit": "2/10s",
                    "custom": 1,
                }
            }
        },
        path=Path("sources.yaml"),
    )
    source = config.sources[SourceId("a_b")]
    assert not source.enabled
    assert source.page_size == 40
    assert source.engine.engines == ["curl_cffi", "scrapling_stealthy"]
    assert source.engine.extra == {"custom": 1}
    assert config.enabled == []

    with pytest.raises(ConfigError, match=r"sources\.a_b.*invalid rate limit"):
        parse_sources({"sources": {"a_b": {"rate_limit": "fast"}}}, path=Path("sources.yaml"))
    with pytest.raises(ConfigError, match=r"sources\.a_b\.page_size"):
        parse_sources({"sources": {"a_b": {"page_size": 0}}}, path=Path("sources.yaml"))

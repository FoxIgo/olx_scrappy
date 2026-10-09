"""ImportBenchmarks / ListComponents against the in-memory store with a scripted source."""

from __future__ import annotations

from pathlib import Path

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.benchmarks import BenchmarkEntry
from scrappy.application.use_cases.benchmarks import ImportBenchmarks, ListComponents
from scrappy.domain.component import ComponentKind
from tests.unit.fakes import FakeClock, InMemoryStore


class ScriptedBenchmarkSource:
    def __init__(self, entries: list[BenchmarkEntry]) -> None:
        self.entries = entries
        self.loaded: list[Path] = []

    def load(self, location: Path) -> list[BenchmarkEntry]:
        self.loaded.append(location)
        return list(self.entries)


class FakeDownloader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0

    def download(self) -> Path:
        self.calls += 1
        return self.path


def entry(kind: ComponentKind, name: str, score: float, samples: int = 10) -> BenchmarkEntry:
    return BenchmarkEntry(kind, name, "blender_open_data", "samples_per_minute", score, samples)


GPU = ComponentKind.GPU
CPU = ComponentKind.CPU


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot.zip"
    path.write_bytes(b"x")
    return path


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


def build(
    store: InMemoryStore, source: ScriptedBenchmarkSource, downloader: FakeDownloader | None = None
) -> ImportBenchmarks:
    return ImportBenchmarks(
        uow=store.uow,
        source=source,
        downloader=downloader or FakeDownloader(Path("unused")),
        clock=FakeClock(),
    )


async def test_imports_components_aliases_and_scores(store: InMemoryStore, snapshot: Path) -> None:
    source = ScriptedBenchmarkSource(
        [
            entry(GPU, "NVIDIA GeForce RTX 4060 Laptop GPU", 345.0, 40),
            entry(GPU, "NVIDIA GeForce RTX 4060", 480.0),
            entry(CPU, "12th Gen Intel(R) Core(TM) i5-12450H", 34.5),
        ]
    )

    report = await build(store, source)(snapshot)

    assert (report.components_added, report.aliases_added, report.benchmarks_saved) == (3, 3, 3)
    assert report.components_total == {"cpu": 1, "gpu": 2}
    found = await ListComponents(uow=store.uow)(kind=GPU)
    assert [c.component.slug for c in found] == ["rtx-4060", "rtx-4060-laptop"]  # best score first
    laptop = found[1]
    assert laptop.benchmarks[0].score == 345.0
    assert laptop.benchmarks[0].samples == 40
    aliases = {a.alias for a in store.state.component_aliases.values()}
    assert "nvidia geforce rtx 4060 laptop gpu" in aliases


async def test_laptop_and_desktop_stay_separate_components(
    store: InMemoryStore, snapshot: Path
) -> None:
    source = ScriptedBenchmarkSource(
        [entry(GPU, "RTX 4060", 480.0), entry(GPU, "RTX 4060 Laptop GPU", 345.0)]
    )

    await build(store, source)(snapshot)

    assert set(store.state.components) == {"gpu:rtx-4060", "gpu:rtx-4060-laptop"}


async def test_rerun_is_idempotent_and_updates_scores(store: InMemoryStore, snapshot: Path) -> None:
    source = ScriptedBenchmarkSource([entry(GPU, "NVIDIA GeForce RTX 4060", 480.0, 10)])
    importer = build(store, source)
    await importer(snapshot)

    again = await importer(snapshot)
    assert (again.components_added, again.aliases_added) == (0, 0)
    assert len(store.state.benchmarks) == 1

    source.entries = [
        entry(GPU, "NVIDIA GeForce RTX 4060", 500.0, 12),
        entry(GPU, "NVIDIA GeForce RTX 4070", 700.0),
    ]
    updated = await importer(snapshot)

    assert (updated.components_added, updated.aliases_added) == (1, 1)
    scores = {b.component_id: (b.score, b.samples) for b in store.state.benchmarks.values()}
    assert scores == {"gpu:rtx-4060": (500.0, 12), "gpu:rtx-4070": (700.0, 10)}


async def test_curated_component_survives_a_reimport(store: InMemoryStore, snapshot: Path) -> None:
    source = ScriptedBenchmarkSource([entry(GPU, "NVIDIA GeForce RTX 4060", 480.0)])
    importer = build(store, source)
    await importer(snapshot)
    first = store.state.components["gpu:rtx-4060"]

    source.entries = [entry(GPU, "GeForce RTX 4060 (renamed)", 490.0)]
    await importer(snapshot)

    assert store.state.components["gpu:rtx-4060"] == first
    assert len(store.state.component_aliases) == 2  # both spellings are aliases


async def test_names_without_a_model_number_are_skipped(
    store: InMemoryStore, snapshot: Path
) -> None:
    source = ScriptedBenchmarkSource(
        [entry(GPU, "AMD Radeon Graphics", 5.0), entry(GPU, "NVIDIA GPU", 5.0)]
    )

    report = await build(store, source)(snapshot)

    assert (report.skipped, report.components_added) == (2, 0)


async def test_same_slug_keeps_the_larger_sample(store: InMemoryStore, snapshot: Path) -> None:
    source = ScriptedBenchmarkSource(
        [
            entry(CPU, "Intel(R) Core(TM) i5-12450H", 30.0, 3),
            entry(CPU, "12th Gen Intel(R) Core(TM) i5-12450H", 36.0, 9),
        ]
    )

    report = await build(store, source)(snapshot)

    assert report.components_total["cpu"] == 1
    (benchmark,) = store.state.benchmarks.values()
    assert (benchmark.score, benchmark.samples) == (36.0, 9)


async def test_download_flag_uses_the_downloader(store: InMemoryStore, snapshot: Path) -> None:
    source = ScriptedBenchmarkSource([entry(GPU, "NVIDIA GeForce RTX 4060", 480.0)])
    downloader = FakeDownloader(snapshot)

    report = await build(store, source, downloader)(download=True)

    assert downloader.calls == 1
    assert source.loaded == [snapshot]
    assert report.location == str(snapshot)


async def test_needs_exactly_one_location_and_an_existing_file(
    store: InMemoryStore, snapshot: Path, tmp_path: Path
) -> None:
    importer = build(store, ScriptedBenchmarkSource([]))

    with pytest.raises(InvalidRequestError):
        await importer()
    with pytest.raises(InvalidRequestError):
        await importer(snapshot, download=True)
    with pytest.raises(InvalidRequestError, match="not found"):
        await importer(tmp_path / "missing.zip")


async def test_list_filters_by_search_and_limit(store: InMemoryStore, snapshot: Path) -> None:
    source = ScriptedBenchmarkSource(
        [
            entry(GPU, "NVIDIA GeForce RTX 4060", 480.0),
            entry(GPU, "NVIDIA GeForce RTX 4060 Laptop GPU", 345.0),
            entry(GPU, "NVIDIA GeForce RTX 3050", 200.0),
            entry(CPU, "AMD Ryzen 7 5800H with Radeon Graphics", 40.0),
        ]
    )
    await build(store, source)(snapshot)
    lister = ListComponents(uow=store.uow)

    by_text = await lister(search="rtx 4060")
    assert [c.component.slug for c in by_text] == ["rtx-4060", "rtx-4060-laptop"]
    assert len(await lister(limit=2)) == 2
    cpu_only = await lister(kind=CPU)
    assert [c.component.slug for c in cpu_only] == ["ryzen-7-5800h"]

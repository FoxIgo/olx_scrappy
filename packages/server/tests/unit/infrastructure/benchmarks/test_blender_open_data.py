"""Blender Open Data parser and aggregation against a tiny hand-made snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.benchmarks import BenchmarkEntry
from scrappy.domain.component import ComponentKind
from scrappy.infrastructure.benchmarks import (
    BLENDER_METRIC,
    BLENDER_SOURCE,
    BlenderOpenDataSource,
)
from tests.unit.infrastructure.benchmarks.snapshots import (
    many,
    sample_lines,
    write_jsonl,
    write_zip,
)


def load(path: Path, source: BlenderOpenDataSource | None = None) -> dict[str, BenchmarkEntry]:
    entries = (source or BlenderOpenDataSource()).load(path)
    return {e.device_name: e for e in entries}


def test_aggregates_to_one_median_score_per_device(tmp_path: Path) -> None:
    found = load(write_jsonl(tmp_path / "s.jsonl", sample_lines()))

    laptop = found["NVIDIA GeForce RTX 4060 Laptop GPU"]
    # runs score 3 * spm: 300, 330, 360, 3000; the median (345) ignores the outlier
    assert (laptop.kind, laptop.score, laptop.samples) == (ComponentKind.GPU, 345.0, 4)
    assert (laptop.source, laptop.metric) == (BLENDER_SOURCE, BLENDER_METRIC)
    assert found["NVIDIA GeForce RTX 4060"].score == 480.0


def test_gpu_backends_are_not_mixed_and_optix_wins_over_cuda(tmp_path: Path) -> None:
    found = load(write_jsonl(tmp_path / "s.jsonl", sample_lines()))

    # 5 CUDA runs (~187) exist, but the 4 OptiX runs are the preferred backend
    assert found["NVIDIA GeForce RTX 4060 Laptop GPU"].samples == 4


def test_spellings_of_one_part_pool_their_runs(tmp_path: Path) -> None:
    found = load(write_jsonl(tmp_path / "s.jsonl", sample_lines()))

    cpu = found["12th Gen Intel(R) Core(TM) i5-12450H"]  # the most frequent spelling
    assert cpu.kind is ComponentKind.CPU
    assert cpu.samples == 4
    assert cpu.score == 34.5  # median of 30, 33, 36, 42
    assert "Intel(R) Core(TM) i5-12450H" not in found


@pytest.mark.parametrize(
    "ignored",
    [
        "AMD Ryzen 7 5800H with Radeon Graphics",  # 2 runs < 3
        "AMD Radeon Graphics",  # generic name without a model number
        "NVIDIA GeForce RTX 3050 Ti Laptop GPU",  # only another Blender version
        "NVIDIA GeForce RTX 3090",  # multi-GPU runs
        "NVIDIA GeForce RTX 3080",  # incomplete scene set
    ],
)
def test_ignored_runs_and_devices(tmp_path: Path, ignored: str) -> None:
    found = load(write_jsonl(tmp_path / "s.jsonl", sample_lines()))

    assert ignored not in found


def test_version_and_minimum_samples_are_configurable(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "s.jsonl", sample_lines())

    old = load(path, BlenderOpenDataSource(blender_version="3.6.0"))
    assert set(old) == {"NVIDIA GeForce RTX 3050 Ti Laptop GPU"}
    few = load(path, BlenderOpenDataSource(min_samples=2))
    assert "AMD Ryzen 7 5800H with Radeon Graphics" in few


def test_reads_a_zip_and_a_directory(tmp_path: Path) -> None:
    lines = many("NVIDIA GeForce GTX 1650", "OPTIX", [10, 20, 30])
    zipped = write_zip(tmp_path / "opendata-latest.zip", lines)
    folder = tmp_path / "unpacked"
    folder.mkdir()
    write_jsonl(folder / "opendata.jsonl", lines)

    assert load(zipped)["NVIDIA GeForce GTX 1650"].score == 60.0
    assert load(folder)["NVIDIA GeForce GTX 1650"].score == 60.0


def test_a_folder_without_a_snapshot_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(InvalidRequestError):
        BlenderOpenDataSource().load(tmp_path)

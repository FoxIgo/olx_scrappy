"""Blender Open Data (https://opendata.blender.org): CPU and GPU render benchmarks.

The daily snapshot ``opendata-latest.zip`` (~100 MB, ~2 GB unpacked, CC0) holds one JSON
document per line, one line per submitted benchmark run::

    {"created_at": ..., "schema_version": "v4",
     "data": [ {"blender_version": {"label": "4.5.0"},
                "device_info": {"device_type": "OPTIX",               # CPU|CUDA|OPTIX|HIP|...
                                "compute_devices": [{"name": "NVIDIA GeForce RTX 4060 ..."}]},
                "scene": {"label": "monster"},
                "stats": {"samples_per_minute": 123.4, ...}}, ... ]}

``schema_version`` v1/v2 lines have a different shape (no ``samples_per_minute``) and are
ignored.

Aggregation (the choice is documented in ADR 0011 section 4)
------------------------------------------------------------
* One Blender version is pinned (``4.5.0`` by default): scores of different versions are not
  comparable and one version with many submissions gives the widest hardware coverage.
* A *run* is one line with all three standard scenes (monster, junkshop, classroom) for one
  device; its score is the **sum** of the scenes' ``samples_per_minute``. Incomplete runs
  and multi-GPU runs are skipped.
* A device's score is the **median** of its runs (robust to throttled laptops and outliers);
  ``samples`` is the number of runs. Devices with fewer than ``MIN_SAMPLES`` runs are dropped.
* Device names are normalized to a slug first, so differently spelled names of one part
  pool their runs. A GPU reported through several backends keeps the best-supported one
  (OptiX, HIP, oneAPI, Metal, then CUDA) with enough runs; the backends are not mixed.
"""

from __future__ import annotations

import io
import json
import statistics
import urllib.request
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.benchmarks import BenchmarkEntry
from scrappy.domain.component import ComponentKind, component_slug, is_identifying_slug

BLENDER_SOURCE = "blender_open_data"
BLENDER_METRIC = "samples_per_minute"
SNAPSHOT_URL = "https://opendata.blender.org/snapshots/opendata-latest.zip"
DEFAULT_BLENDER_VERSION = "4.5.0"
SCENES = frozenset({"monster", "junkshop", "classroom"})
MIN_SAMPLES = 3
BACKEND_PRIORITY = ("OPTIX", "HIP", "ONEAPI", "METAL", "CUDA", "OPENCL")
"""Preferred GPU backends, best first. Unknown backends rank last."""

_CHUNK = 1 << 20


class BlenderOpenDataSource:
    """``BenchmarkSource`` over a snapshot ``.zip``, an unpacked ``.jsonl`` or a directory
    holding one. Streams line by line; memory is bounded by the number of runs of the
    pinned version, not by the file size."""

    def __init__(
        self, *, blender_version: str = DEFAULT_BLENDER_VERSION, min_samples: int = MIN_SAMPLES
    ) -> None:
        self._version = blender_version
        self._min_samples = min_samples

    def load(self, location: Path) -> list[BenchmarkEntry]:
        with _open_lines(location) as lines:
            return self._aggregate(lines)

    def _aggregate(self, lines: Iterator[str]) -> list[BenchmarkEntry]:
        needle = f'"label": "{self._version}"'  # cheap prefilter before parsing
        runs: dict[tuple[ComponentKind, str, str], list[float]] = defaultdict(list)
        names: dict[tuple[ComponentKind, str], Counter[str]] = defaultdict(Counter)
        for line in lines:
            if needle not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for kind, backend, name, score in _runs_of(record, self._version):
                slug = component_slug(name, kind.value)
                if not is_identifying_slug(slug):
                    continue
                runs[(kind, slug, backend)].append(score)
                names[(kind, slug)][name] += 1
        return self._entries(runs, names)

    def _entries(
        self,
        runs: dict[tuple[ComponentKind, str, str], list[float]],
        names: dict[tuple[ComponentKind, str], Counter[str]],
    ) -> list[BenchmarkEntry]:
        chosen: dict[tuple[ComponentKind, str], tuple[str, list[float]]] = {}
        for (kind, slug, backend), scores in runs.items():
            if len(scores) < self._min_samples:
                continue
            known = chosen.get((kind, slug))
            if known is None or _backend_rank(backend) < _backend_rank(known[0]):
                chosen[(kind, slug)] = (backend, scores)
        return [
            BenchmarkEntry(
                kind=kind,
                device_name=names[(kind, slug)].most_common(1)[0][0],
                source=BLENDER_SOURCE,
                metric=BLENDER_METRIC,
                score=round(statistics.median(scores), 3),
                samples=len(scores),
            )
            for (kind, slug), (_, scores) in sorted(chosen.items(), key=lambda i: i[0])
        ]


def _backend_rank(backend: str) -> int:
    return BACKEND_PRIORITY.index(backend) if backend in BACKEND_PRIORITY else len(BACKEND_PRIORITY)


def _runs_of(record: Any, version: str) -> Iterator[tuple[ComponentKind, str, str, float]]:
    """Complete runs of ``version`` in one line: ``(kind, backend, device name, score)``."""
    data = record.get("data") if isinstance(record, dict) else None
    if not isinstance(data, list):
        return
    scenes: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for item in data:
        try:
            if item["blender_version"]["label"] != version:
                continue
            info = item["device_info"]
            backend = str(info["device_type"])
            devices = {str(d["name"]) for d in info["compute_devices"]}
            count = len(info["compute_devices"])
            spm = float(item["stats"]["samples_per_minute"])
            scene = str(item["scene"]["label"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(devices) != 1 or spm <= 0 or (backend != "CPU" and count != 1):
            continue
        scenes[(backend, next(iter(devices)))][scene] = spm
    for (backend, name), by_scene in scenes.items():
        if by_scene.keys() >= SCENES:
            kind = ComponentKind.CPU if backend == "CPU" else ComponentKind.GPU
            yield kind, backend, name, sum(by_scene[s] for s in SCENES)


@contextmanager
def _open_lines(location: Path) -> Iterator[Iterator[str]]:
    """Text lines of the snapshot at ``location`` (zip, jsonl or a directory)."""
    if location.is_dir():
        files = sorted(location.glob("*.jsonl"), key=lambda p: p.stat().st_size)
        if not files:
            raise InvalidRequestError(f"no .jsonl snapshot in {location}")
        location = files[-1]
    if zipfile.is_zipfile(location):
        with zipfile.ZipFile(location) as archive:
            members = [i for i in archive.infolist() if i.filename.endswith(".jsonl")]
            if not members:
                raise InvalidRequestError(f"no .jsonl snapshot in {location}")
            with archive.open(max(members, key=lambda i: i.file_size)) as raw:
                yield iter(io.TextIOWrapper(raw, encoding="utf-8"))
        return
    with location.open(encoding="utf-8") as handle:
        yield iter(handle)


class BlenderOpenDataDownloader:
    """Streams the latest snapshot to ``<directory>/opendata-latest.zip`` (blocking)."""

    def __init__(self, directory: Path, *, url: str = SNAPSHOT_URL, timeout: float = 60.0) -> None:
        self._target = directory / "opendata-latest.zip"
        self._url = url
        self._timeout = timeout

    def download(self) -> Path:
        self._target.parent.mkdir(parents=True, exist_ok=True)
        partial = self._target.with_name(self._target.name + ".part")
        request = urllib.request.Request(self._url, headers={"User-Agent": "olx-scrappy"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                _copy(response, partial)
            partial.replace(self._target)
        except OSError as error:
            partial.unlink(missing_ok=True)
            raise InvalidRequestError(f"download of {self._url} failed: {error}") from error
        return self._target


def _copy(source: IO[bytes], target: Path) -> None:
    with target.open("wb") as out:
        while chunk := source.read(_CHUNK):
            out.write(chunk)

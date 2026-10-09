"""Benchmark ports: where scores come from, and how a snapshot file is fetched."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scrappy.domain.component import ComponentKind


@dataclass(frozen=True, slots=True)
class BenchmarkEntry:
    """One aggregated score of one device name, as a source reports it."""

    kind: ComponentKind
    device_name: str
    source: str
    metric: str
    score: float
    samples: int


class BenchmarkSource(Protocol):
    """Reads a local snapshot and aggregates it to one score per device and metric.

    Blocking and CPU/IO heavy (the Blender snapshot is ~2 GB of JSON lines): use cases call
    it in a worker thread. Devices without a model number or with too few samples are left
    out by the adapter.
    """

    def load(self, location: Path) -> list[BenchmarkEntry]: ...


class BenchmarkDownloader(Protocol):
    """Downloads the source's latest snapshot and returns the local file (blocking)."""

    def download(self) -> Path: ...

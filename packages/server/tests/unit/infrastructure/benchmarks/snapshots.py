"""Tiny Blender Open Data snapshots for tests (never the real 100 MB file)."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable
from pathlib import Path

SCENES = ("monster", "junkshop", "classroom")


def entry(
    device: str,
    backend: str,
    scene: str,
    spm: float,
    *,
    version: str = "4.5.0",
    count: int = 1,
) -> dict[str, object]:
    return {
        "blender_version": {"label": version, "version": version},
        "device_info": {
            "device_type": backend,
            "compute_devices": [{"name": device, "type": backend}] * count,
        },
        "scene": {"label": scene},
        "stats": {"samples_per_minute": spm},
    }


def run_line(
    device: str,
    backend: str,
    spm: float,
    *,
    version: str = "4.5.0",
    scenes: Iterable[str] = SCENES,
    count: int = 1,
) -> str:
    """One submitted run: every scene scores ``spm`` (so the run's score is 3 * spm)."""
    data = [entry(device, backend, s, spm, version=version, count=count) for s in scenes]
    document = {"created_at": "2026-10-01T00:00:00+00:00", "schema_version": "v4", "data": data}
    return json.dumps(document)


def many(
    device: str,
    backend: str,
    spms: Iterable[float],
    *,
    version: str = "4.5.0",
    scenes: Iterable[str] = SCENES,
    count: int = 1,
) -> list[str]:
    scene_list = tuple(scenes)
    return [
        run_line(device, backend, spm, version=version, scenes=scene_list, count=count)
        for spm in spms
    ]


LEGACY_LINE = json.dumps(
    {"schema_version": "v1", "data": {"blender_version": {"version": "2.79"}, "scenes": []}}
)


def sample_lines() -> list[str]:
    """RTX 4060 Laptop (OptiX + a CUDA minority), a spelling variant of one CPU, a CPU with
    too few runs, and every kind of line that must be ignored."""
    lines: list[str] = []
    lines += many("NVIDIA GeForce RTX 4060 Laptop GPU", "OPTIX", [100, 110, 120, 1000])
    lines += many("NVIDIA GeForce RTX 4060 Laptop GPU", "CUDA", [60, 61, 62, 63, 64])
    lines += many("NVIDIA GeForce RTX 4060", "OPTIX", [150, 160, 170])
    lines += many("12th Gen Intel(R) Core(TM) i5-12450H", "CPU", [10, 12, 14])
    lines += many("Intel(R) Core(TM) i5-12450H", "CPU", [11])
    lines += many("AMD Ryzen 7 5800H with Radeon Graphics", "CPU", [20, 21])  # too few runs
    lines += many("AMD Radeon Graphics", "HIP", [5, 5, 5])  # no model number
    lines += many("NVIDIA GeForce RTX 3050 Ti Laptop GPU", "OPTIX", [50, 50, 50], version="3.6.0")
    lines += many("NVIDIA GeForce RTX 3090", "OPTIX", [9, 9, 9], count=2)  # multi-GPU
    lines += many("NVIDIA GeForce RTX 3080", "OPTIX", [9, 9, 9], scenes=("monster",))
    lines.append(LEGACY_LINE)
    lines.append("not json at all")
    return lines


def write_jsonl(path: Path, lines: Iterable[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_zip(path: Path, lines: Iterable[str], member: str = "opendata-test.jsonl") -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "\n".join(lines) + "\n")
        archive.writestr("README.txt", "readme")
    return path

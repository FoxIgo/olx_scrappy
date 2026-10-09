"""Configuration errors with a precise location (file and key path)."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError


class ConfigError(Exception):
    """A configuration file is missing, unreadable or invalid. The message says where."""


def format_validation_error(path: Path, error: ValidationError, *, skip: int = 0) -> str:
    lines = [f"invalid configuration in {path.name} ({path}):"]
    for item in error.errors(include_url=False):
        key = ".".join(str(part) for part in item["loc"][skip:]) or "<root>"
        lines.append(f"  {key}: {item['msg']}")
    return "\n".join(lines)

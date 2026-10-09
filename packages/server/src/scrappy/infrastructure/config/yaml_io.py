"""Shared YAML reading for the config loaders."""

from __future__ import annotations

from pathlib import Path

import yaml

from scrappy.infrastructure.config.errors import ConfigError


def read_yaml(path: Path) -> object:
    """Parse a YAML file; an empty file yields ``None``. Raises :class:`ConfigError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{path.name} ({path}) is not valid YAML: {error}") from error

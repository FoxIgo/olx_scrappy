"""``categories.yaml`` -> domain ``CategoryCatalog`` (ADR 0007).

Format::

    laptop:
      version: 1
      description: "optional, shown to the LLM"
      attributes:
        gpu: {type: string, description: "GPU model"}
        storage_type: {type: enum, values: [ssd, hdd]}
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scrappy.domain.category import (
    AttributeSpec,
    AttributeType,
    Category,
    CategoryCatalog,
    CategoryName,
)
from scrappy.domain.shared import InvalidValueError
from scrappy.infrastructure.config.errors import ConfigError, format_validation_error
from scrappy.infrastructure.config.yaml_io import read_yaml


class _AttributeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean", "enum"]
    description: str | None = None
    values: list[str] = Field(default_factory=list[str])

    @model_validator(mode="after")
    def _check_values(self) -> _AttributeModel:
        if self.type == "enum" and not self.values:
            raise ValueError("enum attributes need a non-empty 'values' list")
        if self.type != "enum" and self.values:
            raise ValueError("'values' is only allowed for enum attributes")
        if len(set(self.values)) != len(self.values):
            raise ValueError("'values' contains duplicates")
        return self


class _CategoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    description: str | None = None
    attributes: dict[str, _AttributeModel] = Field(default_factory=dict[str, _AttributeModel])


class _FileModel(BaseModel):
    categories: dict[str, _CategoryModel]


def parse_categories(data: object, *, path: Path) -> CategoryCatalog:
    """Validate parsed YAML and build the catalog. Raises :class:`ConfigError`."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} ({path}): top level must be a mapping of categories")
    try:
        parsed = _FileModel.model_validate({"categories": data})
    except ValidationError as error:
        raise ConfigError(format_validation_error(path, error, skip=1)) from error
    categories: list[Category] = []
    for name, model in parsed.categories.items():
        try:
            specs = tuple(
                AttributeSpec(
                    name=attr_name,
                    type=AttributeType(attr.type),
                    description=attr.description,
                    values=tuple(attr.values),
                )
                for attr_name, attr in model.attributes.items()
            )
            categories.append(
                Category(
                    name=CategoryName(name),
                    version=model.version,
                    attributes=specs,
                    description=model.description,
                )
            )
        except InvalidValueError as error:
            raise ConfigError(f"{path.name} ({path}): category {name!r}: {error}") from error
    return CategoryCatalog.of(categories)


def load_categories(path: Path) -> CategoryCatalog:
    return parse_categories(read_yaml(path), path=path)


class YamlCategoryProvider:
    """``CategoryProvider`` over a YAML file; reloads when the file's mtime changes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cached: tuple[int, CategoryCatalog] | None = None

    async def catalog(self) -> CategoryCatalog:
        try:
            stamp = self._path.stat().st_mtime_ns
        except OSError as error:
            raise ConfigError(f"cannot read {self._path}: {error}") from error
        if self._cached is None or self._cached[0] != stamp:
            self._cached = (stamp, load_categories(self._path))
        return self._cached[1]

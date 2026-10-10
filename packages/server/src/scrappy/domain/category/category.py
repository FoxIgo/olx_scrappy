"""User-defined categories with versioned attribute schemas (R14, ADR 0007)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import cast

from scrappy.domain.shared import InvalidValueError, validate_slug

type AttributeValue = str | int | Decimal | bool | tuple[str, ...]
"""A typed attribute value. ``number`` attributes use Decimal (exact, comparable);
``enum_list`` attributes are a non-empty tuple of enum values (an empty list is stored as null)."""


@dataclass(frozen=True, slots=True, order=True)
class CategoryName:
    value: str

    def __post_init__(self) -> None:
        validate_slug(self.value, "category name")

    def __str__(self) -> str:
        return self.value


OTHER_CATEGORY = CategoryName("other")
"""Reserved: the LLM answers ``other`` when no known category fits. It has no schema."""


class AttributeType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    ENUM_LIST = "enum_list"
    """A list of values of a fixed set, e.g. the damaged parts of a laptop."""


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    name: str
    type: AttributeType
    description: str | None = None
    values: tuple[str, ...] = ()
    """Allowed values, only for ``ENUM``."""

    def __post_init__(self) -> None:
        validate_slug(self.name, "attribute name")
        has_values = self.type in (AttributeType.ENUM, AttributeType.ENUM_LIST)
        if has_values and not self.values:
            raise InvalidValueError(f"enum attribute {self.name!r} needs values")
        if not has_values and self.values:
            raise InvalidValueError(f"only enum attributes take values ({self.name!r})")

    def coerce_element(self, raw: object) -> str:
        """One value of an ``enum_list`` attribute (a filter operand such as ``screen``)."""
        if self.type is AttributeType.ENUM_LIST and isinstance(raw, str) and raw in self.values:
            return raw
        raise InvalidValueError(f"{raw!r} is not one of {list(self.values)} for {self.name!r}")

    def coerce(self, raw: object) -> AttributeValue:
        """Validate/convert one raw value (e.g. from LLM JSON or a CLI filter).

        Accepts the natural JSON types and numeric strings; floats become Decimal through
        ``str()`` so ``15.6`` stays ``Decimal("15.6")``. Raises :class:`InvalidValueError`.
        """
        match self.type:
            case AttributeType.STRING:
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
            case AttributeType.ENUM:
                if isinstance(raw, str) and raw in self.values:
                    return raw
            case AttributeType.ENUM_LIST:
                if isinstance(raw, list | tuple):
                    items = cast("Sequence[object]", raw)
                    if all(isinstance(item, str) and item in self.values for item in items):
                        return tuple(dict.fromkeys(cast("Sequence[str]", items)))
            case AttributeType.BOOLEAN:
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, str) and raw.lower() in ("true", "false"):
                    return raw.lower() == "true"
            case AttributeType.INTEGER:
                if isinstance(raw, int) and not isinstance(raw, bool):
                    return raw
                number = _to_decimal(raw)
                if number is not None and number == number.to_integral_value():
                    return int(number)
            case AttributeType.NUMBER:
                number = _to_decimal(raw)
                if number is not None:
                    return number
        raise InvalidValueError(f"{raw!r} is not a valid {self.type.value} for {self.name!r}")


def _to_decimal(raw: object) -> Decimal | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal | int | float | str):
        try:
            number = Decimal(str(raw).strip())
        except InvalidOperation:
            return None
        return number if number.is_finite() else None
    return None


@dataclass(frozen=True, slots=True)
class Category:
    """A category and its attribute schema. Bump ``version`` on every schema change."""

    name: CategoryName
    version: int
    attributes: tuple[AttributeSpec, ...]
    description: str | None = None

    def __post_init__(self) -> None:
        if self.name == OTHER_CATEGORY:
            raise InvalidValueError("'other' is reserved and cannot be defined")
        if self.version < 1:
            raise InvalidValueError("category version must be >= 1")
        names = [spec.name for spec in self.attributes]
        if len(set(names)) != len(names):
            raise InvalidValueError(f"duplicate attribute names in category {self.name}")

    def attribute(self, name: str) -> AttributeSpec | None:
        return next((spec for spec in self.attributes if spec.name == name), None)

    def validate_attributes(self, raw: Mapping[str, object]) -> dict[str, AttributeValue | None]:
        """Validate extracted attributes against this schema.

        Every schema attribute is present in the result (``None`` = not stated). Unknown keys
        and badly typed values raise :class:`InvalidValueError` (output is then rejected).
        """
        unknown = set(raw) - {spec.name for spec in self.attributes}
        if unknown:
            raise InvalidValueError(f"unknown attributes for {self.name}: {sorted(unknown)}")
        result: dict[str, AttributeValue | None] = {}
        for spec in self.attributes:
            value = raw.get(spec.name)
            coerced = None if value is None else spec.coerce(value)
            result[spec.name] = None if coerced == () else coerced  # [] = nothing to record
        return result


def _name(category: Category) -> CategoryName:
    return category.name


@dataclass(frozen=True, slots=True)
class CategoryCatalog:
    """All known categories (config-defined now, ADR 0007). ``other`` is implicit."""

    categories: tuple[Category, ...] = field(default=())

    def __post_init__(self) -> None:
        names = [c.name for c in self.categories]
        if len(set(names)) != len(names):
            raise InvalidValueError("duplicate category names in catalog")

    @classmethod
    def of(cls, categories: Iterable[Category]) -> CategoryCatalog:
        return cls(tuple(sorted(categories, key=_name)))

    def get(self, name: CategoryName) -> Category | None:
        return next((c for c in self.categories if c.name == name), None)

    def is_known(self, name: CategoryName) -> bool:
        """True for defined categories and for the implicit ``other``."""
        return name == OTHER_CATEGORY or self.get(name) is not None

    @property
    def fingerprint(self) -> str:
        """Short stable hash of every ``name@version``; changes when any schema changes.

        Extraction input contains every category, so a catalog change is a new extraction
        context. Used to scope ExtractOffer dedup keys.
        """
        canonical = ",".join(f"{c.name}@{c.version}" for c in sorted(self.categories, key=_name))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def __iter__(self) -> Iterator[Category]:
        return iter(self.categories)

    def __len__(self) -> int:
        return len(self.categories)

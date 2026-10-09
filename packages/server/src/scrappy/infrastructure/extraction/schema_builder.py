"""JSON Schema for the LLM answer, and the validator that checks it (ADR 0007 step 3).

One call must classify AND extract, so the answer shape is::

    {"category": "<known>|other", "attributes": {...}, "notes": string|null}

Schema strategy (sent to the model): ``category`` is an enum of the known categories plus
``other``; ``attributes`` is an ``anyOf`` of one closed object per category (every attribute
required but nullable, ``additionalProperties: false``) plus an empty object for ``other``.
That sticks to the strict structured-output subset (no ``oneOf``, no discriminator keyword,
no numeric constraints) that OpenAI-compatible providers accept.

Because ``anyOf`` cannot tie ``attributes`` to ``category``, the *authority* is
:meth:`ExtractionSchema.validate`: it picks the chosen category's attribute set and checks
each value with the domain's :meth:`AttributeSpec.coerce`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from scrappy.domain.category import (
    OTHER_CATEGORY,
    AttributeSpec,
    AttributeType,
    Category,
    CategoryName,
)
from scrappy.domain.shared import InvalidValueError

SCHEMA_NAME = "offer_extraction"

_JSON_TYPES: Mapping[AttributeType, str] = {
    AttributeType.STRING: "string",
    AttributeType.INTEGER: "integer",
    AttributeType.NUMBER: "number",
    AttributeType.BOOLEAN: "boolean",
    AttributeType.ENUM: "string",
}


EMPTY_ATTRIBUTES_MESSAGE = (
    "every attribute of '{category}' is null; extract what the offer states, "
    "or answer category 'other' if it is not a {category}"
)


class InvalidAnswerError(Exception):
    """The model output does not satisfy the schema. The message is safe to show the model."""


def attribute_schema(spec: AttributeSpec) -> dict[str, Any]:
    """Nullable JSON Schema for one attribute (null = not stated)."""
    schema: dict[str, Any] = {"type": [_JSON_TYPES[spec.type], "null"]}
    if spec.type is AttributeType.ENUM:
        schema["enum"] = [*spec.values, None]
    if spec.description:
        schema["description"] = spec.description
    return schema


def category_attributes_schema(category: Category) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "title": str(category.name),
        "properties": {spec.name: attribute_schema(spec) for spec in category.attributes},
        "required": [spec.name for spec in category.attributes],
        "additionalProperties": False,
    }
    if category.description:
        schema["description"] = category.description
    return schema


_OTHER_ATTRIBUTES: dict[str, Any] = {
    "type": "object",
    "title": str(OTHER_CATEGORY),
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ValidAnswer:
    category: CategoryName
    attributes: Mapping[str, object]
    """Raw values (JSON types) of the chosen category's attributes that the model gave."""
    notes: str | None


class ExtractionSchema:
    """Response schema + validator for one set of candidate categories."""

    def __init__(self, categories: Sequence[Category]) -> None:
        self._categories = {c.name: c for c in categories}
        names = [str(c.name) for c in categories]
        branches = [category_attributes_schema(c) for c in categories] + [_OTHER_ATTRIBUTES]
        self.json_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [*names, str(OTHER_CATEGORY)],
                    "description": "The best matching category, or 'other' if none fits.",
                },
                "attributes": {
                    "anyOf": branches,
                    "description": "Attributes of the chosen category; {} for 'other'.",
                },
                "notes": {
                    "type": ["string", "null"],
                    "description": "Short remark such as 'for parts', or null.",
                },
            },
            "required": ["category", "attributes", "notes"],
            "additionalProperties": False,
        }

    @property
    def response_format(self) -> dict[str, Any]:
        """The ``response_format`` argument for strict structured output."""
        return {
            "type": "json_schema",
            "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": self.json_schema},
        }

    def validate(self, parsed: object) -> ValidAnswer:
        """Check a parsed JSON answer. Raises :class:`InvalidAnswerError`.

        * An unknown category becomes ``other`` (the model could not place the offer).
        * ``other`` carries no attributes, whatever the model wrote.
        * Unknown attribute keys are dropped; missing ones mean "not stated".
        * Values must pass the domain's ``AttributeSpec.coerce`` (``null`` is always allowed).
        * A real category with every attribute null is invalid (nothing was extracted).
        """
        if not isinstance(parsed, dict):
            raise InvalidAnswerError("the answer must be a JSON object")
        answer: dict[str, object] = {str(k): v for k, v in parsed.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        raw_category = answer.get("category")
        if not isinstance(raw_category, str):
            raise InvalidAnswerError("'category' must be a string")
        notes = answer.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise InvalidAnswerError("'notes' must be a string or null")
        notes = notes.strip() or None if isinstance(notes, str) else None

        category = self._resolve(raw_category)
        if category is None:
            return ValidAnswer(OTHER_CATEGORY, {}, notes)

        raw_attributes = answer.get("attributes")
        if raw_attributes is None:
            raw_attributes = {}
        if not isinstance(raw_attributes, dict):
            raise InvalidAnswerError("'attributes' must be an object")
        values: dict[str, object] = {str(k): v for k, v in raw_attributes.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        kept: dict[str, object] = {}
        problems: list[str] = []
        for spec in category.attributes:
            if spec.name not in values:
                continue
            value = values[spec.name]
            kept[spec.name] = value
            if value is None:
                continue
            try:
                spec.coerce(value)
            except InvalidValueError as error:
                problems.append(f"attributes.{spec.name}: {error}")
        if problems:
            raise InvalidAnswerError("; ".join(problems))
        if category.attributes and all(value is None for value in kept.values()):
            raise InvalidAnswerError(EMPTY_ATTRIBUTES_MESSAGE.format(category=category.name))
        return ValidAnswer(category.name, kept, notes)

    def _resolve(self, raw: str) -> Category | None:
        candidate = raw.strip().lower()
        for name, category in self._categories.items():
            if name.value == candidate:
                return category
        return None  # unknown or 'other'

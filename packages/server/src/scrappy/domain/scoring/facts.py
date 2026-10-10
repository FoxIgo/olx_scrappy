"""Fact names a scoring term can refer to (ADR 0011 section 5).

* A category attribute: its name (``ram_gb``, ``storage_type``, ``ram_upgradeable``).
* A component benchmark: ``<cpu|gpu>.<source>.<metric>``, the score of the CPU / GPU an
  offer is linked to (``gpu.blender_open_data.samples_per_minute``).

Facts are stored as measured; this module only names them.
"""

from __future__ import annotations

from typing import NamedTuple

from scrappy.domain.component import ComponentKind
from scrappy.domain.shared import InvalidValueError

COMPONENT_METRICS: dict[str, tuple[str, ...]] = {"blender_open_data": ("samples_per_minute",)}
"""Known benchmark ``source -> metrics``. A new benchmark source is one more entry here."""

SOURCE_ALIASES: dict[str, str] = {"blender": "blender_open_data"}
"""Short names allowed in strategy files (``gpu.blender``)."""

_KINDS = {kind.value for kind in ComponentKind}


class ComponentFactRef(NamedTuple):
    kind: ComponentKind
    source: str
    metric: str

    @property
    def key(self) -> str:
        return f"{self.kind.value}.{self.source}.{self.metric}"


def parse_component_fact(name: str) -> ComponentFactRef | None:
    """``gpu.blender`` / ``gpu.blender_open_data.samples_per_minute`` -> the canonical
    reference; ``None`` if ``name`` is a plain attribute (no dot).

    Raises :class:`InvalidValueError` when it looks like a component fact but names an
    unknown kind, source or metric. A source with a single metric may omit the metric.
    """
    parts = name.split(".")
    if len(parts) == 1:
        return None
    if parts[0] not in _KINDS:
        raise InvalidValueError(f"unknown fact {name!r}: component facts start with cpu. or gpu.")
    kind = ComponentKind(parts[0])
    if len(parts) > 3:
        raise InvalidValueError(
            f"bad component fact {name!r}: use {kind.value}.<source>[.<metric>]"
        )
    source = SOURCE_ALIASES.get(parts[1], parts[1])
    metrics = COMPONENT_METRICS.get(source)
    if metrics is None:
        known = ", ".join(sorted({*COMPONENT_METRICS, *SOURCE_ALIASES}))
        raise InvalidValueError(
            f"unknown benchmark source {parts[1]!r} in {name!r} (known: {known})"
        )
    if len(parts) == 2:
        if len(metrics) != 1:
            raise InvalidValueError(f"{name!r} needs a metric (one of: {', '.join(metrics)})")
        return ComponentFactRef(kind, source, metrics[0])
    if parts[2] not in metrics:
        raise InvalidValueError(
            f"unknown metric {parts[2]!r} for {source} in {name!r} (known: {', '.join(metrics)})"
        )
    return ComponentFactRef(kind, source, parts[2])

"""CPU/GPU components, aliases and benchmark scores (ADR 0011)."""

from scrappy.domain.component.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    Segment,
    component_id,
)
from scrappy.domain.component.resolution import (
    RESOLVER_VERSION,
    ComponentMatcher,
    OfferComponentLink,
    Resolution,
    ResolutionMethod,
)
from scrappy.domain.component.slug import alias_text, component_slug, is_identifying_slug

__all__ = [
    "RESOLVER_VERSION",
    "Benchmark",
    "Component",
    "ComponentAlias",
    "ComponentKind",
    "ComponentMatcher",
    "OfferComponentLink",
    "Resolution",
    "ResolutionMethod",
    "Segment",
    "alias_text",
    "component_id",
    "component_slug",
    "is_identifying_slug",
]

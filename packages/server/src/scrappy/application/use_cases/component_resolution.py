"""Component resolution (ADR 0011 section 3): offer CPU/GPU text -> canonical component.

``ResolveComponents`` is a reconciler in the ADR 0010 style: its backlog is a query (raw
texts without an up-to-date link), it works in chunks and each chunk is one transaction.
Unresolved texts get a link row too, so the backlog shrinks and ``status`` can list them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.components import UnresolvedText
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.component import (
    RESOLVER_VERSION,
    ComponentAlias,
    ComponentKind,
    ComponentMatcher,
    OfferComponentLink,
    alias_text,
    component_slug,
)

MOBILE_CATEGORIES = frozenset({"laptop"})
"""Offers of these categories have mobile parts: "RTX 4060" means the laptop variant."""

DEFAULT_CHUNK = 500


@dataclass(frozen=True, slots=True)
class ResolveReport:
    processed: int
    by_method: dict[str, int]
    by_kind: dict[str, int]
    remaining: int


class ResolveComponents:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        clock: Clock,
        resolver_version: int = RESOLVER_VERSION,
        chunk: int = DEFAULT_CHUNK,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._version = resolver_version
        self._chunk = chunk

    async def __call__(self, limit: int | None = None) -> ResolveReport:
        """Resolve up to ``limit`` backlog items (all when ``None``)."""
        async with self._uow() as uow:
            matcher = ComponentMatcher(
                await uow.components.list_components(), await uow.components.list_aliases()
            )
        methods: Counter[str] = Counter()
        kinds: Counter[str] = Counter()
        processed = 0
        while limit is None or processed < limit:
            size = self._chunk if limit is None else min(self._chunk, limit - processed)
            async with self._uow() as uow:
                tasks = await uow.components.resolution_backlog(self._version, limit=size)
                if not tasks:
                    break
                now = self._clock.now()
                links = [
                    OfferComponentLink(
                        offer_id=t.offer_id,
                        kind=t.kind,
                        raw_text=t.raw_text,
                        resolution=matcher.resolve(
                            t.kind,
                            t.raw_text,
                            prefer_mobile=t.category in MOBILE_CATEGORIES,
                            vram_gb=t.vram_gb,
                        ),
                        resolver_version=self._version,
                        resolved_at=now,
                    )
                    for t in tasks
                ]
                await uow.components.save_links(links)
                await uow.commit()
            processed += len(links)
            methods.update(link.resolution.method.value for link in links)
            kinds.update(link.kind.value for link in links)
        async with self._uow() as uow:
            remaining = await uow.components.count_resolution_backlog(self._version)
        return ResolveReport(processed, dict(methods), dict(kinds), remaining)


@dataclass(frozen=True, slots=True)
class ComponentResolutionReport:
    resolver_version: int
    backlog: int
    counts: dict[str, dict[str, int]] = field(default_factory=dict[str, dict[str, int]])
    """kind -> method -> links."""
    top_unresolved: list[UnresolvedText] = field(default_factory=list[UnresolvedText])


class ComponentResolutionStatus:
    def __init__(self, *, uow: UnitOfWorkFactory, resolver_version: int = RESOLVER_VERSION) -> None:
        self._uow = uow
        self._version = resolver_version

    async def __call__(self, *, top: int = 30) -> ComponentResolutionReport:
        async with self._uow() as uow:
            backlog = await uow.components.count_resolution_backlog(self._version)
            raw = await uow.components.link_counts()
            unresolved = await uow.components.top_unresolved(top)
        counts: dict[str, dict[str, int]] = {}
        for (kind, method), n in sorted(raw.items(), key=lambda item: item[0]):
            counts.setdefault(kind.value, {})[method.value] = n
        return ComponentResolutionReport(self._version, backlog, counts, unresolved)


@dataclass(frozen=True, slots=True)
class AliasAdded:
    kind: ComponentKind
    alias: str
    component_id: str
    links_marked_stale: int


class AddComponentAlias:
    """A manual alias (the human fix for a frequent unresolved text).

    Links made from a text that the alias now covers are marked stale, so the next
    ``ResolveComponents`` run re-resolves exactly those offers.
    """

    def __init__(self, *, uow: UnitOfWorkFactory) -> None:
        self._uow = uow

    async def __call__(self, kind: ComponentKind, raw_text: str, component_id: str) -> AliasAdded:
        key = alias_text(raw_text)
        if not key:
            raise InvalidRequestError("the alias text is empty")
        async with self._uow() as uow:
            component = await uow.components.get(component_id)
            if component is None:
                raise InvalidRequestError(f"unknown component {component_id!r}")
            if component.kind is not kind:
                raise InvalidRequestError(
                    f"{component_id} is a {component.kind.value}, not a {kind.value}"
                )
            await uow.components.save_alias(ComponentAlias(kind, key, component.id))
            slug = component_slug(raw_text, kind.value)
            covered = [
                text
                for text in await uow.components.linked_raw_texts(kind)
                if alias_text(text) == key or (slug and component_slug(text, kind.value) == slug)
            ]
            stale = await uow.components.mark_links_stale(kind, covered) if covered else 0
            await uow.commit()
        return AliasAdded(kind, key, component.id, stale)


__all__ = [
    "AddComponentAlias",
    "AliasAdded",
    "ComponentResolutionReport",
    "ComponentResolutionStatus",
    "ResolveComponents",
    "ResolveReport",
]

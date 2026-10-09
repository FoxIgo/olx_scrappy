"""Shared machinery of the extractor use cases: profile availability and request pacing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from scrappy.application.extraction.profile_status import ProfileStatus
from scrappy.application.ports.extraction_backends import (
    ExtractionProfile,
    ExtractionProfiles,
    ProfileHealth,
)
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory

type Sleep = Callable[[float], Awaitable[None]]
type Monotonic = Callable[[], float]


@dataclass(frozen=True, slots=True)
class Availability:
    ok: bool
    reason: str = ""


class ProfileSelector:
    """Decides which profile may work now (ADR 0010 section 8).

    A profile is available when it is not blocked (quota, persisted), has requests left
    today (``daily_limit``, persisted) and its health check passes. Health results are
    cached for ``health_ttl``; a profile that failed at runtime (connection refused, 401,
    model gone) is marked unhealthy until the next check.
    """

    def __init__(
        self,
        *,
        profiles: ExtractionProfiles,
        uow: UnitOfWorkFactory,
        clock: Clock,
        health_ttl: timedelta,
    ) -> None:
        self._profiles = profiles
        self._uow = uow
        self._clock = clock
        self._ttl = health_ttl
        self._health: dict[str, tuple[ProfileHealth, datetime]] = {}

    @property
    def profiles(self) -> ExtractionProfiles:
        return self._profiles

    def cached_health(self, name: str) -> ProfileHealth | None:
        cached = self._health.get(name)
        return None if cached is None else cached[0]

    async def health(
        self, name: str, *, refresh: bool = False, probe: bool = False
    ) -> ProfileHealth:
        now = self._clock.now()
        cached = self._health.get(name)
        if not refresh and not probe and cached is not None and now - cached[1] < self._ttl:
            return cached[0]
        profile = self._profiles.get(name)
        try:
            health = await profile.health.check(probe=probe and profile.probe)
        except Exception as error:  # adapters must not raise; be defensive anyway
            health = ProfileHealth(False, f"health check crashed: {type(error).__name__}: {error}")
        self._health[name] = (health, now)
        return health

    def mark_unhealthy(self, name: str, reason: str) -> None:
        self._health[name] = (ProfileHealth(False, reason), self._clock.now())

    async def status(self, name: str) -> ProfileStatus:
        async with self._uow() as uow:
            found = await uow.profile_status.get(name)
        return found or ProfileStatus.new(name, self._clock.now())

    async def availability(self, name: str) -> Availability:
        now = self._clock.now()
        profile = self._profiles.get(name)
        status = await self.status(name)
        if status.is_blocked(now):
            return Availability(False, f"blocked until {status.blocked_until}: {status.reason}")
        left = status.remaining_today(profile.capabilities.daily_limit, now)
        if left == 0:
            return Availability(False, "daily request limit used up")
        health = await self.health(name)
        if not health.ok:
            return Availability(False, health.detail)
        return Availability(True)

    async def block(self, profile: ExtractionProfile, reason: str, cooldown: timedelta) -> None:
        now = self._clock.now()
        async with self._uow() as uow:
            status = await uow.profile_status.get(profile.name) or ProfileStatus.new(
                profile.name, now
            )
            status.block(now + cooldown, reason, now)
            await uow.profile_status.save(status)
            await uow.commit()


class RequestPacer:
    """At most ``per_minute`` call starts per minute (evenly spaced). ``None`` = unlimited."""

    def __init__(
        self,
        per_minute: float | None,
        *,
        monotonic: Monotonic = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._interval = None if per_minute is None else 60.0 / per_minute
        self._monotonic = monotonic
        self._sleep = sleep
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._interval is None:
            return
        async with self._lock:
            now = self._monotonic()
            delay = self._next - now
            if delay > 0:
                await self._sleep(delay)
                now = self._next
            self._next = now + self._interval

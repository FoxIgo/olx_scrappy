"""Helpers shared by the job handlers."""

from __future__ import annotations

from datetime import datetime

from scrappy.application.jobs.errors import PermanentJobError
from scrappy.application.jobs.model import Job, JobId, JobPayload
from scrappy.application.ports.listing_source import (
    ListingSource,
    ListingSources,
    RecordRejection,
)
from scrappy.application.ports.system import IdGenerator
from scrappy.domain.shared import RunId, SourceId

MAX_NOTES = 20


def new_job(ids: IdGenerator, payload: JobPayload, *, run_id: RunId | None, now: datetime) -> Job:
    return Job.new(JobId(ids.new_id()), payload, run_id=run_id, now=now)


def source_for(sources: ListingSources, source_id: SourceId) -> ListingSource:
    source = sources.get(source_id)
    if source is None:
        raise PermanentJobError(f"no listing source configured for {source_id}")
    return source


def rejection_notes(rejections: tuple[RecordRejection, ...]) -> list[str]:
    notes = [
        f"rejected {r.external_id or '?'}: {r.reason}" + (f" [{r.raw_ref}]" if r.raw_ref else "")
        for r in rejections[:MAX_NOTES]
    ]
    if len(rejections) > MAX_NOTES:
        notes.append(f"... and {len(rejections) - MAX_NOTES} more rejections")
    return notes

"""Settings + sources.yaml (+ extraction.yaml) -> the application's ``PipelinePolicy``."""

from __future__ import annotations

from scrappy.application.policy import (
    DiscoveryPolicy,
    ExtractionPolicy,
    HealthPolicy,
    PipelinePolicy,
    RetryPolicy,
)
from scrappy.infrastructure.config.settings import Settings
from scrappy.infrastructure.config.sources import SourcesConfig


def build_pipeline_policy(
    settings: Settings,
    sources: SourcesConfig | None = None,
    extraction: ExtractionPolicy | None = None,
) -> PipelinePolicy:
    per_source = {
        source.id: source.health
        for source in (sources.sources.values() if sources else ())
        if source.health is not None
    }
    return PipelinePolicy(
        extraction=extraction
        or ExtractionPolicy(description_max_chars=settings.llm_max_description_chars),
        discovery=DiscoveryPolicy(max_pages=settings.pipeline_discovery_max_pages),
        retry=RetryPolicy(max_attempts=settings.pipeline_retry_max_attempts),
        health=HealthPolicy(per_source=per_source),
    )

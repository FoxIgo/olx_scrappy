"""Pure analytics over offers: summary statistics, deal detection, facet counts (ADR 0009)."""

from scrappy.domain.analytics.deals import (
    DEFAULT_MAX_RATIO,
    DEFAULT_MIN_GROUP,
    Deal,
    DealCandidate,
    DealReport,
    GroupKey,
    describe_key,
    find_deals,
    group_key,
)
from scrappy.domain.analytics.facets import (
    Bucket,
    FacetCounts,
    NumericRange,
    count_facet,
)
from scrappy.domain.analytics.stats import Summary, median, percentile, summarize

__all__ = [
    "DEFAULT_MAX_RATIO",
    "DEFAULT_MIN_GROUP",
    "Bucket",
    "Deal",
    "DealCandidate",
    "DealReport",
    "FacetCounts",
    "GroupKey",
    "NumericRange",
    "Summary",
    "count_facet",
    "describe_key",
    "find_deals",
    "group_key",
    "median",
    "percentile",
    "summarize",
]

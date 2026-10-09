"""``q overview`` and ``q schema``: orient the agent."""

from __future__ import annotations

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import AnalyticsQueries
from scrappy.application.ports.system import CategoryProvider
from scrappy.application.use_cases.analytics.common import Answer, Json
from scrappy.domain.category import Category, CategoryName
from scrappy.domain.run import ScrapeRun


def run_brief(run: ScrapeRun) -> Json:
    return {
        "id": str(run.id),
        "status": run.status.value,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def category_view(category: Category) -> Json:
    return {
        "name": str(category.name),
        "version": category.version,
        "description": category.description,
        "attributes": [
            {
                "name": spec.name,
                "type": spec.type.value,
                "values": list(spec.values),
                "description": spec.description,
            }
            for spec in category.attributes
        ],
    }


class Overview:
    def __init__(self, *, queries: AnalyticsQueries, categories: CategoryProvider) -> None:
        self._queries = queries
        self._categories = categories

    async def __call__(self) -> Answer:
        rows = await self._queries.overview()
        catalog = await self._categories.catalog()
        searches: list[Json] = []
        for counts in rows.searches:
            search = counts.search
            runs = await self._queries.recent_runs(search.name, 1)
            searches.append(
                {
                    "name": str(search.name),
                    "source": str(search.source),
                    "category": str(search.category),
                    "offers": {
                        "total": counts.offers,
                        "relevant": counts.relevant,
                        "irrelevant": counts.irrelevant,
                        "relevance_unknown": counts.unknown,
                        "extracted": counts.extracted,
                    },
                    "last_run": run_brief(runs[0]) if runs else None,
                }
            )
        data: Json = {
            "database": {"dialect": rows.dialect},
            "searches": searches,
            "categories": [
                {"name": str(c.name), "version": c.version, "attributes": len(c.attributes)}
                for c in catalog
            ],
            "totals": {
                "offers": rows.offers_total,
                "offers_extracted": rows.offers_extracted,
                "snapshots": rows.snapshots_total,
                "runs": rows.runs_total,
            },
        }
        notes: list[str] = []
        if not searches:
            notes.append("no saved searches yet; add one with `scrappy search add`")
        unextracted = rows.offers_total - rows.offers_extracted
        if unextracted:
            notes.append(f"{unextracted} offer(s) have no extraction yet")
        return Answer(data, len(searches), notes=notes)


class Schema:
    def __init__(self, *, queries: AnalyticsQueries, categories: CategoryProvider) -> None:
        self._queries = queries
        self._categories = categories

    async def __call__(
        self, *, category: CategoryName | None = None, tables: bool = False
    ) -> Answer:
        catalog = await self._categories.catalog()
        selected = list(catalog)
        if category is not None:
            found = catalog.get(category)
            if found is None:
                known = ", ".join(str(c.name) for c in catalog)
                raise InvalidRequestError(f"unknown category {category} (known: {known})")
            selected = [found]
        data: Json = {"categories": [category_view(c) for c in selected]}
        notes = [
            "attribute filters: --where 'name OP value' with OP one of = != < <= > >= ~; "
            "pseudo-fields price, title, location work everywhere",
        ]
        if tables:
            data["dialect"] = self._queries.dialect
            data["tables"] = [
                {
                    "name": table.name,
                    "columns": [
                        {
                            "name": col.name,
                            "type": col.type,
                            "nullable": col.nullable,
                            "primary_key": col.primary_key,
                        }
                        for col in table.columns
                    ],
                }
                for table in await self._queries.tables()
            ]
            notes.append(
                "tables are for `q sql`; attributes are JSON in extractions.attributes, "
                "and only the newest extractions row per offer is current"
            )
        return Answer(data, len(selected), notes=notes)

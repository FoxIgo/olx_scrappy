"""ListOffers: browse and filter stored offers (R5)."""

from __future__ import annotations

from dataclasses import replace

from scrappy.application.errors import InvalidRequestError, NotFoundError
from scrappy.application.ports.queries import OfferFilter, OfferListItem, OfferQueries
from scrappy.application.ports.system import CategoryProvider
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.domain.shared import InvalidValueError


class ListOffers:
    """Validates the filter, then delegates to the read-side port.

    Attribute predicates are checked against a category schema (the filter's ``category``,
    else the search's target category): the attribute must exist and the value is coerced
    to the attribute's type (``"16"`` -> ``16`` for an integer), so adapters receive typed
    values only. Ordering operators are only allowed on numeric attributes.
    """

    def __init__(
        self, *, uow: UnitOfWorkFactory, queries: OfferQueries, categories: CategoryProvider
    ) -> None:
        self._uow = uow
        self._queries = queries
        self._categories = categories

    async def __call__(self, query: OfferFilter) -> list[OfferListItem]:
        category_name: CategoryName | None = query.category
        if query.search is not None:
            async with self._uow() as uow:
                search = await uow.searches.get(query.search)
            if search is None:
                raise NotFoundError(f"search {query.search} not found")
            category_name = category_name or search.category
        if query.attributes:
            query = replace(query, attributes=await self._typed(query, category_name))
        return await self._queries.list_offers(query)

    async def _typed(
        self, query: OfferFilter, category_name: CategoryName | None
    ) -> tuple[AttributePredicate, ...]:
        if category_name is None:
            raise InvalidRequestError("attribute filters need a category or a search")
        category = (await self._categories.catalog()).get(category_name)
        if category is None:
            raise InvalidRequestError(f"unknown category {category_name}")
        typed: list[AttributePredicate] = []
        for predicate in query.attributes:
            spec = category.attribute(predicate.attribute)
            if spec is None:
                raise InvalidRequestError(
                    f"category {category_name} has no attribute {predicate.attribute!r}"
                )
            try:
                value = spec.coerce(predicate.value)
            except InvalidValueError as error:
                raise InvalidRequestError(str(error)) from error
            ordering = predicate.op in (Comparison.LT, Comparison.LE, Comparison.GT, Comparison.GE)
            if ordering and isinstance(value, bool | str):
                raise InvalidRequestError(
                    f"{predicate.op.value} needs a numeric attribute ({predicate.attribute!r})"
                )
            if predicate.op is Comparison.CONTAINS and not isinstance(value, str):
                raise InvalidRequestError(f"~ needs a text attribute ({predicate.attribute!r})")
            typed.append(AttributePredicate(predicate.attribute, predicate.op, value))
        return tuple(typed)

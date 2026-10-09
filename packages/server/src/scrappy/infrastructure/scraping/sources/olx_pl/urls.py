"""URL handling for olx.pl: browser search URL -> internal API request, cursors, detail URLs.

Mapping table (browser URL -> ``/api/v1/offers/`` query), see the spike (section 3):

====================================  =========================================
Browser URL                           API query parameter
====================================  =========================================
path ``/oferty/q-gtx-1650-laptop/``   ``query=gtx 1650 laptop`` (dashes -> spaces)
``search[order]=X``                   ``sort_by=X``
``search[filter_*]=V``                ``filter_*=V`` (also ``[0]`` array suffixes)
``page=N`` (1-based)                  ``offset=(N-1)*limit`` and ``limit``
any other ``search[x]=V`` / ``x=V``   ``x=V`` passed through, reported as a warning
category path ``/elektronika/.../``   not translated: page 1 is fetched as **HTML** and the
                                      site's own ``links.next`` (API URL with ``category_id``,
                                      query and filters) is the cursor of page 2+
region-only path ``/oferty/krakow/``  not supported -> :class:`UnsupportedSearchUrl`
====================================  =========================================

The ``PageRef.cursor`` is one of: the saved browser search URL (first page; ``/oferty/q-...``
is translated to an API request, a category path is fetched as HTML, see
:func:`classify_cursor`), or the absolute API URL taken from ``links.next.href`` (every
later page). Cursors are plain URLs, so old stored cursors keep their meaning.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from scrappy.application.ports.listing_source import PageRef

API_HOST = "www.olx.pl"
API_OFFERS_URL = f"https://{API_HOST}/api/v1/offers/"
SITE_HOSTS = frozenset({"www.olx.pl", "olx.pl"})

DEFAULT_PAGE_SIZE = 40
MAX_PAGE_SIZE = 50
"""``limit`` accepted by the API is 0..50 (400 above)."""
MAX_OFFSET = 1000
"""``offset`` accepted by the API is 0..1000 (400 above): the ~1000 result cap."""

_CATEGORY_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_CATEGORY_DEPTH = 4
_RESERVED_FIRST_SEGMENTS = frozenset({"oferty", "d", "api", "i2", "mojolx", "obserwowane"})
"""Non-category top-level paths (offer pages, API, the generic ``/oferty/`` search, account)."""

_SEARCH_KEY = re.compile(r"^search\[(?P<name>[^\]]+)\](?P<rest>.*)$")


class UnsupportedSearchUrl(ValueError):
    """The saved search URL cannot be translated to an API request (yet)."""


class CursorKind(enum.Enum):
    API = "api"
    """Absolute ``/api/v1/offers`` URL (``links.next``): GET it directly."""
    TRANSLATED = "translated"
    """``/oferty/q-<query>/`` browser URL: translated to an API request."""
    CATEGORY_HTML = "category_html"
    """Category path browser URL: fetched as an HTML page, parsed from the embedded state."""


@dataclass(frozen=True, slots=True)
class SearchRequest:
    url: str
    """Absolute API URL to GET."""
    offset: int
    warnings: tuple[str, ...] = ()
    """Search-URL params that were not recognised and were passed through unchanged."""


def _slug_to_query(slug: str) -> str:
    return unquote(slug[len("q-") :]).replace("-", " ").replace("+", " ").strip()


def is_category_path(segments: list[str]) -> bool:
    """``/<cat>[/<sub>...]/[q-<slug>/]``: 1..4 category segments, optional trailing ``q-`` slug."""
    if segments and segments[-1].startswith("q-"):
        if len(segments[-1]) <= 2:
            return False
        segments = segments[:-1]
    if not 1 <= len(segments) <= MAX_CATEGORY_DEPTH:
        return False
    if segments[0] in _RESERVED_FIRST_SEGMENTS:
        return False
    return all(_CATEGORY_SEGMENT.match(s) for s in segments)


def classify_cursor(cursor: str) -> CursorKind:
    """How a cursor must be fetched. Raises :class:`UnsupportedSearchUrl` if it cannot be."""
    parts = urlsplit(cursor.strip())
    if parts.path.startswith("/api/v1/offers"):
        return CursorKind.API
    _check_site_host(parts.hostname or "", cursor)
    segments = [s for s in unquote(parts.path).split("/") if s]
    if segments and segments[0] == "oferty":
        return CursorKind.TRANSLATED
    if is_category_path(segments):
        return CursorKind.CATEGORY_HTML
    raise UnsupportedSearchUrl(
        f"unsupported olx.pl search URL {cursor!r}: expected /oferty/q-<query>/ or a category "
        "path like /elektronika/komputery/laptopy/[q-<query>/] (region paths are not supported)"
    )


def _check_site_host(host: str, url: str) -> None:
    if host not in SITE_HOSTS:
        raise UnsupportedSearchUrl(f"not an olx.pl URL: {url!r}")


def translate_search_url(
    search_url: str, *, page_size: int = DEFAULT_PAGE_SIZE
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Browser search URL -> (API query params, warnings). Params include offset and limit."""
    parts = urlsplit(search_url.strip())
    _check_site_host(parts.hostname or "", search_url)
    segments = [s for s in parts.path.split("/") if s]
    if not segments or segments[0] != "oferty" or len(segments) > 2:
        raise UnsupportedSearchUrl(
            f"unsupported olx.pl search URL {search_url!r}: expected /oferty/q-<query>/ here "
            "(category paths are fetched as HTML, see classify_cursor)"
        )
    params: dict[str, str] = {}
    warnings: list[str] = []
    if len(segments) == 2:
        if not segments[1].startswith("q-") or len(segments[1]) <= 2:
            raise UnsupportedSearchUrl(
                f"unsupported olx.pl path segment {segments[1]!r} in {search_url!r}: "
                "expected q-<query> (region paths are not supported)"
            )
        params["query"] = _slug_to_query(segments[1])

    page = 1
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if key == "page":
            if value.isdigit() and int(value) >= 1:
                page = int(value)
            else:
                warnings.append(f"ignored invalid page={value!r}")
            continue
        match = _SEARCH_KEY.match(key)
        if match is None:
            params[key] = value
            warnings.append(f"unknown query param {key!r} passed through")
            continue
        name = match["name"] + match["rest"]
        if name == "order":
            params["sort_by"] = value
        elif name.startswith("filter_"):
            params[name] = value
        else:
            params[name] = value
            warnings.append(f"unknown search param {key!r} passed through as {name!r}")

    params["offset"] = str((page - 1) * page_size)
    params["limit"] = str(page_size)
    return params, tuple(warnings)


def _query_string(params: dict[str, str]) -> str:
    return urlencode(params, quote_via=quote, safe=":")


def build_search_request(cursor: str, page_size: int = DEFAULT_PAGE_SIZE) -> SearchRequest:
    """Turn a ``PageRef.cursor`` (browser search URL or API ``next`` URL) into an API request."""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be 1..{MAX_PAGE_SIZE}")
    parts = urlsplit(cursor.strip())
    if parts.path.startswith("/api/v1/offers"):
        if parts.scheme != "https" or parts.hostname not in SITE_HOSTS:
            raise UnsupportedSearchUrl(f"refusing to follow a non-olx.pl API cursor: {cursor!r}")
        offset = dict(parse_qsl(parts.query)).get("offset", "0")
        return SearchRequest(cursor, int(offset) if offset.isdigit() else 0)
    params, warnings = translate_search_url(cursor, page_size=page_size)
    return SearchRequest(
        f"{API_OFFERS_URL}?{_query_string(params)}", int(params["offset"]), warnings
    )


def first_page_ref(search_url: str) -> PageRef:
    """PageRef for page 1 of a saved search; validates that the URL is translatable."""
    kind = classify_cursor(search_url)
    if kind is CursorKind.API:
        raise UnsupportedSearchUrl(f"a saved search must be a browser URL, not API: {search_url!r}")
    if kind is CursorKind.TRANSLATED:
        translate_search_url(search_url)
    return PageRef.first(search_url)


def next_page_ref(next_href: str, current: PageRef) -> PageRef | None:
    """PageRef for the page behind ``links.next.href``, or ``None`` if it is not followable."""
    parts = urlsplit(next_href)
    if (
        parts.scheme != "https"
        or parts.hostname not in SITE_HOSTS
        or not parts.path.startswith("/api/v1/offers")
    ):
        return None
    return PageRef(next_href, current.number + 1)


def offset_of(url: str) -> int | None:
    value = dict(parse_qsl(urlsplit(url).query)).get("offset")
    return int(value) if value and value.isdigit() else None


def offer_api_url(external_id: str) -> str:
    return f"{API_OFFERS_URL}{quote(external_id, safe='')}/"

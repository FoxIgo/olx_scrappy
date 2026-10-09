# OLX.pl extraction spike

Date: 2026-10-09. Related: ADR 0004 (sections 6, 8), ADR 0005. Fixtures: `docs/research/olx_pl_fixtures/`.
Spike scripts lived in `%TEMP%\olx_spike` (not in the repo). About 23 requests in total, at least 3 s apart.

## 1. Summary / recommendation

- **Plain `httpx` is blocked.** Every request (HTML and API) returned `403` from CloudFront
  (`server: CloudFront`, a small HTML4 "ERROR: The request could not be satisfied" page, `x-cache: Error from cloudfront`).
  This happened with a normal Chrome User-Agent and Accept headers. The cause is most likely TLS/HTTP2 fingerprinting
  at the edge, not the headers. I tried only 2 plain httpx requests and did not try to work around it with headers or
  anything else (rule: no bypass).
- **`curl_cffi` with `impersonate="chrome"` gets 200 on everything** (HTML and API). It sends a browser-like TLS
  handshake and no cookies. There was no challenge page and no CAPTCHA. This was the only place I used the
  library, as the task's step 4 asked. Whether it counts as "stealth" is a policy call for the project owner.
  The engine needs to be `curl_cffi` (or a real browser), and ADR 0004's default "httpx" engine will not work for olx.pl.
- **Recommended extraction: the internal JSON API (ADR 0004 strategy 2) for both discovery and enrichment.**
  - `GET https://www.olx.pl/api/v1/offers/?offset=&limit=&query=...` for search. It needs no auth and no cookies.
  - `GET https://www.olx.pl/api/v1/offers/{id}/` for the detail.
  - The search API items carry the full description and are **byte-identical in content to the detail API payload**
    (verified on one 3925-char description: same `description`, same `params`; the only key difference seen was
    `protect_phone`, present on some items only). So discovery already yields everything the
    enrichment needs; the detail call is only needed to refresh one known offer or to check for removal.
  - It is a clean, typed JSON with a versioned path (`/api/v1/`), much more stable than HTML, and about 300 KB per 48 offers
    instead of ~4 MB of HTML.
- **Fallback: embedded state in HTML** (`window.__PRERENDERED_STATE__`). It has the same data with camelCase keys
  and a different shape. Use it if the API starts demanding auth or gets blocked. HTML selectors are the last resort
  (cards are `div[data-cy="l-card"]`, but the CSS classes are emotion hashes and unstable).
- JSON-LD is **not useful**: the search page only has `WebPage` and `BreadcrumbList`, the detail page has a thin
  schema.org `Product` (name, description, images without size, price, currency, availability, city, sku). No dates,
  params or seller.

## 2. Search results page (HTML)

`GET https://www.olx.pl/oferty/q-gtx-1650-laptop/?search%5Border%5D=filter_float_price:asc&search%5Bfilter_float_price:from%5D=600&search%5Bfilter_float_price:to%5D=1400`
(via curl_cffi) returned `200`, 3.9 MB, `text/html; charset=utf-8`.

- Offers are **server-rendered**: 48 `div[data-cy="l-card"][id="<offerId>"]` elements.
- **No `__NEXT_DATA__`.** State lives in `<script id="olx-init-config">` as several `window.X = "<json string>"`
  assignments: `__INIT_CONFIG__`, `__FEATURE_FLAGS__`, `__JSON_FEATURE_FLAGS__`, `__PRERENDERED_STATE__`, `__TAURUS__`,
  `__PAGE_TRANSLATIONS__`. **Each value is a JSON string literal of a JSON document (double-encoded):**
  `json.loads(json.loads(literal))`. `__PRERENDERED_STATE__` is the only one that matters (about 3.3 MB).
- Structure of the state: `{listing: {listing: {...}, friendlyLinks, similarSearches, seo, breadcrumbs, filters, filteredCounts, stats, ...}, categories}`.
  - `listing.listing.ads[]`: the offers (48 = 40 organic + 8 promoted/top ads inserted on page 1; see section 5).
  - `listing.listing.totalElements` (173), `visibleElements` (173), `totalPages` (5), `pageNumber` (0-based),
    `links.{first,self,next}` (these point to the **API** URL, `https://www.olx.pl/api/v1/offers?offset=40&limit=40&query=...`; `previous` appears on later pages),
    `params` (the API params derived from the page URL), `requestParams` (`page`, `categoryPath`, `query`, raw `search[...]` params),
    `metaData.{searchId, promoted[], facets, filters, searchReason}`.
- Ad fields (camelCase) for the search page ads are listed in the mapping table. It also includes `photos` (full-size URLs) and `photosSet`
  (srcset strings), `location.{cityName,cityId,regionName,regionId,districtName,pathName}`, `user.{id,uuid,name,created,sellerType,...}`,
  `contact.{name,phone,chat,...}` (phone is only a boolean), `isBusiness`, `delivery`, `safedeal`.
- Page URL pagination: `?page=N` (1-based). `?page=2` returned `pageNumber=1`, 40 ads. A page beyond the end (`?page=9`
  with 5 pages) still returns **200** with `ads: []`, `pageNumber=8`, `totalPages=5`. So an empty `ads` list marks the end, not a 404.
- The embedded state is exactly the API response reshaped, but ads are not a verbatim copy of API data
  (key names differ, see section 6).

## 3. Internal JSON API

`https://www.olx.pl/api/v1/offers/` works **without auth, cookies or special headers** (only through curl_cffi,
see section 1). Responses: `{"data": [...], "metadata": {...}, "links": {...}}`.

### Param mapping (browser URL to API)

| Browser URL | API param |
|---|---|
| path `/oferty/q-gtx-1650-laptop/` (query slug) | `query=gtx 1650 laptop` (the human query; the slug has `-` for spaces, so prefer reading `listing.params`/`requestParams.query` from the HTML or take it from the user's saved search) |
| `search[order]=filter_float_price:asc` | `sort_by=filter_float_price:asc` |
| `search[filter_float_price:from]=600` | `filter_float_price:from=600` |
| `search[filter_float_price:to]=1400` | `filter_float_price:to=1400` |
| `page=N` (1-based) | `offset=(N-1)*limit`, `limit=40` (the site default) |
| category path (`/elektronika/komputery/laptopy/`) | `category_id=<id>` (from category tree in `categories.list`; **not verified in this spike**) |
| region/city path segments | `region_id`, `city_id`, `distance` (**not verified**) |
| other `search[filter_enum_xxx][0]=yyy`, `search[filter_float_xxx:from]` | very likely `filter_enum_xxx[0]=yyy`, `filter_float_xxx:from` (**not verified**, but the `filter_float_price:*` mapping is confirmed by the site's own `links.next` and `listing.params`) |

The cleanest way to be sure for any URL is: fetch page 1 HTML once, read `listing.listing.params` (the API params the site derived) and
`links.first`, then reuse them. That avoids reimplementing the mapping. A saved search could store the browser URL and
let the recipe compute API params by parsing `search[...]` keys (strip `search[` and `]`, `order` becomes `sort_by`).

The API URLs used (all returned 200 or the stated error):
`/api/v1/offers/?offset=0&limit=40&query=gtx%201650%20laptop&sort_by=filter_float_price:asc&filter_float_price:from=600&filter_float_price:to=1400`.
`links.next.href` is a ready-to-follow URL (absolute, normalized, includes all filters). Prefer following `links.next` over building offsets.

### Limits

- `limit`: **0..50** (100 gave `400 {"error": {"status":400, "title":"Invalid request", "validation":[{"field":"limit","title":"This value should be between 0 and 50."}]}}`).
  Default and site use is 40. Fixture: `api_error_limit_over_50_400.json`.
- `offset`: **0..1000** (`offset=10000` gave `400 ... [offset: This value should be between 0 and 1000.]`). `offset=1000` itself still returned data.
- `metadata.total_elements` is **capped at 1000** for broad queries (observed: query `laptop` gave `total_elements: 1000`,
  `visible_total_count: 113841`). For narrow queries it is the real count (173).
- `links.next` disappears when the cap or the end is reached (it was absent at `offset=960&limit=40` for the broad query,
  and absent on the last page of the narrow query).
- Past the end: `200` with `data: []` (fixture `api_search_beyond_end_empty.json`; note the extra `metadata.search_suggestion` of type `extended_s2v`).
- So a single search can reach at most ~1000 organic results (the historical "25 pages" cap holds: 25 x 40 = 1000).
  To cover more, split by price range, category or region, or sort by newest and stop at the first already-known offer.

### Response shape (search item == detail item)

Keys: `id, url, title, last_refresh_time, created_time, valid_to_time, pushup_time, omnibus_pushup_time, description, promotion{highlighted,urgent,top_ad,options[],...}, params[], key_params[], business, user{...}, status, contact{name,phone,chat,negotiation,courier}, map{lat,lon,radius,zoom,show_detailed}, location{city{id,name,normalized_name},region{...}}, photos[{id,filename,width,height,link}], partner, category{id,type}, delivery, safedeal, shop, isGpsrAvailable, offer_type, protect_phone`.
(`protect_phone` is present on some items only.)

- **Price is a `params[]` entry with `key == "price"`**: `value: {value, type, currency, negotiable, arranged, budget, label, previous_value, previous_label, converted_*}`.
  There is **no top-level price field** in the API (unlike the embedded state, which has `price.regularPrice.{value,currencyCode,negotiable}` plus `price.free/exchange/budget`).
  Non-money prices exist: `type: "exchange"` has `value: 0`, `label: "Zamienię"`; there are also "free" (`Za darmo`) and "budget" cases.
  So the mapper must check `value.type` (or `label`), not just `value`. Seen in the data: `price`, `exchange`.
- `params[].value` is `{key, label}` for `select` (key is the normalized slug, label is the Polish display text),
  `{key, label}` also for `input` (e.g. `bdo`). Param types seen: `price`, `select`, `input`.
- **Description is text with `<br />` line breaks plus `\n`** (OLX sanitizes HTML down to `<br />`). Not full HTML. Max seen 4354 chars.
  Sellers sometimes obfuscate phone numbers in text (`6+6+0+2+...`, `508 /|\ 904 /|\ 407`); the fixtures redact phone-like digit runs (none were found in the saved ones).
- `photos[].link` is a template with `{width}x{height}` placeholders: `https://ireland.apollo.olxcdn.com:443/v1/files/<filename>/image;s={width}x{height}`.
- Search results mix promoted offers in: `metadata.promoted` lists the indexes of promoted items inside `data`, `metadata.source.{promoted,organic}`
  split indexes. Promoted offers may be **duplicated** within one page (46 unique ids among 48 items on page 1: two ids appeared twice,
  once as promoted and once as organic or twice as promoted) and may reappear on other pages (1 of 40 on page 2 overlapped page 1).
  Always dedupe by `id`.
- All offers seen had `status: "active"`.

## 4. Offer detail page

`GET https://www.olx.pl/d/oferta/<slug>-CID99-ID<code>.html` via curl_cffi returned 200, 2.0 MB.

- `window.__PRERENDERED_STATE__` has `{ad: {ad: {...}, fragments, breadcrumbs, userAgent}, categories}`.
  `ad.ad` has the same camelCase shape as a search ad (plus the full description and photo list) and **no `contact.phone` number**.
- Description is also rendered in `div[data-cy="ad_description"]` (inner `div` with plain text, `<br>` converted to markup by React).
- JSON-LD (`Product`): `name, image[] (no size suffix), url, description, category (URL), sku (== offer id), offers{availability, priceCurrency, price, areaServed.name, itemCondition}`.
  Availability is `https://schema.org/InStock` for an active offer (what it is for a removed one is **unknown**, I did not find a removed offer).
- Seller info: `ad.ad.user` has `id, uuid, name, created, lastSeen, sellerType, company_name, about, logo, photo, b2c_business_page`. No phone number.
  The seller is identified by `user.id` (numeric) and `user.uuid`.
- The detail API (`/api/v1/offers/{id}/`) gives the same fields; 4 KB vs 2 MB for HTML. **Use the API.**

## 5. Missing / removed / invalid offers (FetchOutcome)

| Case | Request | Status | Markers |
|---|---|---|---|
| API, nonexistent numeric id | `GET /api/v1/offers/1/` | **404** | JSON `{"error":{"status":404,"detail":"Ad not found."}}` (fixture `api_offer_not_found_404.json`) |
| API, malformed id | `GET /api/v1/offers/abc/` | **404** | content-type `application/x-json`, `{"id":null,"result":null,"error":{"request":{"code":"request json error","message":"unknown method or incorrect parameters"}}}` (legacy-style error) |
| HTML, bogus offer URL | `GET /d/oferta/nie-istnieje-test-CID99-IDzzzzzz.html` | **404** | A full 1.8 MB SPA page: `<title>Ogłoszenia - Sprzedam, kupię na OLX.pl</title>`, `__PRERENDERED_STATE__ = {"ad": {"statusCode": 404}, "categories": ...}`, no `ad_description`, no JSON-LD (fixture `offer_not_found_404.html`). |
| CloudFront block | any, plain httpx | **403** | `server: CloudFront`, `x-cache: Error from cloudfront`, body `<TITLE>ERROR: The request could not be satisfied</TITLE>`, "Generated by cloudfront" |

**Not observed** (open): a real offer that existed and was later sold/expired/removed. I did not have one and did not want to
burn the request budget. OLX typically either keeps the page with `status` other than `active` (`moderated`, `removed_by_user`, `limited`, `unpaid`, ...)
or returns 404/410. Guesses for the recipe, to verify against a real one:
- API `data.status != "active"` (or `isActive == false`) maps to GONE with the raw status stored.
- API/HTML `404` with `Ad not found.` / `ad.statusCode == 404` maps to NOT_FOUND (could well be GONE for a previously known id; the *domain*
  decides: an id that we saw before and now 404s is GONE, an id never seen is NOT_FOUND).
- JSON-LD `availability` other than `InStock` is a secondary signal.

Suggested `classify()` for the OLX recipe:
1. Status 403/429, or body starts with `<!DOCTYPE HTML PUBLIC` containing `Generated by cloudfront` or `The request could not be satisfied`: **BLOCKED**.
2. Status 404 with API JSON `error.detail == "Ad not found."` or HTML state `ad.statusCode == 404`: **NOT_FOUND** (promote to GONE in the application layer if the offer was known).
3. Status 200 with `data.status` in a non-active set (or `isActive` false): **GONE**.
4. Status 5xx or network error: **TRANSIENT**.
5. Status 200, JSON with `data[]` / `data.id`: **OK**. Treat a 200 HTML page lacking `__PRERENDERED_STATE__` as BLOCKED/challenge (not seen, but that is where a challenge would show up).
Search page with `data: []` is OK (empty result), not an error.

## 6. Field mapping

Primary source is the API (`data[]` for search, `data` for detail). The second column is the embedded state for the HTML fallback.

| Our concept | API path | Embedded state path (`ads[]` / `ad.ad`) | Notes |
|---|---|---|---|
| external_id | `id` | `id` | int, e.g. `1098526767`. URL has `ID1cliZF` (a base-36-like code, not the numeric id); use the numeric id |
| url | `url` | `url` (also `urlPath`) | absolute, canonical |
| title | `title` | `title` | |
| price amount | `params[key=="price"].value.value` | `price.regularPrice.value` | number; 0 for exchange/free, check `type` |
| currency | `params[key=="price"].value.currency` | `price.regularPrice.currencyCode` | `PLN` |
| negotiable | `params[key=="price"].value.negotiable` | `price.regularPrice.negotiable` | |
| price kind | `params[key=="price"].value.type` / `.label` / `.budget` / `.arranged` | `price.free`, `price.exchange`, `price.budget` | `price` / `exchange` (`Zamienię`) / free |
| price label | `params[key=="price"].value.label` | `price.displayValue` | "1 300 zł", for display only |
| location | `location.city.{id,name,normalized_name}`, `location.region.{id,name,normalized_name}` | `location.{cityName,cityId,regionName,regionId,districtName,pathName}` | API has no `pathName` and no district; `map.{lat,lon,radius}` is a fuzzy point (`radius` 1 or more, `show_detailed: false`) |
| posted_at | `created_time` | `createdTime` | ISO 8601 with offset `+02:00` |
| refreshed_at | `last_refresh_time` (also `pushup_time`, `omnibus_pushup_time`) | `lastRefreshTime` (`pushupTime`) | `last_refresh_time` is the user-visible "refreshed"; `pushup_time` can be null |
| valid_to | `valid_to_time` | `validToTime` | expiry date |
| promoted | `promotion.top_ad` / `promotion.highlighted` / `promotion.urgent`; position in `metadata.promoted[]` | `isPromoted`, `isHighlighted`, `promotion.*` | `top_ad` is the real "promoted/featured" slot; `isPromoted` in the state is true only when promoted. Do not use promoted as organic ranking |
| params | `params[]` : `{key, name, type, value{key,label}}` | `params[]`: `{key, name, type, value (label), normalizedValue}` | skip `key=="price"`. Shapes differ: API `value.label`/`value.key`, state `value`/`normalizedValue` |
| condition | `params[key=="state"].value.key` (`used`, `new`) | `itemCondition` | |
| description | `description` | `description` | text with `<br />` + `\n`; normalize (`<br />` to `\n`, unescape entities) |
| images | `photos[].link` (replace `{width}x{height}`, e.g. `1000x700`; or use `;s=` with original `width`x`height`) | `photos[]` (full URLs with `;s=WxH`) | thumbnail for the list: state `photosSet[0]` is a 389x272 / 516x361 / 1000x700 srcset |
| seller ref | `user.id` (numeric), `user.uuid`, `user.name`, `business`, `user.seller_type`, `user.company_name`, `user.created` | `user.id`, `user.uuid`, `user.name`, `isBusiness`, `user.sellerType`, `user.created` | seller page URL not in data; store `user.id`. `user.name` is the public display name only |
| status | `status` (`active` seen) | `status`, `isActive` | map non-active to GONE (to confirm) |
| category | `category.id`, `category.type` | `category.{id,type}` | no label in API; label via `categories` tree or breadcrumbs |
| delivery | `delivery.rock.{active,mode}` | `delivery.rock` | OLX delivery |
| offer type | `offer_type` (`offer`) | | |
| total results | `metadata.total_elements` (cap 1000), `metadata.visible_total_count` | `listing.listing.totalElements/visibleElements/totalPages` | |
| next page | `links.next.href` (absent on last page) | `listing.listing.links.next` | |

Seller phone: only `contact.phone: true/false` (a boolean) is exposed; the number needs an authenticated/clicked reveal call. Not collected.

## 7. Pagination approach

1. Build `limit=40` (or up to 50), `offset=0` from the saved search; call it.
2. Follow `links.next.href` until it is absent or `data` is empty. Cap at 25 pages / `offset <= 1000`.
3. Dedupe by `id` within a run (promoted items repeat). Remember `metadata.promoted` indexes to mark the promoted flag (it is also in each item).
4. Sort by newest (`sort_by=created_at:desc`; **not verified in this spike**, value is the site's "Najnowsze" sort, check `listing.params` after choosing it on the page)
   and stop paginating once a whole page is already known, to keep requests low.
5. If `total_elements` hits 1000 the query is too broad: split it (price ranges, region, category) instead of hoping to reach everything.
6. Politeness: 1 request per 3+ s, jitter, backoff on 429/403. The `/api/v1/` endpoint is behind the same CloudFront as the site.

## 8. curl_cffi vs httpx

| | httpx | curl_cffi impersonate="chrome" |
|---|---|---|
| Search HTML | 403 CloudFront | 200 |
| API search | 403 CloudFront | 200 |
| API detail / detail HTML / 404 pages | not tried (already blocked twice) | 200 / 200 / 404 as expected |

Same URL, same Accept-Language; only the TLS/HTTP fingerprint differs. I did not test curl_cffi without impersonation or other headers.

## 9. Risks and open issues

- **Engine requirement**: plain httpx cannot be the olx engine. Needs curl_cffi impersonation (or a real browser later). A CloudFront
  rule can change, and the block may also become IP/rate based. The BLOCKED classification above must be in place before the first run.
- The API is **internal and undocumented**; the site's own frontend uses it, so it should be stable but may change or gain auth/anti-bot
  tokens without notice. Keep the HTML embedded-state parser as a tested fallback (fixtures included) and add a canary: parse a golden fixture in CI and run a daily live probe (ADR 0005).
- Embedded state is double-encoded JSON inside a big inline script (3 to 4 MB per page). Parsing needs to find `window.__PRERENDERED_STATE__=` in `#olx-init-config`.
- Price lives in `params[]` in the API; fragile if OLX reorders or renames. Always look it up by `key == "price"`. Price kinds (exchange/free/budget) need handling.
- Descriptions contain `<br />` and sometimes obfuscated phone numbers or promo text. Store raw plus a normalized copy.
- Promoted duplicates, page overlaps, and shifting results while paginating (new offers push others down). Dedupe and treat a page as a snapshot.
- Not verified: the real "sold/removed" offer response, category and region filter param names in the API, newest-first sort value, whether the API
  responds to `If-None-Match`/ETag (would save bandwidth), rate limits (no 429 seen in ~23 requests), and the `limit=50` exact behavior (only the validation message was seen).
- `valid_to_time` (expiry) is available and could drive "expiring soon" logic without re-fetching.
- Legal/ToS: OLX terms restrict automated collection; this is a personal-use tool, keep the request rate low.

## 10. Fixtures (`docs/research/olx_pl_fixtures/`)

| File | Content |
|---|---|
| `search_results.html` | Search results page reduced to: JSON-LD, `#olx-init-config` with `__PRERENDERED_STATE__` (5 of 48 ads, 3 photos each, trimmed filters/facets), 2 real `l-card` divs without emotion `<style>` blocks, the pagination block |
| `api_search_page1.json` | First API page (offset 0, limit 40), first 5 items; totals and links untouched (`total_elements: 173`, `links.next`) |
| `api_search_last_page_no_next.json` | Last page (offset 160), last 2 items, `links` has no `next` |
| `api_search_beyond_end_empty.json` | `data: []` past the end |
| `offer_detail.html` | Detail page reduced to JSON-LD, state `ad.ad`, description block |
| `api_offer_detail.json` | `/api/v1/offers/1098526767/` |
| `api_offer_detail_long_description.json` | Detail with a long `<br />` description (3925 chars) |
| `offer_not_found_404.html` | HTML 404 (`ad.statusCode: 404`), trimmed (original was 1.8 MB with HTTP 404) |
| `api_offer_not_found_404.json`, `api_offer_bad_id_404.json` | API error bodies (HTTP 404) |
| `api_error_limit_over_50_400.json`, `api_error_offset_over_1000_400.json` | API validation errors (HTTP 400) |

No CloudFront 403 body is saved as a fixture; it is the small HTML4 page described in section 5 (starts with `<!DOCTYPE HTML PUBLIC`, contains "Generated by cloudfront").
Seller names and ids in the fixtures are the public listing data; no phone numbers were present in the API/state.

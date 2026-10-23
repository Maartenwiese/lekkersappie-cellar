"""Asynchronous Vivino rating and metadata lookup client."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

try:
    import aiohttp
except ImportError:  # pragma: no cover - fallback when running standalone unit tests outside HA venv
    aiohttp = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

VIVINO_EXPLORE_URL = "https://www.vivino.com/api/explore/explore"
VIVINO_WEB_SEARCH_URL = "https://www.vivino.com/search/wines?q="

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _score_candidate(
    candidate: dict[str, Any],
    target_winery: str,
    target_name: str,
    target_vintage: int | None,
) -> float:
    """Rank a Vivino explore match against the queried winery, name, and vintage."""
    score = 0.0
    cand_winery = (candidate.get("winery") or "").lower()
    cand_name = (candidate.get("name") or "").lower()
    cand_vintage = candidate.get("vintage")

    q_winery = (target_winery or "").strip().lower()
    q_name = (target_name or "").strip().lower()

    if q_winery and q_winery in cand_winery:
        score += 3.0
    elif cand_winery and cand_winery in q_winery:
        score += 2.0

    if q_name and q_name in cand_name:
        score += 4.0
    elif cand_name and cand_name in q_name:
        score += 2.5

    if target_vintage and cand_vintage:
        if int(target_vintage) == int(cand_vintage):
            score += 3.5
        elif abs(int(target_vintage) - int(cand_vintage)) == 1:
            score += 1.0

    ratings_count = candidate.get("vivino_ratings_count") or 0
    if ratings_count > 100:
        score += 0.5

    return score


def parse_vivino_explore_payload(
    payload: dict[str, Any],
    *,
    target_winery: str = "",
    target_name: str = "",
    target_vintage: int | None = None,
    max_candidates: int = 3,
) -> list[dict[str, Any]]:
    """Extract and score candidate wine matches from Vivino's explore JSON payload."""
    explore_vintage = payload.get("explore_vintage") or {}
    matches = explore_vintage.get("matches") or []
    candidates: list[dict[str, Any]] = []

    for match in matches:
        if not isinstance(match, dict):
            continue
        vintage_obj = match.get("vintage") or {}
        wine_obj = vintage_obj.get("wine") or {}
        winery_obj = wine_obj.get("winery") or {}
        stats_obj = vintage_obj.get("statistics") or wine_obj.get("statistics") or {}
        region_obj = wine_obj.get("region") or {}
        country_obj = region_obj.get("country") or {}
        image_obj = vintage_obj.get("image") or wine_obj.get("image") or {}
        price_obj = match.get("price") or {}

        winery_name = str(winery_obj.get("name") or "").strip()
        wine_name = str(wine_obj.get("name") or "").strip()
        year_raw = vintage_obj.get("year")
        parsed_year: int | None = None
        if year_raw and str(year_raw).isdigit():
            y_val = int(year_raw)
            if 1800 <= y_val <= 2100:
                parsed_year = y_val

        rating_raw = stats_obj.get("ratings_average")
        rating_val = round(float(rating_raw), 2) if rating_raw is not None else None
        ratings_count_raw = stats_obj.get("ratings_count")
        ratings_count = int(ratings_count_raw) if ratings_count_raw is not None else None

        price_raw = price_obj.get("amount")
        price_val = round(float(price_raw), 2) if price_raw is not None else None

        seo_name = str(wine_obj.get("seo_name") or vintage_obj.get("seo_name") or "").strip()
        wine_id = wine_obj.get("id")
        if seo_name and wine_id:
            vivino_url = f"https://www.vivino.com/wines/{wine_id}"
            if parsed_year:
                vivino_url = f"{vivino_url}?year={parsed_year}"
        else:
            q_str = quote_plus(f"{winery_name} {wine_name}".strip())
            vivino_url = f"{VIVINO_WEB_SEARCH_URL}{q_str}"

        img_location = str(
            image_obj.get("variations", {}).get("bottle_medium")
            or image_obj.get("location")
            or ""
        ).strip()
        if img_location.startswith("//"):
            img_location = f"https:{img_location}"

        candidate = {
            "winery": winery_name,
            "name": wine_name,
            "vintage": parsed_year,
            "region": str(region_obj.get("name") or "").strip(),
            "country": str(country_obj.get("name") or "").strip(),
            "vivino_rating": rating_val,
            "vivino_ratings_count": ratings_count,
            "vivino_url": vivino_url,
            "vivino_price_estimate": price_val,
            "vivino_image_url": img_location,
            "rating_source": "vivino",
        }
        candidate["match_score"] = _score_candidate(
            candidate, target_winery, target_name, target_vintage
        )
        candidates.append(candidate)

    candidates.sort(
        key=lambda c: (
            c.get("match_score", 0.0),
            c.get("vivino_ratings_count") or 0,
        ),
        reverse=True,
    )
    return candidates[:max_candidates]


async def async_lookup_vivino(
    session: aiohttp.ClientSession,
    *,
    winery: str,
    name: str,
    vintage: int | None = None,
    country_code: str = "NL",
    currency_code: str = "EUR",
    max_candidates: int = 3,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Query Vivino's explore endpoint and return top match + candidate list."""
    query_parts = [p.strip() for p in (winery, name, str(vintage or "")) if p and str(p).strip()]
    query_str = " ".join(query_parts).strip()
    search_url = f"{VIVINO_WEB_SEARCH_URL}{quote_plus(query_str)}"

    if not query_str:
        return {
            "status": "empty_query",
            "best_match": None,
            "candidates": [],
            "search_url": search_url,
        }

    params = {
        "q": query_str,
        "country_code": (country_code or "NL").upper(),
        "currency_code": (currency_code or "EUR").upper(),
        "min_rating": "1",
        "order_by": "ratings_count",
        "order": "desc",
        "page": "1",
    }

    timeout = (
        aiohttp.ClientTimeout(total=timeout_seconds)
        if aiohttp is not None
        else timeout_seconds
    )
    client_errors = (
        (aiohttp.ClientError, ValueError, TimeoutError, OSError)
        if aiohttp is not None
        else (ValueError, TimeoutError, OSError)
    )
    try:
        async with session.get(
            VIVINO_EXPLORE_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
        ) as resp:
            if resp.status in (403, 429):
                _LOGGER.info(
                    "Vivino endpoint returned HTTP %s (rate-limited/blocked) for query '%s'",
                    resp.status,
                    query_str,
                )
                return {
                    "status": f"http_{resp.status}",
                    "best_match": None,
                    "candidates": [],
                    "search_url": search_url,
                }
            if resp.status != 200:
                return {
                    "status": f"http_{resp.status}",
                    "best_match": None,
                    "candidates": [],
                    "search_url": search_url,
                }
            payload = await resp.json(content_type=None)
    except client_errors as err:
        _LOGGER.debug("Vivino lookup error for '%s': %s", query_str, err)
        return {
            "status": "error",
            "error": str(err),
            "best_match": None,
            "candidates": [],
            "search_url": search_url,
        }

    if not isinstance(payload, dict):
        return {
            "status": "invalid_payload",
            "best_match": None,
            "candidates": [],
            "search_url": search_url,
        }

    candidates = parse_vivino_explore_payload(
        payload,
        target_winery=winery,
        target_name=name,
        target_vintage=vintage,
        max_candidates=max_candidates,
    )
    return {
        "status": "ok" if candidates else "no_match",
        "best_match": candidates[0] if candidates else None,
        "candidates": candidates,
        "search_url": search_url,
    }

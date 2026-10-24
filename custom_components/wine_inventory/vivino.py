"""Asynchronous Vivino rating and metadata lookup client."""

from __future__ import annotations

import difflib
import html
import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

try:
    import aiohttp
except ImportError:  # pragma: no cover - fallback when running standalone unit tests outside HA venv
    aiohttp = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

VIVINO_SEARCH_URL = "https://www.vivino.com/search/wines?q="
VIVINO_EXPLORE_URL = "https://www.vivino.com/api/explore/explore"
VIVINO_WEB_SEARCH_URL = "https://www.vivino.com/search/wines?q="

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
}


def clean_tokens(s: str) -> list[str]:
    """Extract lowercased alphanumeric words with length > 1."""
    return [t for t in re.findall(r"\w+", (s or "").lower()) if len(t) > 1]


def is_text_similar(target: str, candidate: str, threshold: float = 0.5) -> bool:
    """Check if target and candidate strings are lexically or semantically similar."""
    t = (target or "").strip().lower()
    c = (candidate or "").strip().lower()
    if not t or not c:
        return False
    if t == c:
        return True
    if (len(t) >= 4 and t in c) or (len(c) >= 4 and c in t):
        return True

    t_tokens = set(clean_tokens(t))
    c_tokens = set(clean_tokens(c))
    if t_tokens and c_tokens:
        overlap = t_tokens & c_tokens
        if len(overlap) / min(len(t_tokens), len(c_tokens)) >= 0.5:
            return True

    ratio = difflib.SequenceMatcher(None, t, c).ratio()
    return ratio >= threshold


def is_vivino_candidate_similar(
    candidate: dict[str, Any],
    target_winery: str,
    target_name: str,
) -> bool:
    """Determine whether a candidate Vivino record has a similar wine name or winery/maker.

    Per strict requirement: either wine name or maker needs to be similar.
    If not, do not match the wine to a Vivino match.
    """
    clean_target_winery = (target_winery or "").strip()
    clean_target_name = (target_name or "").strip()

    if not clean_target_winery and not clean_target_name:
        return False

    cand_winery = str(candidate.get("winery") or "").strip()
    cand_name = str(candidate.get("name") or "").strip()

    maker_similar = is_text_similar(clean_target_winery, cand_winery)
    name_similar = is_text_similar(clean_target_name, cand_name)

    # In case the winery was detected as part of the wine name or vice versa
    cross_similar_1 = is_text_similar(clean_target_winery, cand_name)
    cross_similar_2 = is_text_similar(clean_target_name, cand_winery)

    return maker_similar or name_similar or cross_similar_1 or cross_similar_2


def _score_candidate(
    candidate: dict[str, Any],
    target_winery: str,
    target_name: str,
    target_vintage: int | None,
) -> float:
    """Rank a Vivino candidate match against the queried winery, name, and vintage."""
    score = 0.0
    cand_winery = (candidate.get("winery") or "").strip().lower()
    cand_name = (candidate.get("name") or "").strip().lower()
    cand_vintage = candidate.get("vintage")

    q_winery = (target_winery or "").strip().lower()
    q_name = (target_name or "").strip().lower()

    # 1. Winery token comparison
    if q_winery:
        w_tokens = set(re.findall(r"\w+", q_winery))
        cand_w_tokens = set(re.findall(r"\w+", cand_winery))
        overlap = len(w_tokens & cand_w_tokens)
        if q_winery == cand_winery:
            score += 6.0
        elif q_winery in cand_winery or cand_winery in q_winery:
            score += 4.5
        elif overlap > 0:
            score += 3.0 * (overlap / max(len(w_tokens), 1))
        else:
            score -= 2.5

    # 2. Wine name token comparison
    if q_name:
        n_tokens = set(re.findall(r"\w+", q_name))
        cand_n_tokens = set(re.findall(r"\w+", cand_name))
        overlap = len(n_tokens & cand_n_tokens)
        if q_name == cand_name:
            score += 8.0
        elif q_name in cand_name or cand_name in q_name:
            score += 5.5
        elif overlap > 0:
            score += 4.0 * (overlap / max(len(n_tokens), 1))
        else:
            score -= 2.5

    # 3. Vintage alignment
    if target_vintage and cand_vintage:
        try:
            t_v = int(target_vintage)
            c_v = int(cand_vintage)
            if t_v == c_v:
                score += 5.0
            elif abs(t_v - c_v) == 1:
                score += 1.5
            else:
                score -= 1.0
        except (ValueError, TypeError):
            pass

    # 4. Review count confidence bonus
    ratings_count = candidate.get("vivino_ratings_count") or 0
    if ratings_count > 50:
        score += 0.5
    if ratings_count > 500:
        score += 0.5

    return round(score, 2)


def parse_vivino_explore_payload(
    payload: dict[str, Any],
    *,
    target_winery: str = "",
    target_name: str = "",
    target_vintage: int | None = None,
    max_candidates: int = 5,
) -> list[dict[str, Any]]:
    """Extract and score candidate wine matches from Vivino JSON structure or SSR records."""
    matches = (
        payload.get("records")
        or (payload.get("explore_vintage") or {}).get("matches")
        or payload.get("matches")
        or []
    )
    candidates: list[dict[str, Any]] = []

    for match in matches:
        if not isinstance(match, dict):
            continue
        vintage_obj = match.get("vintage") or {}
        wine_obj = vintage_obj.get("wine") or match.get("wine") or {}
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

        # Filter candidate: Either wine name or maker MUST be similar!
        if (target_winery or target_name) and not is_vivino_candidate_similar(
            candidate, target_winery, target_name
        ):
            _LOGGER.debug(
                "Rejecting Vivino candidate '%s - %s' (neither winery nor name is similar to '%s - %s')",
                winery_name,
                wine_name,
                target_winery,
                target_name,
            )
            continue

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


def parse_vivino_search_html(
    html_text: str,
    *,
    target_winery: str = "",
    target_name: str = "",
    target_vintage: int | None = None,
    max_candidates: int = 5,
) -> list[dict[str, Any]]:
    """Parse server-side rendered search results from Vivino search/wines page HTML."""
    all_props = re.findall(r'data-ssr-props="([^"]+)"', html_text)
    for prop_str in all_props:
        try:
            unescaped = html.unescape(prop_str)
            data = json.loads(unescaped)
            if not isinstance(data, dict):
                continue
            records = (
                data.get("initialExploreResults", {}).get("records")
                or data.get("exploreRecords", {}).get("records")
                or []
            )
            if records:
                return parse_vivino_explore_payload(
                    {"records": records},
                    target_winery=target_winery,
                    target_name=target_name,
                    target_vintage=target_vintage,
                    max_candidates=max_candidates,
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed parsing SSR props chunk: %s", err)
            continue
    return []


async def async_lookup_vivino(
    session: aiohttp.ClientSession,
    *,
    winery: str,
    name: str,
    vintage: int | None = None,
    country_code: str = "NL",
    currency_code: str = "EUR",
    max_candidates: int = 5,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Query Vivino search page and return top match + candidate list."""
    clean_winery = (winery or "").strip()
    clean_name = (name or "").strip()

    if clean_winery.lower() in clean_name.lower():
        query_str = clean_name
    elif clean_name.lower() in clean_winery.lower():
        query_str = clean_winery
    else:
        query_str = f"{clean_winery} {clean_name}".strip()

    search_url = f"{VIVINO_SEARCH_URL}{quote_plus(query_str)}"

    if not query_str:
        return {
            "status": "empty_query",
            "best_match": None,
            "candidates": [],
            "search_url": search_url,
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

    # 1. Primary: Query Vivino's real Search page
    try:
        async with session.get(
            search_url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
        ) as resp:
            if resp.status == 200:
                html_content = await resp.text()
                candidates = parse_vivino_search_html(
                    html_content,
                    target_winery=winery,
                    target_name=name,
                    target_vintage=vintage,
                    max_candidates=max_candidates,
                )
                if candidates:
                    return {
                        "status": "ok",
                        "best_match": candidates[0],
                        "candidates": candidates,
                        "search_url": search_url,
                    }
    except client_errors as err:
        _LOGGER.debug("Vivino HTML search error for '%s': %s", query_str, err)

    # 2. Fallback: Query explore endpoint with min_rating=1
    params = {
        "q": query_str,
        "country_code": (country_code or "NL").upper(),
        "currency_code": (currency_code or "EUR").upper(),
        "min_rating": "1",
        "order_by": "ratings_count",
        "order": "desc",
        "page": "1",
    }
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
            if resp.status == 200:
                payload = await resp.json(content_type=None)
                if isinstance(payload, dict):
                    candidates = parse_vivino_explore_payload(
                        payload,
                        target_winery=winery,
                        target_name=name,
                        target_vintage=vintage,
                        max_candidates=max_candidates,
                    )
                    if candidates:
                        return {
                            "status": "ok",
                            "best_match": candidates[0],
                            "candidates": candidates,
                            "search_url": search_url,
                        }
    except client_errors as err:
        _LOGGER.debug("Vivino fallback explore error for '%s': %s", query_str, err)

    return {
        "status": "no_match",
        "best_match": None,
        "candidates": [],
        "search_url": search_url,
    }

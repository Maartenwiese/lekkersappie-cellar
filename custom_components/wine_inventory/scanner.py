"""Gemini Flash-Lite Vision bottle label scanner and local cover saver."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
import re
from typing import Any
import uuid

try:
    import aiohttp
except ImportError:  # pragma: no cover - fallback when running standalone unit tests outside HA venv
    aiohttp = None  # type: ignore[assignment]

from .const import COVERS_SUBDIR, DEFAULT_GEMINI_MODEL, WINE_TYPE_RED, WINE_TYPES

_LOGGER = logging.getLogger(__name__)

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

LABEL_EXTRACTION_PROMPT = """You are an expert master sommelier and wine cataloguing vision intelligence system.
Analyze the provided photo of a wine bottle label (which has been cropped and oriented upright) and extract as much comprehensive, accurate detail as possible into JSON.

Core Extraction Rules:
1. Producer / Winery (`winery`) and Specific Cuvée / Wine Name (`name`):
   - Identify the winemaker/producer/château/bodega/estate cleanly (`winery`).
   - Identify the specific cuvée, vineyard designation, or wine title (`name`).
   - If only a grape varietal is used as the principal wine title (e.g. "Sauvignon Blanc", "Malbec"), use that as `name`.
2. Harvest Year / Vintage (`vintage`):
   - Scrutinize the label, neck band, vintage collar, and embossed elements for the 4-digit harvest year.
   - If Non-Vintage (NV, common in Champagne, sparkling, fortified wines), return null.
3. Grape Variety / Varietals (`varietal`):
   - Identify the primary grape variety or blend composition (e.g., "Cabernet Sauvignon", "Chardonnay", "Pinot Noir", "Nebbiolo", "Tempranillo", "Syrah/Shiraz", "Sangiovese", "Bordeaux Blend", "Rhône Blend", "Sauvignon Blanc", "Riesling", "Malbec", "Merlot").
   - If not explicitly written on Old World labels (e.g. Burgundy, Bordeaux, Rioja, Barolo, Chianti), deduce the canonical legal grape varieties for the appellation (e.g., Barolo = Nebbiolo, Red Burgundy = Pinot Noir, Chablis = Chardonnay, Chianti = Sangiovese).
4. Country of Origin (`country`):
   - Identify the country where the wine was produced (e.g., "France", "Italy", "Spain", "United States", "Germany", "Portugal", "South Africa", "Australia", "New Zealand", "Chile", "Argentina", "Austria", "Greece").
5. Wine Region & Appellation (`region`):
   - Extract the specific geographical growing region or AOC/DOC/DOCG/AVA (e.g., "Bordeaux", "Napa Valley", "Tuscany", "Rioja Alta", "Marlborough", "Mosel", "Piedmont").
6. Wine Style (`wine_type`):
   - Strictly classify as one of: "red", "white", "rose", "sparkling", "dessert", "fortified".
7. Technical Specs:
   - Extract `alcohol_pct` (e.g. 13.5, 14.0) and `bottle_size_ml` (integer, default 750).
8. Sommelier Guidance:
   - Provide recommended drinking window bounds (`drink_from_year` and `drink_until_year`) and a descriptive `drink_window_note` (e.g., "Peak drinking 2026-2032; decant 45 mins before serving").
   - Suggest 2 to 4 concise `food_pairings` items (e.g. ["Grilled ribeye steak", "Aged Comté cheese", "Truffle risotto"]).
   - Provide a concise 1-sentence `label_summary` for the wine overview notes.
   - Return best-effort values even if parts of the label are partially weathered or in low contrast.
"""

LABEL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "winery": {"type": "STRING"},
        "name": {"type": "STRING"},
        "vintage": {"type": "INTEGER", "nullable": True},
        "wine_type": {
            "type": "STRING",
            "enum": ["red", "white", "rose", "sparkling", "dessert", "fortified"],
        },
        "varietal": {"type": "STRING"},
        "region": {"type": "STRING"},
        "country": {"type": "STRING"},
        "alcohol_pct": {"type": "NUMBER", "nullable": True},
        "bottle_size_ml": {"type": "INTEGER", "nullable": True},
        "drink_from_year": {"type": "INTEGER", "nullable": True},
        "drink_until_year": {"type": "INTEGER", "nullable": True},
        "drink_window_note": {"type": "STRING"},
        "food_pairings": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "label_summary": {"type": "STRING"},
    },
    "required": [
        "winery",
        "name",
        "wine_type",
        "varietal",
        "region",
        "country",
        "drink_window_note",
        "food_pairings",
        "label_summary",
    ],
}


class GeminiScannerError(Exception):
    """Raised when Gemini vision label extraction fails."""


def parse_image_data_uri(image_data: str) -> tuple[str, bytes]:
    """Parse a base64 data URI or raw base64 string into (mime_type, raw_bytes)."""
    cleaned = image_data.strip()
    mime_type = "image/jpeg"
    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", cleaned, re.DOTALL)
    if match:
        mime_type = match.group(1).lower()
        b64_payload = match.group(2)
    else:
        b64_payload = cleaned

    raw_bytes = base64.b64decode(b64_payload)
    if not raw_bytes:
        raise GeminiScannerError("Provided image payload is empty.")
    return mime_type, raw_bytes


def save_bottle_cover_image(
    config_dir: str | Path,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> str:
    """Save scanned bottle image under <config>/www/wine_inventory/covers/ and return /local/ URL."""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    ext = ext_map.get(mime_type.lower(), ".jpg")
    filename = f"bottle_{uuid.uuid4().hex[:12]}{ext}"
    covers_dir = Path(config_dir) / COVERS_SUBDIR
    covers_dir.mkdir(parents=True, exist_ok=True)
    target_path = covers_dir / filename
    target_path.write_bytes(image_bytes)
    return f"/local/wine_inventory/covers/{filename}"


def _normalize_extracted_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize and sanitize parsed JSON fields from Gemini response."""
    wine_type = str(raw.get("wine_type") or WINE_TYPE_RED).lower().strip()
    if wine_type not in WINE_TYPES:
        wine_type = WINE_TYPE_RED

    vintage_raw = raw.get("vintage")
    vintage: int | None = None
    if vintage_raw is not None:
        try:
            v_int = int(vintage_raw)
            if 1800 <= v_int <= 2100:
                vintage = v_int
        except (ValueError, TypeError):
            vintage = None

    def _opt_int(val: Any, default: int | None = None) -> int | None:
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _opt_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return round(float(val), 2)
        except (ValueError, TypeError):
            return None

    pairings = raw.get("food_pairings")
    if not isinstance(pairings, list):
        pairings = []
    else:
        pairings = [str(p).strip() for p in pairings if str(p).strip()]

    return {
        "winery": str(raw.get("winery") or "").strip(),
        "name": str(raw.get("name") or "").strip(),
        "vintage": vintage,
        "wine_type": wine_type,
        "varietal": str(raw.get("varietal") or "").strip(),
        "region": str(raw.get("region") or "").strip(),
        "country": str(raw.get("country") or "").strip(),
        "alcohol_pct": _opt_float(raw.get("alcohol_pct")),
        "bottle_size_ml": _opt_int(raw.get("bottle_size_ml"), 750) or 750,
        "drink_from_year": _opt_int(raw.get("drink_from_year")),
        "drink_until_year": _opt_int(raw.get("drink_until_year")),
        "drink_window_note": str(raw.get("drink_window_note") or "").strip(),
        "food_pairings": pairings,
        "general_notes": str(raw.get("label_summary") or "").strip(),
    }


async def async_scan_bottle_label(
    session: aiohttp.ClientSession,
    *,
    api_key: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    model: str = DEFAULT_GEMINI_MODEL,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Call Gemini REST API to extract structured wine label metadata from an image."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        raise GeminiScannerError(
            "Gemini API key is not configured. Add it in Wine Inventory settings."
        )
    model_id = (model or DEFAULT_GEMINI_MODEL).strip()
    if model_id.startswith("models/"):
        model_id = model_id[len("models/") :]

    url = f"{GEMINI_API_BASE_URL}/{model_id}:generateContent"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")

    request_body: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": LABEL_EXTRACTION_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": encoded_image,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": LABEL_RESPONSE_SCHEMA,
        },
    }

    timeout = (
        aiohttp.ClientTimeout(total=timeout_seconds)
        if aiohttp is not None
        else timeout_seconds
    )
    client_error_cls = aiohttp.ClientError if aiohttp is not None else OSError
    try:
        async with session.post(
            url,
            params={"key": clean_key},
            json=request_body,
            timeout=timeout,
        ) as resp:
            resp_text = await resp.text()
            if resp.status != 200:
                if resp.status == 400:
                    raise GeminiScannerError(
                        f"Gemini API Bad Request (HTTP 400): {resp_text[:250]}. Check your configured Gemini Model ID in Lekkersappie options."
                    )
                if resp.status in (401, 403):
                    raise GeminiScannerError(
                        f"Gemini API Permission Denied (HTTP {resp.status}): {resp_text[:250]}. Check that your Google Gemini API key is valid and Generative Language API is enabled."
                    )
                if resp.status == 429:
                    raise GeminiScannerError(
                        "Gemini API Rate Limit / Quota Exceeded (HTTP 429). Please wait a moment before scanning another bottle."
                    )
                raise GeminiScannerError(
                    f"Gemini API returned HTTP {resp.status}: {resp_text[:300]}"
                )
            payload = json.loads(resp_text)
    except client_error_cls as err:
        raise GeminiScannerError(f"Network error contacting Gemini API: {err}") from err
    except json.JSONDecodeError as err:
        raise GeminiScannerError(f"Invalid JSON returned by Gemini API: {err}") from err

    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiScannerError("Gemini returned no candidates for the bottle image.")

    parts = candidates[0].get("content", {}).get("parts") or []
    text_output = "".join(str(p.get("text") or "") for p in parts).strip()
    if not text_output:
        raise GeminiScannerError("Gemini returned an empty content part.")

    try:
        parsed_json = json.loads(text_output)
    except json.JSONDecodeError as err:
        raise GeminiScannerError(
            f"Gemini output could not be parsed as JSON: {text_output[:200]}"
        ) from err

    normalized = _normalize_extracted_payload(parsed_json)
    normalized["model_used"] = model_id
    return normalized


async def async_estimate_rating_via_gemini(
    session: aiohttp.ClientSession,
    *,
    api_key: str,
    winery: str,
    name: str,
    vintage: int | None,
    model: str = DEFAULT_GEMINI_MODEL,
    currency: str = "EUR",
    timeout_seconds: float = 15.0,
) -> dict[str, Any] | None:
    """Fallback when Vivino HTTP endpoint is rate-limited (403/429) or unreachable."""
    clean_key = (api_key or "").strip()
    if not clean_key or (not winery and not name):
        return None

    model_id = (model or DEFAULT_GEMINI_MODEL).strip()
    if model_id.startswith("models/"):
        model_id = model_id[len("models/") :]

    url = f"{GEMINI_API_BASE_URL}/{model_id}:generateContent"
    vintage_str = str(vintage) if vintage else "Non-Vintage"
    prompt = (
        f"Provide the typical community wine rating (on a 1.0 to 5.0 scale) and estimated "
        f"retail price in {currency} for: Winery='{winery}', Wine='{name}', Vintage={vintage_str}. "
        f"If completely unknown, return null for rating."
    )
    schema = {
        "type": "OBJECT",
        "properties": {
            "estimated_rating": {"type": "NUMBER", "nullable": True},
            "estimated_price": {"type": "NUMBER", "nullable": True},
        },
    }
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }

    timeout = (
        aiohttp.ClientTimeout(total=timeout_seconds)
        if aiohttp is not None
        else timeout_seconds
    )
    try:
        async with session.post(
            url,
            params={"key": clean_key},
            json=body,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            parts = (
                (data.get("candidates") or [{}])[0]
                .get("content", {})
                .get("parts")
                or []
            )
            raw_text = "".join(str(p.get("text") or "") for p in parts).strip()
            if not raw_text:
                return None
            parsed = json.loads(raw_text)
            rating = parsed.get("estimated_rating")
            price = parsed.get("estimated_price")
            if rating is None:
                return None
            return {
                "vivino_rating": round(float(rating), 2),
                "vivino_ratings_count": None,
                "vivino_url": f"https://www.vivino.com/search/wines?q={winery}+{name}",
                "vivino_price_estimate": round(float(price), 2) if price else None,
                "vivino_image_url": "",
                "rating_source": "gemini_estimate",
            }
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Gemini rating fallback failed: %s", err)
        return None


WINE_RESEARCH_PROMPT = """You are a world-class master sommelier and esteemed wine historian.
Conduct an in-depth, authoritative research review for the following wine:
- Producer / Winery: {winery}
- Wine / Cuvée Name: {name}
- Vintage / Year: {vintage}
- Grape Variety / Blend: {varietal}
- Region / Appellation: {region}
- Country of Origin: {country}
- Wine Type / Style: {wine_type}
- Stored Notes: {notes}

Provide structured, engaging, sommelier-grade research covering:
1. Producer History: A rich, concise narrative covering the history of the winery, estate, founding heritage, winemaking philosophy, and notable winemakers.
2. The Wine & Terroir: Heritage of this specific cuvée, vineyard location, soil composition, microclimate (terroir), and vinification / barrel-aging methods.
3. Tasting Profile & Structure: Detailed aromatic notes, palate profile, acid/tannin structure, body, and aging potential / peak window.
4. Serving & Food Pairings: Recommended serving temperature, decanting duration, glassware, and ideal culinary pairings.
5. Fun Facts & Accolades: 1 or 2 fascinating historical anecdotes, awards, or trivia about the estate or wine.
6. Summary: A 2-sentence executive summary highlighting what makes this wine and producer special.
"""

WINE_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "producer_history": {"type": "STRING"},
        "wine_and_terroir": {"type": "STRING"},
        "tasting_profile": {"type": "STRING"},
        "serving_and_pairing": {"type": "STRING"},
        "fun_facts": {"type": "STRING"},
        "summary": {"type": "STRING"},
    },
    "required": [
        "producer_history",
        "wine_and_terroir",
        "tasting_profile",
        "serving_and_pairing",
        "summary",
    ],
}


async def async_research_wine_with_gemini(
    session: aiohttp.ClientSession,
    *,
    api_key: str,
    wine_data: dict[str, Any],
    model: str = DEFAULT_GEMINI_MODEL,
    timeout_seconds: float = 35.0,
) -> dict[str, Any]:
    """Perform in-depth Gemini AI research scan on wine producer and cuvée history."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        raise GeminiScannerError(
            "Gemini API key is not configured. Add it in Lekkersappie options."
        )

    model_id = (model or DEFAULT_GEMINI_MODEL).strip()
    if model_id.startswith("models/"):
        model_id = model_id[len("models/") :]

    url = f"{GEMINI_API_BASE_URL}/{model_id}:generateContent"

    winery = str(wine_data.get("winery") or "Unknown Producer").strip()
    name = str(wine_data.get("name") or "Estate Wine").strip()
    vintage_str = str(wine_data.get("vintage") or "Non-Vintage")
    varietal = str(wine_data.get("varietal") or "Traditional Varieties").strip()
    region = str(wine_data.get("region") or "Unknown Region").strip()
    country = str(wine_data.get("country") or "Unknown Country").strip()
    wine_type = str(wine_data.get("wine_type") or "red").strip()
    notes = str(wine_data.get("general_notes") or "").strip()

    prompt = WINE_RESEARCH_PROMPT.format(
        winery=winery,
        name=name,
        vintage=vintage_str,
        varietal=varietal,
        region=region,
        country=country,
        wine_type=wine_type,
        notes=notes,
    )

    request_body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": WINE_RESEARCH_SCHEMA,
        },
    }

    timeout = (
        aiohttp.ClientTimeout(total=timeout_seconds)
        if aiohttp is not None
        else timeout_seconds
    )
    client_error_cls = aiohttp.ClientError if aiohttp is not None else OSError

    try:
        async with session.post(
            url,
            params={"key": clean_key},
            json=request_body,
            timeout=timeout,
        ) as resp:
            resp_text = await resp.text()
            if resp.status != 200:
                raise GeminiScannerError(
                    f"Gemini API returned HTTP {resp.status} during wine research: {resp_text[:250]}"
                )
            payload = json.loads(resp_text)
    except client_error_cls as err:
        raise GeminiScannerError(f"Network error contacting Gemini API: {err}") from err
    except json.JSONDecodeError as err:
        raise GeminiScannerError(f"Invalid JSON returned by Gemini API: {err}") from err

    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiScannerError("Gemini returned no research output for this wine.")

    parts = candidates[0].get("content", {}).get("parts") or []
    text_output = "".join(str(p.get("text") or "") for p in parts).strip()
    if not text_output:
        raise GeminiScannerError("Gemini returned an empty research text response.")

    try:
        research_json = json.loads(text_output)
    except json.JSONDecodeError as err:
        raise GeminiScannerError(
            f"Failed to parse Gemini research JSON: {text_output[:200]}"
        ) from err

    return {
        "status": "ok",
        "research": research_json,
        "model_used": model_id,
    }

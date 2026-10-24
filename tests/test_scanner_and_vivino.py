"""Unit tests for Gemini Flash-Lite label scanner, Vivino parser, and Coordinator."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

from custom_components.wine_inventory.coordinator import WineInventoryCoordinator
from custom_components.wine_inventory.scanner import (
    parse_image_data_uri,
    save_bottle_cover_image,
)
from custom_components.wine_inventory.vivino import parse_vivino_explore_payload


class _StubHttpResponse:
    """Test helper representing an async HTTP response."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return json.dumps(self._body)

    async def json(self, content_type: str | None = None) -> dict[str, Any]:
        return self._body

    async def __aenter__(self) -> _StubHttpResponse:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class _StubHttpSession:
    """Test helper routing Gemini POST and Vivino GET calls."""

    def __init__(
        self,
        gemini_payload: dict[str, Any],
        vivino_status: int = 200,
        vivino_payload: dict[str, Any] | None = None,
    ) -> None:
        self.gemini_payload = gemini_payload
        self.vivino_status = vivino_status
        self.vivino_payload = vivino_payload or {}

    def post(self, url: str, **kwargs: Any) -> _StubHttpResponse:
        return _StubHttpResponse(200, self.gemini_payload)

    def get(self, url: str, **kwargs: Any) -> _StubHttpResponse:
        return _StubHttpResponse(self.vivino_status, self.vivino_payload)


class _StubHassConfig:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = str(config_dir)


class _StubHass:
    def __init__(self, config_dir: Path) -> None:
        self.config = _StubHassConfig(config_dir)

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


class TestScannerVivinoAndCoordinator(unittest.TestCase):
    """Test suite for image parsing, Vivino candidate ranking, and Coordinator workflows."""

    def test_parse_data_uri_and_save_cover(self) -> None:
        """Verify base64 data URI parsing and cover thumbnail saving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_bytes = b"\xff\xd8\xff\xe0JFIF-test-jpeg"
            b64_uri = "data:image/jpeg;base64," + base64.b64encode(sample_bytes).decode(
                "ascii"
            )
            mime, raw = parse_image_data_uri(b64_uri)
            self.assertEqual(mime, "image/jpeg")
            self.assertEqual(raw, sample_bytes)

            local_url = save_bottle_cover_image(Path(tmpdir), raw, mime)
            self.assertTrue(local_url.startswith("/local/wine_inventory/covers/bottle_"))
            self.assertTrue(local_url.endswith(".jpg"))

    def test_parse_vivino_explore_candidates(self) -> None:
        """Verify Vivino explore response parsing and match scoring."""
        sample_vivino = {
            "explore_vintage": {
                "matches": [
                    {
                        "vintage": {
                            "year": 2019,
                            "seo_name": "antinori-tignanello-2019",
                            "statistics": {"ratings_average": 4.5, "ratings_count": 14820},
                            "image": {"location": "//images.vivino.com/thumbs/tig.png"},
                            "wine": {
                                "id": 1652,
                                "name": "Tignanello",
                                "winery": {"name": "Antinori"},
                                "region": {
                                    "name": "Toscana",
                                    "country": {"name": "Italy"},
                                },
                            },
                        },
                        "price": {"amount": 135.0},
                    },
                    {
                        "vintage": {
                            "year": 2020,
                            "statistics": {"ratings_average": 4.4, "ratings_count": 9200},
                            "wine": {
                                "id": 1652,
                                "name": "Tignanello",
                                "winery": {"name": "Antinori"},
                                "region": {"name": "Toscana", "country": {"name": "Italy"}},
                            },
                        },
                        "price": {"amount": 130.0},
                    },
                ]
            }
        }

        candidates = parse_vivino_explore_payload(
            sample_vivino,
            target_winery="Antinori",
            target_name="Tignanello",
            target_vintage=2019,
        )
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["vintage"], 2019)
        self.assertEqual(candidates[0]["vivino_rating"], 4.5)
        self.assertEqual(candidates[0]["vivino_ratings_count"], 14820)
        self.assertEqual(candidates[0]["vivino_price_estimate"], 135.0)
        self.assertEqual(
            candidates[0]["vivino_image_url"],
            "https://images.vivino.com/thumbs/tig.png",
        )

    def test_coordinator_end_to_end_scan_add_and_export(self) -> None:
        """Verify full async workflow: Gemini scan -> Vivino lookup -> DB add -> CSV export."""

        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                gemini_extracted = {
                    "winery": "Antinori",
                    "name": "Tignanello",
                    "vintage": 2019,
                    "wine_type": "red",
                    "varietal": "Sangiovese, Cabernet Sauvignon",
                    "region": "Toscana",
                    "country": "Italy",
                    "alcohol_pct": 14.0,
                    "bottle_size_ml": 750,
                    "drink_from_year": 2024,
                    "drink_until_year": 2036,
                    "drink_window_note": "Decant 90 minutes before serving",
                    "food_pairings": ["Bistecca alla Fiorentina", "Aged Pecorino"],
                    "label_summary": "Iconic Super Tuscan blend from Marchesi Antinori.",
                }
                gemini_resp = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": json.dumps(gemini_extracted)}],
                            }
                        }
                    ]
                }
                vivino_resp = {
                    "explore_vintage": {
                        "matches": [
                            {
                                "vintage": {
                                    "year": 2019,
                                    "seo_name": "antinori-tignanello",
                                    "statistics": {
                                        "ratings_average": 4.5,
                                        "ratings_count": 15000,
                                    },
                                    "wine": {
                                        "id": 1652,
                                        "name": "Tignanello",
                                        "winery": {"name": "Antinori"},
                                        "region": {
                                            "name": "Toscana",
                                            "country": {"name": "Italy"},
                                        },
                                    },
                                },
                                "price": {"amount": 140.0},
                            }
                        ]
                    }
                }

                stub_session = _StubHttpSession(gemini_resp, 200, vivino_resp)
                hass = _StubHass(tmp_path)
                coordinator = WineInventoryCoordinator(
                    hass=hass,
                    entry_id="test_entry",
                    config={
                        "cellar_name": "Home Cellar",
                        "gemini_api_key": "test-key",
                        "gemini_model": "gemini-3.8-flash-lite",
                        "currency": "EUR",
                        "vivino_country_code": "NL",
                    },
                    session_getter=lambda _h: stub_session,
                )
                await coordinator.async_initialize()

                events_fired: list[tuple[str, dict[str, Any]]] = []
                coordinator.async_add_event_listener(
                    lambda et, data: events_fired.append((et, data))
                )

                sample_img = "data:image/jpeg;base64," + base64.b64encode(
                    b"test-jpg-payload"
                ).decode("ascii")
                scan_result = await coordinator.async_scan_bottle(image_data=sample_img)

                self.assertEqual(scan_result["extracted"]["winery"], "Antinori")
                self.assertEqual(scan_result["extracted"]["vivino_rating"], 4.5)
                self.assertIsNone(scan_result["existing_wine"])

                saved_wine = await coordinator.async_add_wine(
                    {
                        **scan_result["extracted"],
                        "quantity": 3,
                        "purchase_location": "Gall & Gall",
                        "storage_location": "Cellar Rack B2",
                        "batch_notes": "Bought a 3-pack case",
                    }
                )
                self.assertEqual(saved_wine["quantity"], 3)
                self.assertEqual(coordinator.statistics["total_bottles"], 3)
                self.assertTrue(any(et == "bottle_added" for et, _ in events_fired))

                export_res = await coordinator.async_export_inventory("csv")
                self.assertEqual(export_res["exported_wines"], 1)
                self.assertTrue(Path(export_res["file_path"]).exists())

        asyncio.run(_run())

    def test_gemini_scanner_error_reporting_on_http_failures(self) -> None:
        """Verify that GeminiScannerError reports descriptive, user-friendly messages for HTTP 400, 403, 429."""
        from custom_components.wine_inventory.scanner import (
            GeminiScannerError,
            async_scan_bottle_label,
        )

        class _ErrorSession:
            def __init__(self, status: int, text: str) -> None:
                self.status = status
                self.msg_text = text

            def post(self, url: str, **kwargs: Any) -> Any:
                class _Resp:
                    def __init__(self, s: int, t: str) -> None:
                        self.status = s
                        self.t = t

                    async def text(self) -> str:
                        return self.t

                    async def __aenter__(self) -> Any:
                        return self

                    async def __aexit__(self, *args: Any) -> None:
                        pass

                return _Resp(self.status, self.msg_text)

        async def _run() -> None:
            # 1. HTTP 400 - Model ID error
            with self.assertRaises(GeminiScannerError) as ctx_400:
                await async_scan_bottle_label(
                    _ErrorSession(400, "models/invalid not found"),  # type: ignore[arg-type]
                    api_key="valid-key",
                    image_bytes=b"dummy",
                )
            self.assertIn("HTTP 400", str(ctx_400.exception))
            self.assertIn("Check your configured Gemini Model ID", str(ctx_400.exception))

            # 2. HTTP 403 - Permission Denied / Key issue
            with self.assertRaises(GeminiScannerError) as ctx_403:
                await async_scan_bottle_label(
                    _ErrorSession(403, "API_KEY_INVALID"),  # type: ignore[arg-type]
                    api_key="bad-key",
                    image_bytes=b"dummy",
                )
            self.assertIn("HTTP 403", str(ctx_403.exception))
            self.assertIn("Google Gemini API key", str(ctx_403.exception))

            # 3. HTTP 429 - Rate limit / Quota
            with self.assertRaises(GeminiScannerError) as ctx_429:
                await async_scan_bottle_label(
                    _ErrorSession(429, "RESOURCE_EXHAUSTED"),  # type: ignore[arg-type]
                    api_key="valid-key",
                    image_bytes=b"dummy",
                )
            self.assertIn("HTTP 429", str(ctx_429.exception))
            self.assertIn("Rate Limit", str(ctx_429.exception))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

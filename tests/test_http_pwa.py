"""Unit tests for the standalone Lekkersappie Mobile PWA HTTP API and card editors."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from custom_components.wine_inventory.const import DOMAIN, MOBILE_APP_URL_BASE, VERSION
from custom_components.wine_inventory.coordinator import WineInventoryCoordinator
from custom_components.wine_inventory.http_api import (
    WineInventoryMobileAssetView,
    WineInventoryPwaApiView,
    async_handle_pwa_get,
    async_handle_pwa_post,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "wine_inventory"
MOBILE_DIR = INTEGRATION_DIR / "frontend" / "mobile"


class _StubConfig:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self.config_dir = str(self._root)

    def path(self, *parts: str) -> str:
        return str(self._root.joinpath(*parts))


class _StubBus:
    def async_fire(self, event_type: str, event_data: dict) -> None:
        pass


class _StubHass:
    def __init__(self, root: str) -> None:
        self.config = _StubConfig(root)
        self.bus = _StubBus()
        self.states: dict = {}
        self.data: dict = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class TestMobilePwaAndCards(unittest.IsolatedAsyncioTestCase):
    """Test the standalone mobile PWA REST backend, manifest, and card registrations."""

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.hass = _StubHass(self._tmpdir.name)
        self.coordinator = WineInventoryCoordinator(
            hass=self.hass,
            entry_id="test_entry",
            config={"cellar_name": "Test Cellar", "currency": "EUR"},
        )
        await self.coordinator.async_initialize()
        self.hass.data[DOMAIN] = {"test_entry": {"coordinator": self.coordinator}}

    async def asyncTearDown(self) -> None:
        self._tmpdir.cleanup()

    async def test_pwa_lifecycle_endpoints(self) -> None:
        """Verify state, add, detail, adjust, update, unlink_vivino, and delete via HTTP API."""
        status, state = await async_handle_pwa_get(self.hass, "state", {})
        self.assertEqual(status, 200)
        self.assertEqual(state["version"], VERSION)
        self.assertEqual(state["cellar_name"], "Test Cellar")
        self.assertEqual(state["statistics"]["total_bottles"], 0)
        self.assertIn("Wine Fridge", state["areas"])

        # Add a bottle via POST /api/wine_inventory/pwa/add
        status, added = await async_handle_pwa_post(
            self.hass,
            "add",
            {
                "winery": "Domaine Tempier",
                "name": "Bandol Rosé",
                "vintage": 2023,
                "wine_type": "rose",
                "varietal": "Mourvèdre, Grenache, Cinsault",
                "country": "France",
                "region": "Provence",
                "quantity": 3,
                "storage_location": "Wine Fridge",
                "purchase_location": "Chabrol Wines",
                "purchase_price": 38.5,
                "vivino_rating": 4.3,
                "vivino_url": "https://www.vivino.com/w/12345?year=2023",
            },
        )
        self.assertEqual(status, 200)
        wine_id = added["wine"]["id"]
        self.assertEqual(added["statistics"]["total_bottles"], 3)

        # Fetch detail via GET /api/wine_inventory/pwa/detail
        status, detail = await async_handle_pwa_get(
            self.hass, "detail", {"wine_id": str(wine_id)}
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["wine"]["name"], "Bandol Rosé")
        self.assertEqual(detail["wine"]["quantity"], 3)

        # Adjust bottle count (-1) via POST /api/wine_inventory/pwa/adjust
        status, adjusted = await async_handle_pwa_post(
            self.hass, "adjust", {"wine_id": wine_id, "delta": -1}
        )
        self.assertEqual(status, 200)
        self.assertEqual(adjusted["wine"]["quantity"], 2)

        # Update metadata via POST /api/wine_inventory/pwa/update
        status, updated = await async_handle_pwa_post(
            self.hass,
            "update",
            {
                "wine_id": wine_id,
                "updates": {
                    "storage_location": "Wine Cellar",
                    "purchase_price": 41.0,
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["wine"]["storage_location"], "Wine Cellar")
        self.assertEqual(updated["wine"]["purchase_price"], 41.0)

        # Unlink Vivino via POST /api/wine_inventory/pwa/unlink_vivino
        status, unlinked = await async_handle_pwa_post(
            self.hass, "unlink_vivino", {"wine_id": wine_id}
        )
        self.assertEqual(status, 200)
        self.assertEqual(unlinked["wine"]["vivino_url"], "")
        self.assertIsNone(unlinked["wine"]["vivino_rating"])

        # Delete wine via POST /api/wine_inventory/pwa/delete
        status, deleted = await async_handle_pwa_post(
            self.hass, "delete", {"wine_id": wine_id}
        )
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["statistics"]["total_bottles"], 0)

    def test_mobile_pwa_manifest_and_assets_compliance(self) -> None:
        """Verify PWA manifest and assets meet installable standalone standards."""
        self.assertEqual(MOBILE_APP_URL_BASE, "/lekkersappie")
        manifest_path = MOBILE_DIR / "manifest.webmanifest"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["id"], "/lekkersappie/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/lekkersappie/index.html")
        self.assertEqual(manifest["scope"], "/lekkersappie/")
        self.assertLessEqual(len(manifest["short_name"]), 12)

        icon_sizes = {i["sizes"] for i in manifest["icons"]}
        self.assertIn("192x192", icon_sizes)
        self.assertIn("512x512", icon_sizes)
        purposes = {i["purpose"] for i in manifest["icons"]}
        self.assertIn("any", purposes)
        self.assertIn("maskable", purposes)

        for asset in (
            "index.html",
            "app.js",
            "styles.css",
            "sw.js",
            "icon-192.png",
            "icon-512.png",
            "icon-maskable-512.png",
            "apple-touch-icon.png",
            "icon.svg",
        ):
            self.assertTrue(
                (MOBILE_DIR / asset).exists(),
                f"Expected mobile PWA asset missing: {asset}",
            )

        html = (MOBILE_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest" href="/lekkersappie/manifest.webmanifest"', html)
        self.assertIn('rel="apple-touch-icon" href="/lekkersappie/apple-touch-icon.png"', html)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', html)

    def test_lovelace_cards_and_detailed_view_text_sizing(self) -> None:
        """Verify custom:wine-inventory-card and custom:wine-cellar-summary-card registrations and detail scaling."""
        card_js = (INTEGRATION_DIR / "frontend" / "wine-inventory-card.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("static getStubConfig()", card_js)
        self.assertIn("static getConfigElement()", card_js)
        self.assertIn("wine-inventory-card-editor", card_js)
        self.assertIn("wine-cellar-summary-card", card_js)
        self.assertIn("wine-cellar-summary-card-editor", card_js)
        self.assertIn("btn-detail-font-scale", card_js)
        self.assertIn(".modal-inner", card_js)
        self.assertIn("@container lsmodal", card_js)
        self.assertIn("lekkersappie_ha_tokens", card_js)
        self.assertIn("bottle-library-input", card_js)

    async def test_v031_mobile_auth_font_list_scroll_and_library(self) -> None:
        """Verify v0.3.1 HA authentication inheritance, L default font, list icons, scroll fix, and library upload."""
        self.assertTrue(WineInventoryPwaApiView.requires_auth)
        self.assertEqual(WineInventoryMobileAssetView.url, "/lekkersappie/{filename}")
        for route in (
            "/lekkersappie",
            "/lekkersappie/",
            "/api/wine_inventory/mobile",
            "/api/wine_inventory/mobile/",
            "/api/wine_inventory/mobile/{filename}",
        ):
            self.assertIn(route, WineInventoryMobileAssetView.extra_urls)

        status, state = await async_handle_pwa_get(
            self.hass,
            "state",
            {},
            authenticated_user={"id": "ha_user_1", "name": "Maarten"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["authenticated_user"]["name"], "Maarten")

        app_js = (MOBILE_DIR / "app.js").read_text(encoding="utf-8")
        styles_css = (MOBILE_DIR / "styles.css").read_text(encoding="utf-8")

        # 1. Home Assistant authentication inheritance
        self.assertIn("hassTokens", app_js)
        self.assertIn("lekkersappie_ha_tokens", app_js)
        self.assertIn("/auth/token", app_js)
        self.assertIn("/auth/authorize", app_js)
        self.assertIn("Bearer ${token}", app_js)

        # 2. Default font size L (1.15)
        self.assertIn("--ls-app-scale: 1.15;", styles_css)
        self.assertIn("lekkersappie_mobile_font_scale", app_js)
        self.assertIn("val >= 0.8 && val <= 1.5 ? val : 1.15;", app_js)

        # 3. Richer mobile list view with grape and bought date icons
        self.assertIn("bottle-detail-chips", app_js)
        self.assertIn("🍇 ${esc(w.varietal)}", app_js)
        self.assertIn("🗓️ ${esc(boughtDateLabel)}", app_js)
        self.assertIn(".bottle-detail-chips", styles_css)
        self.assertIn(".meta-chip", styles_css)

        # 4. Scrollable Detailed sheet structure (.sheet-body wraps .scaled-zone with min-height: 0)
        self.assertIn('id="detail-sheet-body"', app_js)
        self.assertIn("min-height: 0;", styles_css)
        self.assertIn("overflow-y: auto;", styles_css)
        self.assertIn("overscroll-behavior: contain;", styles_css)

        # 4b. Real asset view serves every mobile file (regression: HTTP 500 when
        # charset was passed inside content_type to aiohttp web.Response).
        from aiohttp import web as aio_web
        from aiohttp.test_utils import make_mocked_request

        asset_view = WineInventoryMobileAssetView(self.hass)
        for fname, mime in (
            ("index.html", "text/html"),
            ("app.js", "application/javascript"),
            ("styles.css", "text/css"),
            ("sw.js", "application/javascript"),
            ("manifest.webmanifest", "application/manifest+json"),
            ("icon-192.png", "image/png"),
        ):
            req = make_mocked_request("GET", f"/lekkersappie/{fname}")
            resp = await asset_view.get(req, fname)
            self.assertEqual(resp.status, 200, fname)
            self.assertEqual(resp.content_type, mime, fname)
        with self.assertRaises(aio_web.HTTPFound):
            await asset_view.get(make_mocked_request("GET", "/lekkersappie"), None)

        # PWA API view resolves hass from the view instance (no request.app["hass"]).
        api_view = WineInventoryPwaApiView(self.hass)
        api_resp = await api_view.get(
            make_mocked_request("GET", "/api/wine_inventory/pwa/state"), "state"
        )
        self.assertEqual(api_resp.status, 200)

        # 5. Photo library selection alongside camera capture
        self.assertIn('id="mobile-scan-file"', app_js)
        self.assertIn('id="mobile-scan-library"', app_js)
        self.assertIn("Choose from Library", app_js)


    def test_hacs_json_follows_publish_guidance(self) -> None:
        """hacs.json uses only documented keys, has a name, and avoids the zip_release that broke installs."""
        hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))
        allowed = {
            "name",
            "content_in_root",
            "zip_release",
            "filename",
            "hide_default_branch",
            "country",
            "homeassistant",
            "hacs",
            "persistent_directory",
            "render_readme",
        }
        self.assertTrue(set(hacs).issubset(allowed), set(hacs) - allowed)
        self.assertEqual(hacs["name"], "Lekkersappie")
        self.assertFalse(hacs.get("content_in_root", False))
        self.assertNotIn("zip_release", hacs)
        self.assertRegex(hacs["homeassistant"], r"^\d{4}\.\d{1,2}\.\d+$")
        manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["codeowners"], ["@Maartenwiese"])
        for key in ("domain", "name", "version", "documentation", "issue_tracker", "codeowners"):
            self.assertIn(key, manifest)

    def test_v033_mobile_touch_first_stats_config_and_crop(self) -> None:
        """Stats/Config tabs, touch targets, touch crop, confirm sheet, toast, scroll preservation."""
        app_js = (MOBILE_DIR / "app.js").read_text(encoding="utf-8")
        css = (MOBILE_DIR / "styles.css").read_text(encoding="utf-8")

        # Navigation renamed
        self.assertIn('data-nav="stats"', app_js)
        self.assertIn('data-nav="config"', app_js)
        self.assertIn("<span>Stats</span>", app_js)
        self.assertIn("<span>Config</span>", app_js)
        self.assertNotIn("<span>Areas</span>", app_js)
        self.assertNotIn("<span>App</span>", app_js)
        self.assertIn("⚙️", app_js)

        # Expanded statistics
        for label in ("Avg. Price / Bottle", "Top Countries", "Top Grapes", "Top Stores",
                      "Drinking Window", "Highest rated", "Drink first", "Bottles added (30 days)"):
            self.assertIn(label, app_js)

        # Larger touch targets
        self.assertIn("min-height: 48px;", css)
        self.assertIn("touch-action: manipulation;", css)
        self.assertNotRegex(app_js, r"min-height:\s*[0-3]\dpx")

        # Touch-native crop & rotate
        for token in ('addEventListener("pointerdown"', 'addEventListener("pointermove"',
                      "setPointerCapture", 'id="crop-fine-slider"', "_cropGeometry", "devicePixelRatio"):
            self.assertIn(token, app_js)
        self.assertIn("touch-action: none; /* finger drags", css)

        # No blocking native dialogs; toast doesn't re-render
        self.assertNotIn("window.confirm(", app_js)
        self.assertNotIn("alert(", app_js)
        self.assertIn("confirmAction(", app_js)
        toast_body = app_js.split("showToast(msg, kind")[1].split("showError(")[0]
        self.assertNotIn("this.render()", toast_body)

        # Scroll preservation, form binding, numeric keyboards, pull-to-refresh
        self.assertIn("_lastRenderedSheet", app_js)
        self.assertIn("_bindFormState", app_js)
        self.assertIn('inputmode="numeric"', app_js)
        self.assertIn('inputmode="decimal"', app_js)
        self.assertIn("ptr-indicator", app_js)
        self.assertIn("calc(16px / var(--ls-app-scale", css)


    def test_v034_scan_contract_header_splash_and_back(self) -> None:
        """Mobile scan mapping uses the real coordinator response keys; header removed; splash; back nav."""
        import re

        app_js = (MOBILE_DIR / "app.js").read_text(encoding="utf-8")
        html = (MOBILE_DIR / "index.html").read_text(encoding="utf-8")
        coord = (INTEGRATION_DIR / "coordinator.py").read_text(encoding="utf-8")

        # Contract: every key the mobile app reads from the scan response must be
        # returned by coordinator.async_scan_bottle (regression: it read `recognized`).
        scan_fn = coord.split("async def async_scan_bottle")[1].split("async def ")[0]
        returned = set(re.findall(r'"([a-z_]+)":', scan_fn))
        mapper = app_js.split("_applyScanResult(res) {")[1].split("_selectScanCandidate(idx) {")[0]
        read_keys = set(re.findall(r"res\?\.([a-z_]+)", mapper))
        self.assertTrue(read_keys, "scan mapper reads no keys")
        self.assertTrue(read_keys.issubset(returned), read_keys - returned)
        self.assertIn("extracted", read_keys)
        self.assertNotIn("res.recognized", app_js)
        self.assertIn("this._applyScanResult(res)", app_js)

        # Header removed; Aa removed from sheets; back buttons instead of ✕
        self.assertNotIn('class="top-app-bar"', app_js)
        self.assertNotIn("btn-sheet-font-scale", app_js)
        self.assertNotIn("btn-top-font-scale\" title", app_js)
        self.assertIn("btn-back", app_js)
        self.assertNotRegex(app_js, r'id="btn-close-sheet"[^>]*>✕')
        self.assertIn('addEventListener("popstate"', app_js)
        self.assertIn("history.pushState", app_js)

        # Splash: static, 2 seconds, once per session
        self.assertIn('id="ls-splash"', html)
        self.assertIn("Lekkersappie", html)
        self.assertIn("Wine Cellar", html)
        self.assertIn("2000", html)
        self.assertIn("sessionStorage", html)

    async def test_v035_float_bug_splash_version_fullscreen_stepper_and_autosize(self) -> None:
        """v0.3.5: empty-string float bug fixed, splash shows version, full-screen pages, no cellar +/- stepper, auto-scaling notes."""
        # 1. Saving a wine from the mobile scan form with empty strings "" in numeric fields
        # must succeed AND all subsequent DB updates must succeed without ValueError.
        status, added = await async_handle_pwa_post(
            self.hass,
            "add",
            {
                "winery": "Cloudy Bay",
                "name": "Sauvignon Blanc",
                "vintage": "",
                "wine_type": "white",
                "quantity": 2,
                "vivino_rating": "",
                "vivino_price_estimate": "",
                "purchase_price": "",
                "drink_from_year": "",
                "drink_until_year": "",
            },
        )
        self.assertEqual(status, 200)
        wine_id = added["wine"]["id"]
        self.assertIsNone(added["wine"]["vivino_price_estimate"])
        self.assertIsNone(added["wine"]["purchase_price"])

        # Subsequent DB updates (update, adjust) must also succeed without float('') error
        status, updated = await async_handle_pwa_post(
            self.hass,
            "update",
            {
                "wine_id": wine_id,
                "updates": {
                    "general_notes": "Crisp passionfruit and lime.",
                    "purchase_price": "",
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["wine"]["general_notes"], "Crisp passionfruit and lime.")

        status, adjusted = await async_handle_pwa_post(
            self.hass, "adjust", {"wine_id": wine_id, "delta": 1}
        )
        self.assertEqual(status, 200)
        self.assertEqual(adjusted["wine"]["quantity"], 3)

        app_js = (MOBILE_DIR / "app.js").read_text(encoding="utf-8")
        html = (MOBILE_DIR / "index.html").read_text(encoding="utf-8")
        css = (MOBILE_DIR / "styles.css").read_text(encoding="utf-8")

        # 2. Splash screen shows version in small font
        self.assertIn("ls-splash-version", html)
        self.assertIn(f"v{VERSION}", html)

        # 3. Full-screen pages (no bottom-sheet overlay handle, 100dvh surface, border-radius: 0)
        self.assertNotIn('<div class="sheet-handle"></div>', app_js)
        self.assertIn("height: 100dvh;", css)
        self.assertIn("border-radius: 0;", css)

        # 4. Main Cellar list removed +/- stepper buttons, while Details still has +/- buttons
        bottle_list_fn = app_js.split("_renderBottleListItems(wines) {")[1].split("_renderCellarView() {")[0]
        self.assertNotIn("data-step-minus", bottle_list_fn)
        self.assertNotIn("data-step-plus", bottle_list_fn)
        self.assertIn("pill-qty", bottle_list_fn)
        self.assertIn('id="btn-detail-minus"', app_js)
        self.assertIn('id="btn-detail-plus"', app_js)

        # 5. Master Wine Notes textarea in Details scales automatically with text
        self.assertIn('id="detail-master-notes"', app_js)
        self.assertIn("_autoResizeTextarea", app_js)
        self.assertIn("_autoResizeTextareas", app_js)
        self.assertIn("_sanitizeWinePayload", app_js)


if __name__ == "__main__":
    unittest.main()

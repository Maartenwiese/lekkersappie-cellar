"""Coordinator for Wine Inventory database, Gemini scanner, and Vivino lookups."""

from __future__ import annotations

from collections.abc import Callable
import csv
import json
import logging
from pathlib import Path
from typing import Any

from .const import (
    CONF_CELLAR_NAME,
    CONF_CURRENCY,
    CONF_GEMINI_API_KEY,
    CONF_GEMINI_MODEL,
    CONF_HUMIDITY_ENTITY,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_TEMPERATURE_ENTITY,
    CONF_VIVINO_COUNTRY_CODE,
    CONF_VIVINO_FALLBACK_TO_GEMINI,
    DB_FILENAME,
    DEFAULT_CELLAR_NAME,
    DEFAULT_CURRENCY,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_LOW_STOCK_THRESHOLD,
    DEFAULT_VIVINO_COUNTRY_CODE,
    DEFAULT_VIVINO_FALLBACK_TO_GEMINI,
    EVENT_BOTTLE_ADDED,
    EVENT_BOTTLE_CONSUMED,
    EVENT_DRINK_WINDOW_ALERT,
    EVENT_QUANTITY_ADJUSTED,
    EVENT_STOCK_LOW,
    EVENT_WINE_UPDATED,
    EXPORTS_SUBDIR,
    STORAGE_DIR_NAME,
)
from .database import WineDatabase, utc_now_iso
from .scanner import (
    async_estimate_rating_via_gemini,
    async_scan_bottle_label,
    parse_image_data_uri,
    save_bottle_cover_image,
)
from .vivino import async_lookup_vivino

_LOGGER = logging.getLogger(__name__)


class WineInventoryCoordinator:
    """Manages SQLite persistence, Gemini scanning, Vivino enrichment, and HA state updates."""

    def __init__(
        self,
        hass: Any,
        entry_id: str,
        config: dict[str, Any],
        session_getter: Callable[[Any], Any] | None = None,
    ) -> None:
        """Initialize the Wine Inventory coordinator."""
        self.hass = hass
        self.entry_id = entry_id
        self.config = dict(config)
        self._session_getter = session_getter

        config_dir = Path(getattr(hass.config, "config_dir", "."))
        self.db_path = config_dir / STORAGE_DIR_NAME / DB_FILENAME
        self.db = WineDatabase(self.db_path)

        self.statistics: dict[str, Any] = {}
        self.wines: list[dict[str, Any]] = []
        self._listeners: list[Callable[[], None]] = []
        self._event_callbacks: list[Callable[[str, dict[str, Any]], None]] = []

    @property
    def cellar_name(self) -> str:
        """Return configured cellar name."""
        return str(self.config.get(CONF_CELLAR_NAME) or DEFAULT_CELLAR_NAME)

    @property
    def currency(self) -> str:
        """Return configured currency code."""
        return str(self.config.get(CONF_CURRENCY) or DEFAULT_CURRENCY)

    @property
    def gemini_api_key(self) -> str:
        """Return configured Gemini API key."""
        return str(self.config.get(CONF_GEMINI_API_KEY) or "")

    @property
    def gemini_model(self) -> str:
        """Return configured Gemini model identifier."""
        return str(self.config.get(CONF_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL)

    @property
    def vivino_country_code(self) -> str:
        """Return configured Vivino country code."""
        return str(self.config.get(CONF_VIVINO_COUNTRY_CODE) or DEFAULT_VIVINO_COUNTRY_CODE)

    @property
    def vivino_fallback_to_gemini(self) -> bool:
        """Return whether to estimate rating via Gemini when Vivino rate-limits."""
        return bool(
            self.config.get(
                CONF_VIVINO_FALLBACK_TO_GEMINI,
                DEFAULT_VIVINO_FALLBACK_TO_GEMINI,
            )
        )

    @property
    def low_stock_threshold(self) -> int:
        """Return configured low-stock bottle threshold."""
        return int(self.config.get(CONF_LOW_STOCK_THRESHOLD, DEFAULT_LOW_STOCK_THRESHOLD))

    @property
    def temperature_entity(self) -> str:
        """Return optional linked cellar temperature sensor entity_id."""
        return str(self.config.get(CONF_TEMPERATURE_ENTITY) or "")

    @property
    def humidity_entity(self) -> str:
        """Return optional linked cellar humidity sensor entity_id."""
        return str(self.config.get(CONF_HUMIDITY_ENTITY) or "")

    def update_config(self, new_config: dict[str, Any]) -> None:
        """Update runtime configuration from ConfigEntry data + options."""
        self.config = dict(new_config)
        self._notify_listeners()

    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register an entity state update listener."""
        self._listeners.append(update_callback)

        def _remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    def async_add_event_listener(
        self, event_callback: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a listener for native Home Assistant EventEntity triggers."""
        self._event_callbacks.append(event_callback)

        def _remove() -> None:
            if event_callback in self._event_callbacks:
                self._event_callbacks.remove(event_callback)

        return _remove

    def _notify_listeners(self) -> None:
        """Notify all attached sensor entities of updated inventory state."""
        for callback in list(self._listeners):
            callback()

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to registered EventEntity instances."""
        for callback in list(self._event_callbacks):
            callback(event_type, data)

    def _get_http_session(self) -> Any:
        """Obtain the shared Home Assistant aiohttp ClientSession."""
        if self._session_getter is not None:
            return self._session_getter(self.hass)
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        return async_get_clientsession(self.hass)

    async def async_initialize(self) -> None:
        """Initialize the SQLite schema and load initial statistics."""
        await self.hass.async_add_executor_job(self.db.initialize)
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Reload wine list and aggregate statistics from SQLite."""
        self.wines = await self.hass.async_add_executor_job(self.db.list_wines)
        self.statistics = await self.hass.async_add_executor_job(self.db.get_statistics)
        self._notify_listeners()

    async def async_checkpoint_database(self) -> None:
        """Flush SQLite WAL checkpoint for safe Home Assistant backups."""
        await self.hass.async_add_executor_job(self.db.checkpoint_wal)

    async def _async_resolve_camera_image(
        self, camera_entity_id: str
    ) -> tuple[str, bytes]:
        """Grab a still frame from a Home Assistant camera.* or image.* entity."""
        domain = camera_entity_id.split(".", 1)[0].lower()
        if domain == "camera":
            from homeassistant.components.camera import async_get_image

            image = await async_get_image(self.hass, camera_entity_id)
            return image.content_type or "image/jpeg", image.content
        if domain == "image":
            from homeassistant.components.image import async_get_image as async_get_image_entity

            image = await async_get_image_entity(self.hass, camera_entity_id)
            return image.content_type or "image/jpeg", image.content
        raise ValueError(
            f"Unsupported entity '{camera_entity_id}'. Expected a camera.* or image.* entity."
        )

    async def async_scan_bottle(
        self,
        *,
        image_data: str | None = None,
        camera_entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Scan a bottle image with Gemini Flash-Lite, enrich via Vivino, and check duplicates."""
        if image_data:
            mime_type, raw_bytes = parse_image_data_uri(image_data)
        elif camera_entity_id:
            mime_type, raw_bytes = await self._async_resolve_camera_image(camera_entity_id)
        else:
            raise ValueError("Either 'image_data' or 'camera_entity_id' must be provided.")

        config_dir = Path(getattr(self.hass.config, "config_dir", "."))
        saved_image_url = await self.hass.async_add_executor_job(
            save_bottle_cover_image,
            config_dir,
            raw_bytes,
            mime_type,
        )

        session = self._get_http_session()
        extracted = await async_scan_bottle_label(
            session,
            api_key=self.gemini_api_key,
            image_bytes=raw_bytes,
            mime_type=mime_type,
            model=self.gemini_model,
        )
        extracted["image_url"] = saved_image_url

        vivino_result = await async_lookup_vivino(
            session,
            winery=extracted.get("winery", ""),
            name=extracted.get("name", ""),
            vintage=extracted.get("vintage"),
            country_code=self.vivino_country_code,
            currency_code=self.currency,
        )

        best_match = vivino_result.get("best_match")
        if best_match is None and self.vivino_fallback_to_gemini:
            best_match = await async_estimate_rating_via_gemini(
                session,
                api_key=self.gemini_api_key,
                winery=extracted.get("winery", ""),
                name=extracted.get("name", ""),
                vintage=extracted.get("vintage"),
                model=self.gemini_model,
                currency=self.currency,
            )

        if best_match:
            extracted["vivino_rating"] = best_match.get("vivino_rating")
            extracted["vivino_ratings_count"] = best_match.get("vivino_ratings_count")
            extracted["vivino_url"] = best_match.get("vivino_url") or vivino_result.get(
                "search_url", ""
            )
            extracted["vivino_price_estimate"] = best_match.get("vivino_price_estimate")
            extracted["rating_source"] = best_match.get("rating_source", "vivino")
            if not extracted.get("region") and best_match.get("region"):
                extracted["region"] = best_match["region"]
            if not extracted.get("country") and best_match.get("country"):
                extracted["country"] = best_match["country"]
        else:
            extracted["vivino_rating"] = None
            extracted["vivino_ratings_count"] = None
            extracted["vivino_url"] = vivino_result.get("search_url", "")
            extracted["vivino_price_estimate"] = None
            extracted["rating_source"] = ""

        existing_match = await self.hass.async_add_executor_job(
            self.db.find_matching_wine,
            extracted.get("winery", ""),
            extracted.get("name", ""),
            extracted.get("vintage"),
        )

        return {
            "extracted": extracted,
            "vivino_status": vivino_result.get("status", "unknown"),
            "vivino_candidates": vivino_result.get("candidates", []),
            "existing_wine": existing_match,
            "suggested_added_at": utc_now_iso(),
        }

    async def async_add_wine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Add a wine or increment an existing wine with batch metadata."""
        wine = await self.hass.async_add_executor_job(
            lambda: self.db.add_or_increment_wine(
                wine_id=payload.get("wine_id"),
                winery=str(payload.get("winery") or "Unknown Winery"),
                name=str(payload.get("name") or "Unnamed Wine"),
                vintage=payload.get("vintage"),
                wine_type=str(payload.get("wine_type") or "red"),
                varietal=str(payload.get("varietal") or ""),
                region=str(payload.get("region") or ""),
                country=str(payload.get("country") or ""),
                alcohol_pct=payload.get("alcohol_pct"),
                bottle_size_ml=int(payload.get("bottle_size_ml") or 750),
                vivino_rating=payload.get("vivino_rating"),
                vivino_ratings_count=payload.get("vivino_ratings_count"),
                vivino_url=str(payload.get("vivino_url") or ""),
                vivino_price_estimate=payload.get("vivino_price_estimate"),
                rating_source=str(payload.get("rating_source") or ""),
                drink_from_year=payload.get("drink_from_year"),
                drink_until_year=payload.get("drink_until_year"),
                drink_window_note=str(payload.get("drink_window_note") or ""),
                food_pairings=payload.get("food_pairings"),
                general_notes=str(payload.get("general_notes") or ""),
                personal_rating=payload.get("personal_rating"),
                image_url=str(payload.get("image_url") or ""),
                quantity=int(payload.get("quantity") or 1),
                added_at=payload.get("added_at"),
                purchase_location=str(payload.get("purchase_location") or ""),
                purchase_price=payload.get("purchase_price"),
                storage_location=str(payload.get("storage_location") or ""),
                batch_notes=str(payload.get("batch_notes") or payload.get("notes") or ""),
            )
        )
        await self.async_refresh()
        self._emit_event(
            EVENT_BOTTLE_ADDED,
            {
                "wine_id": wine["id"],
                "winery": wine["winery"],
                "name": wine["name"],
                "vintage": wine["vintage"],
                "quantity_added": int(payload.get("quantity") or 1),
                "total_quantity": wine["quantity"],
                "purchase_location": payload.get("purchase_location") or "",
                "storage_location": payload.get("storage_location") or "",
            },
        )
        if wine.get("drink_status") == "drink_soon":
            self._emit_event(
                EVENT_DRINK_WINDOW_ALERT,
                {
                    "wine_id": wine["id"],
                    "winery": wine["winery"],
                    "name": wine["name"],
                    "drink_until_year": wine.get("drink_until_year"),
                },
            )
        return wine

    async def async_adjust_quantity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Adjust bottle quantity (+N or -N) and emit corresponding events."""
        wine_id = int(payload["wine_id"])
        delta = int(payload["delta"])
        wine = await self.hass.async_add_executor_job(
            lambda: self.db.adjust_quantity(
                wine_id=wine_id,
                delta=delta,
                batch_id=payload.get("batch_id"),
                added_at=payload.get("added_at"),
                purchase_location=str(payload.get("purchase_location") or ""),
                purchase_price=payload.get("purchase_price"),
                storage_location=str(payload.get("storage_location") or ""),
                drink_window_note=str(payload.get("drink_window_note") or ""),
                notes=str(payload.get("notes") or ""),
                personal_rating=payload.get("personal_rating"),
            )
        )
        await self.async_refresh()

        event_type = (
            EVENT_BOTTLE_ADDED
            if delta > 0
            else EVENT_BOTTLE_CONSUMED
            if delta < 0
            else EVENT_QUANTITY_ADJUSTED
        )
        self._emit_event(
            event_type,
            {
                "wine_id": wine["id"],
                "winery": wine["winery"],
                "name": wine["name"],
                "vintage": wine["vintage"],
                "delta": delta,
                "total_quantity": wine["quantity"],
            },
        )
        if delta < 0 and 0 < int(wine["quantity"]) <= self.low_stock_threshold:
            self._emit_event(
                EVENT_STOCK_LOW,
                {
                    "wine_id": wine["id"],
                    "winery": wine["winery"],
                    "name": wine["name"],
                    "remaining_quantity": wine["quantity"],
                },
            )
        return wine

    async def async_update_wine(
        self,
        wine_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update wine metadata and refresh state."""
        wine = await self.hass.async_add_executor_job(
            self.db.update_wine,
            int(wine_id),
            updates,
        )
        await self.async_refresh()
        self._emit_event(
            EVENT_WINE_UPDATED,
            {
                "wine_id": wine["id"],
                "winery": wine["winery"],
                "name": wine["name"],
            },
        )
        return wine

    async def async_delete_wine(self, wine_id: int) -> bool:
        """Delete a wine from the database and refresh state."""
        deleted = await self.hass.async_add_executor_job(
            self.db.delete_wine,
            int(wine_id),
        )
        await self.async_refresh()
        return deleted

    async def async_refresh_vivino(self, wine_id: int | None = None) -> dict[str, Any]:
        """Re-fetch Vivino ratings for one wine or all in-stock wines."""
        session = self._get_http_session()
        if wine_id is not None:
            detail = await self.hass.async_add_executor_job(
                self.db.get_wine_detail, int(wine_id)
            )
            targets = [detail] if detail else []
        else:
            targets = [w for w in self.wines if int(w.get("quantity", 0)) > 0]

        updated_count = 0
        for item in targets:
            if not item:
                continue
            res = await async_lookup_vivino(
                session,
                winery=item["winery"],
                name=item["name"],
                vintage=item.get("vintage"),
                country_code=self.vivino_country_code,
                currency_code=self.currency,
            )
            best = res.get("best_match")
            if best is None and self.vivino_fallback_to_gemini:
                best = await async_estimate_rating_via_gemini(
                    session,
                    api_key=self.gemini_api_key,
                    winery=item["winery"],
                    name=item["name"],
                    vintage=item.get("vintage"),
                    model=self.gemini_model,
                    currency=self.currency,
                )
            if best:
                updates: dict[str, Any] = {
                    "vivino_rating": best.get("vivino_rating"),
                    "vivino_ratings_count": best.get("vivino_ratings_count"),
                    "vivino_url": best.get("vivino_url") or item.get("vivino_url", ""),
                    "vivino_price_estimate": best.get("vivino_price_estimate"),
                    "rating_source": best.get("rating_source", "vivino"),
                }
                if not item.get("image_url") and best.get("vivino_image_url"):
                    updates["image_url"] = best["vivino_image_url"]
                await self.hass.async_add_executor_job(
                    self.db.update_wine,
                    int(item["id"]),
                    updates,
                )
                updated_count += 1

        await self.async_refresh()
        return {"updated_count": updated_count, "checked_count": len(targets)}

    async def async_export_inventory(self, export_format: str = "csv") -> dict[str, Any]:
        """Export full wine inventory to <config>/www/wine_inventory/exports/."""
        config_dir = Path(getattr(self.hass.config, "config_dir", "."))
        exports_dir = config_dir / EXPORTS_SUBDIR
        fmt = export_format.lower().strip()
        wines = await self.hass.async_add_executor_job(self.db.list_wines)

        def _write_export() -> tuple[str, str]:
            exports_dir.mkdir(parents=True, exist_ok=True)
            if fmt == "json":
                filename = "wine_inventory_export.json"
                target = exports_dir / filename
                target.write_text(json.dumps(wines, indent=2), encoding="utf-8")
            else:
                filename = "wine_inventory_export.csv"
                target = exports_dir / filename
                fieldnames = [
                    "id",
                    "winery",
                    "name",
                    "vintage",
                    "wine_type",
                    "varietal",
                    "region",
                    "country",
                    "quantity",
                    "vivino_rating",
                    "vivino_ratings_count",
                    "personal_rating",
                    "drink_from_year",
                    "drink_until_year",
                    "drink_status",
                    "last_purchase_location",
                    "last_storage_location",
                    "last_purchase_price",
                    "general_notes",
                    "vivino_url",
                ]
                with target.open("w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.DictWriter(
                        csvfile, fieldnames=fieldnames, extrasaction="ignore"
                    )
                    writer.writeheader()
                    for w in wines:
                        writer.writerow(w)
            return str(target), f"/local/wine_inventory/exports/{filename}"

        file_path, download_url = await self.hass.async_add_executor_job(_write_export)
        return {
            "file_path": file_path,
            "download_url": download_url,
            "exported_wines": len(wines),
        }

    async def async_create_backup(self) -> dict[str, Any]:
        """Create a full .zip backup of SQLite db, metadata.json, and cover images."""
        from .backup import create_backup_archive

        config_dir = Path(getattr(self.hass.config, "config_dir", "."))
        return await self.hass.async_add_executor_job(
            create_backup_archive,
            config_dir,
            self.db,
        )

    async def async_restore_backup(self, zip_source: Path | bytes | str) -> dict[str, Any]:
        """Restore database and cover images from a .zip backup archive."""
        from .backup import restore_backup_archive

        config_dir = Path(getattr(self.hass.config, "config_dir", "."))
        res = await self.hass.async_add_executor_job(
            restore_backup_archive,
            config_dir,
            self.db,
            zip_source,
        )
        await self.async_refresh()
        return res

    async def async_import_wines(
        self,
        payload: list[dict[str, Any]] | dict[str, Any] | bytes | str,
        format_type: str = "auto",
    ) -> dict[str, Any]:
        """Import wines from JSON list, CSV, or ZIP archive."""
        from .backup import import_wines_archive

        config_dir = Path(getattr(self.hass.config, "config_dir", "."))
        res = await self.hass.async_add_executor_job(
            import_wines_archive,
            config_dir,
            self.db,
            payload,
            format_type,
        )
        await self.async_refresh()
        return res

    async def async_list_backups(self) -> list[dict[str, Any]]:
        """List available backups on disk."""
        from .backup import list_available_backups

        config_dir = Path(getattr(self.hass.config, "config_dir", "."))
        return await self.hass.async_add_executor_job(
            list_available_backups,
            config_dir,
        )

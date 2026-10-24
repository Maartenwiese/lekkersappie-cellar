"""WebSocket API commands for the Wine Inventory frontend card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import WineInventoryCoordinator


def _get_coordinator(
    hass: HomeAssistant, entry_id: str | None = None
) -> WineInventoryCoordinator:
    """Resolve the active WineInventoryCoordinator instance."""
    domain_data = hass.data.get(DOMAIN) or {}
    if entry_id and entry_id in domain_data:
        return domain_data[entry_id]["coordinator"]
    for val in domain_data.values():
        if isinstance(val, dict) and "coordinator" in val:
            return val["coordinator"]
    raise ValueError("No active Wine Inventory integration instance found.")


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all Wine Inventory WebSocket commands with Home Assistant."""
    websocket_api.async_register_command(hass, ws_list_wines)
    websocket_api.async_register_command(hass, ws_get_wine_detail)
    websocket_api.async_register_command(hass, ws_scan_bottle)
    websocket_api.async_register_command(hass, ws_add_wine)
    websocket_api.async_register_command(hass, ws_adjust_quantity)
    websocket_api.async_register_command(hass, ws_update_wine)
    websocket_api.async_register_command(hass, ws_delete_wine)
    websocket_api.async_register_command(hass, ws_refresh_vivino)
    websocket_api.async_register_command(hass, ws_create_backup)
    websocket_api.async_register_command(hass, ws_restore_backup)
    websocket_api.async_register_command(hass, ws_import_wines)
    websocket_api.async_register_command(hass, ws_list_backups)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/list",
        vol.Optional("entry_id"): str,
        vol.Optional("include_out_of_stock", default=True): bool,
        vol.Optional("wine_type"): vol.Any(str, None),
        vol.Optional("search"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_list_wines(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return full wine list, cellar statistics, and autocomplete metadata."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        wines = await hass.async_add_executor_job(
            lambda: coordinator.db.list_wines(
                include_out_of_stock=bool(msg.get("include_out_of_stock", True)),
                wine_type=msg.get("wine_type"),
                search=msg.get("search"),
            )
        )
        connection.send_result(
            msg["id"],
            {
                "cellar_name": coordinator.cellar_name,
                "currency": coordinator.currency,
                "temperature_entity": coordinator.temperature_entity,
                "humidity_entity": coordinator.humidity_entity,
                "statistics": coordinator.statistics,
                "wines": wines,
            },
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "list_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/get_detail",
        vol.Required("wine_id"): int,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_wine_detail(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return single wine detail with purchase batches and notes timeline."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        detail = await hass.async_add_executor_job(
            coordinator.db.get_wine_detail,
            int(msg["wine_id"]),
        )
        if detail is None:
            connection.send_error(msg["id"], "not_found", "Wine not found")
            return
        connection.send_result(msg["id"], {"wine": detail})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "detail_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/scan_bottle",
        vol.Optional("image_data"): str,
        vol.Optional("camera_entity_id"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_scan_bottle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Scan a wine bottle photo via Gemini Flash-Lite + Vivino lookup."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        result = await coordinator.async_scan_bottle(
            image_data=msg.get("image_data"),
            camera_entity_id=msg.get("camera_entity_id"),
        )
        connection.send_result(msg["id"], result)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "scan_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/add_wine",
        vol.Optional("wine_id"): vol.Any(int, None),
        vol.Required("winery"): str,
        vol.Required("name"): str,
        vol.Optional("vintage"): vol.Any(int, None),
        vol.Optional("wine_type", default="red"): str,
        vol.Optional("varietal", default=""): str,
        vol.Optional("region", default=""): str,
        vol.Optional("country", default=""): str,
        vol.Optional("alcohol_pct"): vol.Any(float, int, None),
        vol.Optional("bottle_size_ml", default=750): int,
        vol.Optional("vivino_rating"): vol.Any(float, int, None),
        vol.Optional("vivino_ratings_count"): vol.Any(int, None),
        vol.Optional("vivino_url", default=""): str,
        vol.Optional("vivino_price_estimate"): vol.Any(float, int, None),
        vol.Optional("rating_source", default=""): str,
        vol.Optional("drink_from_year"): vol.Any(int, None),
        vol.Optional("drink_until_year"): vol.Any(int, None),
        vol.Optional("drink_window_note", default=""): str,
        vol.Optional("food_pairings"): vol.Any(list, str, None),
        vol.Optional("general_notes", default=""): str,
        vol.Optional("personal_rating"): vol.Any(float, int, None),
        vol.Optional("image_url", default=""): str,
        vol.Optional("quantity", default=1): int,
        vol.Optional("added_at"): vol.Any(str, None),
        vol.Optional("purchase_location", default=""): str,
        vol.Optional("purchase_price"): vol.Any(float, int, None),
        vol.Optional("storage_location", default=""): str,
        vol.Optional("batch_notes", default=""): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_add_wine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a new wine or add a batch to an existing wine."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        wine = await coordinator.async_add_wine(msg)
        connection.send_result(
            msg["id"],
            {"wine": wine, "statistics": coordinator.statistics},
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "add_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/adjust_quantity",
        vol.Required("wine_id"): int,
        vol.Required("delta"): int,
        vol.Optional("batch_id"): vol.Any(int, None),
        vol.Optional("added_at"): vol.Any(str, None),
        vol.Optional("purchase_location", default=""): str,
        vol.Optional("purchase_price"): vol.Any(float, int, None),
        vol.Optional("storage_location", default=""): str,
        vol.Optional("drink_window_note", default=""): str,
        vol.Optional("notes", default=""): str,
        vol.Optional("personal_rating"): vol.Any(float, int, None),
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_adjust_quantity(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Adjust bottle count (+N adds a batch, -N consumes a bottle with optional tasting note)."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        wine = await coordinator.async_adjust_quantity(msg)
        connection.send_result(
            msg["id"],
            {"wine": wine, "statistics": coordinator.statistics},
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "adjust_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/update_wine",
        vol.Required("wine_id"): int,
        vol.Required("updates"): dict,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_update_wine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update wine fields (notes overview, drink window, Vivino fields, etc.)."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        wine = await coordinator.async_update_wine(
            int(msg["wine_id"]),
            dict(msg["updates"]),
        )
        connection.send_result(
            msg["id"],
            {"wine": wine, "statistics": coordinator.statistics},
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "update_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/delete_wine",
        vol.Required("wine_id"): int,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_wine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a wine record permanently."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        deleted = await coordinator.async_delete_wine(int(msg["wine_id"]))
        connection.send_result(
            msg["id"],
            {"deleted": deleted, "statistics": coordinator.statistics},
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "delete_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/refresh_vivino",
        vol.Optional("wine_id"): vol.Any(int, None),
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_refresh_vivino(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Refresh Vivino rating and price estimate for one or all wines."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        res = await coordinator.async_refresh_vivino(msg.get("wine_id"))
        connection.send_result(msg["id"], res)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "vivino_refresh_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/create_backup",
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_create_backup(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a complete .zip backup containing database, metadata, and images."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        res = await coordinator.async_create_backup()
        connection.send_result(msg["id"], res)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "backup_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/restore_backup",
        vol.Optional("file_path"): str,
        vol.Optional("zip_data"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_restore_backup(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Restore database and images from a backup .zip file path or base64 data."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        zip_data = msg.get("zip_data")
        file_path = msg.get("file_path")
        if zip_data:
            import base64

            if "," in zip_data:
                zip_data = zip_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(zip_data)
            res = await coordinator.async_restore_backup(raw_bytes)
        elif file_path:
            res = await coordinator.async_restore_backup(file_path)
        else:
            raise ValueError("Either 'file_path' or 'zip_data' must be provided.")

        connection.send_result(msg["id"], res)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "restore_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/import_wines",
        vol.Optional("source"): str,
        vol.Optional("file_data"): str,
        vol.Optional("wines"): list,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_import_wines(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Import wines from file path, base64 archive, or JSON list."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        file_data = msg.get("file_data")
        source = msg.get("source")
        wines_list = msg.get("wines")

        if file_data:
            import base64

            if "," in file_data:
                file_data = file_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(file_data)
            res = await coordinator.async_import_wines(raw_bytes)
        elif source:
            res = await coordinator.async_import_wines(source)
        elif wines_list is not None:
            res = await coordinator.async_import_wines(wines_list)
        else:
            raise ValueError("No import payload provided.")

        connection.send_result(msg["id"], res)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "import_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wine_inventory/list_backups",
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_list_backups(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List available backups on disk."""
    try:
        coordinator = _get_coordinator(hass, msg.get("entry_id"))
        res = await coordinator.async_list_backups()
        connection.send_result(msg["id"], {"backups": res})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "list_backups_failed", str(err))

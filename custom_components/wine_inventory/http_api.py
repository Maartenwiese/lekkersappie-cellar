"""HTTP REST API and Redirect Views for the Standalone Lekkersappie Mobile Web App (PWA)."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

try:
    from homeassistant.components.http import HomeAssistantView
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import area_registry as ar
except ImportError:  # pragma: no cover - allows standalone unit test imports
    HomeAssistant = Any  # type: ignore[assignment,misc]
    ar = None  # type: ignore[assignment]

    class HomeAssistantView:  # type: ignore[no-redef]
        """Minimal stub base class when homeassistant runtime is absent."""

        url: str = ""
        name: str = ""
        requires_auth: bool = False

        @staticmethod
        def json(
            result: Any,
            status_code: int = 200,
        ) -> web.Response:
            return web.Response(
                text=json.dumps(result),
                status=status_code,
                content_type="application/json",
            )

from .const import DOMAIN, MOBILE_APP_URL_BASE, VERSION
from .coordinator import WineInventoryCoordinator

_LOGGER = logging.getLogger(__name__)

DEFAULT_STORAGE_AREAS = [
    "Wine Cellar",
    "Wine Fridge",
    "Kitchen Rack",
    "Basement",
    "Dining Room",
    "Pantry",
    "Garage",
]


def _resolve_coordinator(
    hass: HomeAssistant, entry_id: str | None = None
) -> WineInventoryCoordinator:
    """Resolve active WineInventoryCoordinator from hass.data."""
    domain_data = getattr(hass, "data", {}).get(DOMAIN) or {}
    if entry_id and entry_id in domain_data:
        return domain_data[entry_id]["coordinator"]
    for val in domain_data.values():
        if isinstance(val, dict) and "coordinator" in val:
            return val["coordinator"]
    raise ValueError("No active Wine Inventory integration instance found.")


def _resolve_available_areas(
    hass: HomeAssistant, coordinator: WineInventoryCoordinator
) -> list[str]:
    """Combine Home Assistant areas, database storage locations, and default cellar areas."""
    area_set: set[str] = set()
    try:
        if ar is not None:
            reg = ar.async_get(hass)
            for area in reg.async_list_areas():
                if getattr(area, "name", None):
                    area_set.add(str(area.name).strip())
    except Exception:  # noqa: BLE001
        pass

    for loc in (coordinator.statistics or {}).get("known_storage_locations") or []:
        if loc and str(loc).strip():
            area_set.add(str(loc).strip())

    for default_loc in DEFAULT_STORAGE_AREAS:
        area_set.add(default_loc)

    return sorted(area_set, key=str.lower)


def _resolve_sensor_display(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Read formatted state + unit from hass.states if configured."""
    if not entity_id or not hasattr(hass, "states") or hass.states is None:
        return None
    st = hass.states.get(entity_id)
    if not st or st.state in ("unknown", "unavailable", None):
        return None
    unit = (getattr(st, "attributes", {}) or {}).get("unit_of_measurement", "")
    return f"{st.state} {unit}".strip()


async def async_handle_pwa_get(
    hass: HomeAssistant,
    action: str,
    query: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Execute GET actions for the standalone mobile PWA."""
    coordinator = _resolve_coordinator(hass, query.get("entry_id"))

    if action == "state":
        include_out_of_stock = str(query.get("include_out_of_stock", "true")).lower() != "false"
        wine_type = query.get("wine_type") or None
        search = query.get("search") or None

        if hasattr(hass, "async_add_executor_job"):
            wines = await hass.async_add_executor_job(
                lambda: coordinator.db.list_wines(
                    include_out_of_stock=include_out_of_stock,
                    wine_type=wine_type,
                    search=search,
                )
            )
        else:
            wines = coordinator.db.list_wines(
                include_out_of_stock=include_out_of_stock,
                wine_type=wine_type,
                search=search,
            )

        return 200, {
            "version": VERSION,
            "cellar_name": coordinator.cellar_name,
            "currency": coordinator.currency,
            "temperature_entity": coordinator.temperature_entity,
            "humidity_entity": coordinator.humidity_entity,
            "temperature_display": _resolve_sensor_display(
                hass, coordinator.temperature_entity
            ),
            "humidity_display": _resolve_sensor_display(
                hass, coordinator.humidity_entity
            ),
            "areas": _resolve_available_areas(hass, coordinator),
            "statistics": coordinator.statistics,
            "wines": wines,
        }

    if action == "detail":
        raw_id = query.get("wine_id")
        if not raw_id:
            return 400, {"error": "Missing required query parameter: wine_id"}
        wine_id = int(raw_id)
        if hasattr(hass, "async_add_executor_job"):
            detail = await hass.async_add_executor_job(
                coordinator.db.get_wine_detail, wine_id
            )
        else:
            detail = coordinator.db.get_wine_detail(wine_id)
        if detail is None:
            return 404, {"error": "Wine not found"}
        return 200, {"wine": detail}

    return 404, {"error": f"Unknown GET action: {action}"}


async def async_handle_pwa_post(
    hass: HomeAssistant,
    action: str,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Execute POST actions for the standalone mobile PWA."""
    coordinator = _resolve_coordinator(hass, payload.get("entry_id"))

    if action == "scan":
        res = await coordinator.async_scan_bottle(
            image_data=payload.get("image_data"),
            camera_entity_id=payload.get("camera_entity_id"),
        )
        return 200, res

    if action == "add":
        wine = await coordinator.async_add_wine(dict(payload))
        return 200, {"wine": wine, "statistics": coordinator.statistics}

    if action == "adjust":
        wine = await coordinator.async_adjust_quantity(dict(payload))
        return 200, {"wine": wine, "statistics": coordinator.statistics}

    if action == "update":
        wine_id = int(payload["wine_id"])
        updates = dict(payload.get("updates") or {})
        wine = await coordinator.async_update_wine(wine_id, updates)
        return 200, {"wine": wine, "statistics": coordinator.statistics}

    if action == "delete":
        wine_id = int(payload["wine_id"])
        deleted = await coordinator.async_delete_wine(wine_id)
        return 200, {"deleted": deleted, "statistics": coordinator.statistics}

    if action == "research":
        wine_id = int(payload["wine_id"])
        res = await coordinator.async_research_wine(wine_id)
        return 200, res

    if action == "link_vivino":
        wine_id = int(payload["wine_id"])
        url = str(payload.get("url") or "")
        res = await coordinator.async_link_vivino_url(wine_id, url)
        return 200, {**res, "statistics": coordinator.statistics}

    if action == "unlink_vivino":
        wine_id = int(payload["wine_id"])
        wine = await coordinator.async_unlink_vivino(wine_id)
        return 200, {"wine": wine, "statistics": coordinator.statistics}

    if action == "refresh_vivino":
        raw_id = payload.get("wine_id")
        wine_id = int(raw_id) if raw_id is not None else None
        res = await coordinator.async_refresh_vivino(wine_id)
        return 200, res

    return 404, {"error": f"Unknown POST action: {action}"}


class WineInventoryMobileRedirectView(HomeAssistantView):
    """Redirect /lekkersappie to /lekkersappie/index.html for instant mobile access."""

    url = MOBILE_APP_URL_BASE
    name = "api:wine_inventory:mobile_redirect"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Redirect bare /lekkersappie path to /lekkersappie/index.html."""
        raise web.HTTPFound(f"{MOBILE_APP_URL_BASE}/index.html")


class WineInventoryPwaApiView(HomeAssistantView):
    """REST endpoint for the standalone Lekkersappie Mobile PWA."""

    url = "/api/wine_inventory/pwa/{action}"
    name = "api:wine_inventory:pwa_api"
    requires_auth = False

    async def get(self, request: web.Request, action: str) -> web.Response:
        """Handle GET requests from the mobile PWA."""
        hass: HomeAssistant = request.app["hass"]
        try:
            status, data = await async_handle_pwa_get(
                hass, action, dict(request.query)
            )
            return self.json(data, status_code=status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Mobile PWA GET %s failed: %s", action, err)
            return self.json({"error": str(err)}, status_code=500)

    async def post(self, request: web.Request, action: str) -> web.Response:
        """Handle POST requests from the mobile PWA."""
        hass: HomeAssistant = request.app["hass"]
        try:
            payload = await request.json() if request.can_read_body else {}
            status, data = await async_handle_pwa_post(
                hass, action, dict(payload or {})
            )
            return self.json(data, status_code=status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Mobile PWA POST %s failed: %s", action, err)
            return self.json({"error": str(err)}, status_code=500)


def async_register_http_views(hass: HomeAssistant) -> None:
    """Register HTTP views for the standalone mobile PWA."""
    if not hasattr(hass, "http") or hass.http is None:
        return
    hass.http.register_view(WineInventoryMobileRedirectView())
    hass.http.register_view(WineInventoryPwaApiView())

"""Constants for the Wine Inventory integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "wine_inventory"
NAME: Final = "Lekkersappie"
VERSION: Final = "0.2.2"

# Config & Options keys
CONF_CELLAR_NAME: Final = "cellar_name"
CONF_GEMINI_API_KEY: Final = "gemini_api_key"
CONF_GEMINI_MODEL: Final = "gemini_model"
CONF_CURRENCY: Final = "currency"
CONF_VIVINO_COUNTRY_CODE: Final = "vivino_country_code"
CONF_VIVINO_FALLBACK_TO_GEMINI: Final = "vivino_fallback_to_gemini"
CONF_TEMPERATURE_ENTITY: Final = "temperature_entity"
CONF_HUMIDITY_ENTITY: Final = "humidity_entity"
CONF_LOW_STOCK_THRESHOLD: Final = "low_stock_threshold"

# Defaults
DEFAULT_CELLAR_NAME: Final = "Lekkersappie"
DEFAULT_GEMINI_MODEL: Final = "gemini-3.8-flash-lite"
DEFAULT_CURRENCY: Final = "EUR"
DEFAULT_VIVINO_COUNTRY_CODE: Final = "NL"
DEFAULT_VIVINO_FALLBACK_TO_GEMINI: Final = True
DEFAULT_LOW_STOCK_THRESHOLD: Final = 2

# Storage & Static Paths
STORAGE_DIR_NAME: Final = "wine_inventory"
DB_FILENAME: Final = "wine_inventory.db"
COVERS_SUBDIR: Final = "www/wine_inventory/covers"
EXPORTS_SUBDIR: Final = "www/wine_inventory/exports"
FRONTEND_URL_BASE: Final = "/wine_inventory"
CARD_JS_FILENAME: Final = "wine-inventory-card.js"
CARD_RESOURCE_URL: Final = f"{FRONTEND_URL_BASE}/{CARD_JS_FILENAME}?v={VERSION}"

# Wine types
WINE_TYPE_RED: Final = "red"
WINE_TYPE_WHITE: Final = "white"
WINE_TYPE_ROSE: Final = "rose"
WINE_TYPE_SPARKLING: Final = "sparkling"
WINE_TYPE_DESSERT: Final = "dessert"
WINE_TYPE_FORTIFIED: Final = "fortified"

WINE_TYPES: Final[list[str]] = [
    WINE_TYPE_RED,
    WINE_TYPE_WHITE,
    WINE_TYPE_ROSE,
    WINE_TYPE_SPARKLING,
    WINE_TYPE_DESSERT,
    WINE_TYPE_FORTIFIED,
]

# Drinking window statuses
DRINK_STATUS_HOLD: Final = "hold"
DRINK_STATUS_READY: Final = "ready"
DRINK_STATUS_DRINK_SOON: Final = "drink_soon"
DRINK_STATUS_PAST_PEAK: Final = "past_peak"
DRINK_STATUS_UNKNOWN: Final = "unknown"

# Event types for EventEntity (homeassistant-ai/skills event.received pattern)
EVENT_BOTTLE_ADDED: Final = "bottle_added"
EVENT_BOTTLE_CONSUMED: Final = "bottle_consumed"
EVENT_QUANTITY_ADJUSTED: Final = "quantity_adjusted"
EVENT_WINE_UPDATED: Final = "wine_updated"
EVENT_STOCK_LOW: Final = "stock_low"
EVENT_DRINK_WINDOW_ALERT: Final = "drink_window_alert"

CELLAR_EVENT_TYPES: Final[list[str]] = [
    EVENT_BOTTLE_ADDED,
    EVENT_BOTTLE_CONSUMED,
    EVENT_QUANTITY_ADJUSTED,
    EVENT_WINE_UPDATED,
    EVENT_STOCK_LOW,
    EVENT_DRINK_WINDOW_ALERT,
]

# Service Names
SERVICE_SCAN_BOTTLE: Final = "scan_bottle"
SERVICE_ADD_WINE: Final = "add_wine"
SERVICE_ADJUST_QUANTITY: Final = "adjust_quantity"
SERVICE_UPDATE_WINE: Final = "update_wine"
SERVICE_REFRESH_VIVINO: Final = "refresh_vivino"
SERVICE_EXPORT_INVENTORY: Final = "export_inventory"

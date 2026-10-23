"""Config flow and Options flow for the Wine Inventory integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

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
    DEFAULT_CELLAR_NAME,
    DEFAULT_CURRENCY,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_LOW_STOCK_THRESHOLD,
    DEFAULT_VIVINO_COUNTRY_CODE,
    DEFAULT_VIVINO_FALLBACK_TO_GEMINI,
    DOMAIN,
)


def _build_schema(defaults: dict[str, Any], include_cellar_name: bool = True) -> vol.Schema:
    """Build Voluptuous schema for Config Flow and Options Flow."""
    fields: dict[Any, Any] = {}
    if include_cellar_name:
        fields[
            vol.Required(
                CONF_CELLAR_NAME,
                default=defaults.get(CONF_CELLAR_NAME, DEFAULT_CELLAR_NAME),
            )
        ] = str

    fields.update(
        {
            vol.Optional(
                CONF_GEMINI_API_KEY,
                default=defaults.get(CONF_GEMINI_API_KEY, ""),
            ): str,
            vol.Required(
                CONF_GEMINI_MODEL,
                default=defaults.get(CONF_GEMINI_MODEL, DEFAULT_GEMINI_MODEL),
            ): str,
            vol.Required(
                CONF_CURRENCY,
                default=defaults.get(CONF_CURRENCY, DEFAULT_CURRENCY),
            ): str,
            vol.Required(
                CONF_VIVINO_COUNTRY_CODE,
                default=defaults.get(
                    CONF_VIVINO_COUNTRY_CODE, DEFAULT_VIVINO_COUNTRY_CODE
                ),
            ): str,
            vol.Required(
                CONF_VIVINO_FALLBACK_TO_GEMINI,
                default=defaults.get(
                    CONF_VIVINO_FALLBACK_TO_GEMINI,
                    DEFAULT_VIVINO_FALLBACK_TO_GEMINI,
                ),
            ): bool,
            vol.Required(
                CONF_LOW_STOCK_THRESHOLD,
                default=defaults.get(
                    CONF_LOW_STOCK_THRESHOLD, DEFAULT_LOW_STOCK_THRESHOLD
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
            vol.Optional(
                CONF_TEMPERATURE_ENTITY,
                default=defaults.get(CONF_TEMPERATURE_ENTITY, ""),
            ): str,
            vol.Optional(
                CONF_HUMIDITY_ENTITY,
                default=defaults.get(CONF_HUMIDITY_ENTITY, ""),
            ): str,
        }
    )
    return vol.Schema(fields)


class WineInventoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a UI config flow for Wine Inventory."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step configured by the user in Settings > Integrations."""
        if user_input is not None:
            cellar_name = user_input.get(CONF_CELLAR_NAME, DEFAULT_CELLAR_NAME).strip()
            await self.async_set_unique_id(cellar_name.lower().replace(" ", "_"))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=cellar_name, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema({}, include_cellar_name=True),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return WineInventoryOptionsFlowHandler(config_entry)


class WineInventoryOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Wine Inventory options updates."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the Wine Inventory options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        merged = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(merged, include_cellar_name=False),
        )

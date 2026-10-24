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


def _get_coordinator_for_entry(hass: Any, entry_id: str) -> Any:
    """Get coordinator from hass.data."""
    if not hasattr(hass, "data"):
        return None
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry_id)
    if isinstance(entry_data, dict) and "coordinator" in entry_data:
        return entry_data["coordinator"]
    for val in domain_data.values():
        if isinstance(val, dict) and "coordinator" in val:
            return val["coordinator"]
    return None


class WineInventoryOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Wine Inventory options updates, backups, restores, and imports."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the Wine Inventory options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "backup", "restore", "import_wines"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage general cellar settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        merged = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="settings",
            data_schema=_build_schema(merged, include_cellar_name=False),
        )

    async def async_step_backup(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Create a full database, metadata, and images .zip backup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            coordinator = _get_coordinator_for_entry(self.hass, self._config_entry.entry_id)
            if coordinator:
                try:
                    res = await coordinator.async_create_backup()
                    _LOGGER.info("Created backup %s with %s wines", res.get("filename"), res.get("wines_count"))
                    return self.async_create_entry(title="", data=self._config_entry.options)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Backup failed: %s", err)
                    errors["base"] = "backup_failed"

        return self.async_show_form(
            step_id="backup",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_restore(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Restore database from an existing or custom .zip backup."""
        errors: dict[str, str] = {}
        coordinator = _get_coordinator_for_entry(self.hass, self._config_entry.entry_id)
        available_backups = await coordinator.async_list_backups() if coordinator else []
        backup_filenames = [b["filename"] for b in available_backups]

        if user_input is not None and coordinator:
            chosen = user_input.get("backup_file")
            custom_path = (user_input.get("custom_path") or "").strip()
            target_path = custom_path or chosen
            if target_path:
                try:
                    await coordinator.async_restore_backup(target_path)
                    return self.async_create_entry(title="", data=self._config_entry.options)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Restore failed: %s", err)
                    errors["base"] = "restore_failed"
            else:
                errors["base"] = "no_backup_selected"

        schema_fields: dict[Any, Any] = {}
        if backup_filenames:
            schema_fields[vol.Optional("backup_file", default=backup_filenames[0])] = vol.In(
                backup_filenames
            )
        schema_fields[vol.Optional("custom_path", default="")] = str

        return self.async_show_form(
            step_id="restore",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

    async def async_step_import_wines(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Import wines from file path or JSON text."""
        errors: dict[str, str] = {}
        coordinator = _get_coordinator_for_entry(self.hass, self._config_entry.entry_id)

        if user_input is not None and coordinator:
            source = (user_input.get("import_source") or "").strip()
            if source:
                try:
                    await coordinator.async_import_wines(source)
                    return self.async_create_entry(title="", data=self._config_entry.options)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Import failed: %s", err)
                    errors["base"] = "import_failed"
            else:
                errors["base"] = "no_import_source"

        return self.async_show_form(
            step_id="import_wines",
            data_schema=vol.Schema({vol.Required("import_source"): str}),
            errors=errors,
        )

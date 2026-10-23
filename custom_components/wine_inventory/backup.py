"""Home Assistant Core Backup integration for Wine Inventory SQLite database."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Flush SQLite WAL checkpoint before Home Assistant creates a backup archive."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if isinstance(entry_data, dict) and "coordinator" in entry_data:
            coordinator = entry_data["coordinator"]
            await coordinator.async_checkpoint_database()
    _LOGGER.debug("Completed SQLite WAL checkpoint for Wine Inventory pre-backup")


async def async_post_backup(hass: HomeAssistant) -> None:
    """Perform any post-backup actions after Home Assistant snapshot completes."""
    _LOGGER.debug("Completed Wine Inventory post-backup hook")

"""The Discord Webhook Notify integration.

Setup model: each config entry holds one Discord webhook. On entry setup we
load the legacy ``notify`` platform through discovery, which registers a
``notify.<name>`` service for that webhook. The legacy service style is kept
on purpose so automations can call ``notify.<name>`` directly, the same way
the classic ``notify: - platform: rest`` setup worked.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_AVATAR_URL,
    CONF_TTS,
    CONF_WEBHOOK_URL,
    DEFAULT_NAME,
    DEFAULT_TTS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the component (no YAML configuration is supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Discord webhook from a config entry."""
    # Options (edited via the GUI) take precedence over the original data.
    data = {**entry.data, **entry.options}
    name = data.get(CONF_NAME, DEFAULT_NAME)

    discovery_info = {
        "platform": DOMAIN,
        CONF_NAME: name,
        CONF_WEBHOOK_URL: data[CONF_WEBHOOK_URL],
        CONF_USERNAME: data.get(CONF_USERNAME),
        CONF_AVATAR_URL: data.get(CONF_AVATAR_URL),
        CONF_TTS: data.get(CONF_TTS, DEFAULT_TTS),
    }

    hass.async_create_task(
        discovery.async_load_platform(hass, Platform.NOTIFY, DOMAIN, discovery_info, {})
    )

    # Reload the entry when the user saves changes via the options flow.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _LOGGER.debug("Setting up Discord webhook notification: %s", name)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    The notify platform owns the service lifecycle; returning True allows the
    entry to be removed/reloaded. Restart Home Assistant after removing an
    entry to make sure its ``notify.<name>`` service is gone.
    """
    _LOGGER.debug("Unloading Discord webhook notification: %s", entry.title)
    return True

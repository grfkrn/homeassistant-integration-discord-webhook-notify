"""Tests for __init__.py — a config entry registers its notify service."""

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.discord_webhook_notify.const import (
    CONF_WEBHOOK_URL,
    DOMAIN,
)

WEBHOOK_ID = "123456789012345678"
WEBHOOK_URL = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/abcdef-ghijkl"


async def test_entry_registers_notify_service(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="discord_alerts",
        data={CONF_NAME: "discord_alerts", CONF_WEBHOOK_URL: WEBHOOK_URL},
        unique_id=WEBHOOK_ID,
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.services.has_service("notify", "discord_alerts")


async def test_unload_entry(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="discord_alerts",
        data={CONF_NAME: "discord_alerts", CONF_WEBHOOK_URL: WEBHOOK_URL},
        unique_id=WEBHOOK_ID,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)

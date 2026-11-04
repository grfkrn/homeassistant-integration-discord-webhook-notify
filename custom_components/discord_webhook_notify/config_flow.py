"""Config flow for Discord Webhook Notify.

Add flow:  form -> confirm menu (test / edit / save) -> entry created.
Options flow reuses the same fields and the same confirm menu, so an entry
can be re-tested before saving changes.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AVATAR_URL,
    CONF_TTS,
    CONF_WEBHOOK_URL,
    DEFAULT_NAME,
    DEFAULT_TTS,
    DOMAIN,
    webhook_id_from_url,
)

_LOGGER = logging.getLogger(__name__)

TEST_MESSAGE = (
    "🔔 Test message from the Discord Webhook Notify integration for Home Assistant."
)


async def async_test_webhook(hass, webhook_url: str) -> bool:
    """Post a test message to the webhook. True when Discord accepts it."""
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            webhook_url, json={"content": TEST_MESSAGE}
        ) as response:
            return response.status in (200, 201, 204)
    except aiohttp.ClientError as err:
        _LOGGER.debug("Test webhook request failed: %s", err)
        return False


def normalize_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw form input into config-entry data."""
    return {
        CONF_NAME: (user_input.get(CONF_NAME) or "").strip() or DEFAULT_NAME,
        CONF_WEBHOOK_URL: (user_input.get(CONF_WEBHOOK_URL) or "").strip(),
        CONF_USERNAME: (user_input.get(CONF_USERNAME) or "").strip() or None,
        CONF_AVATAR_URL: (user_input.get(CONF_AVATAR_URL) or "").strip() or None,
        CONF_TTS: bool(user_input.get(CONF_TTS, DEFAULT_TTS)),
    }


def form_schema(defaults: dict[str, Any], *, suggested: bool = False) -> vol.Schema:
    """Build the form schema.

    In the options flow, values are passed as ``suggested_value`` instead of
    ``default`` for the optional text fields, so the user can clear them.
    """

    def optional_text(key: str, config_key: str) -> Any:
        if suggested:
            return vol.Optional(
                key, description={"suggested_value": defaults.get(config_key) or ""}
            )
        return vol.Optional(key, default=defaults.get(config_key) or "")

    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(
                CONF_WEBHOOK_URL, default=defaults.get(CONF_WEBHOOK_URL, "")
            ): str,
            optional_text(CONF_USERNAME, CONF_USERNAME): str,
            optional_text(CONF_AVATAR_URL, CONF_AVATAR_URL): str,
            vol.Optional(CONF_TTS, default=defaults.get(CONF_TTS, DEFAULT_TTS)): bool,
        }
    )


class DiscordWebhookNotifyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Discord Webhook Notify."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._test_result = ""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DiscordWebhookNotifyOptionsFlow:
        return DiscordWebhookNotifyOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = normalize_input(user_input)
            webhook_id = webhook_id_from_url(data[CONF_WEBHOOK_URL])
            if webhook_id is None:
                errors[CONF_WEBHOOK_URL] = "invalid_webhook_url"
            if not errors:
                await self.async_set_unique_id(webhook_id)
                self._abort_if_unique_id_configured()
                self._data = data
                self._test_result = ""
                return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=form_schema(user_input or self._data),
            errors=errors,
            last_step=False,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="confirm",
            menu_options=["test_webhook", "edit_settings", "save"],
            description_placeholders={"test_result": self._test_result},
        )

    async def async_step_test_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        ok = await async_test_webhook(self.hass, self._data[CONF_WEBHOOK_URL])
        self._test_result = (
            "✅ Test message sent." if ok else "❌ Test failed. Check the webhook URL."
        )
        return await self.async_step_confirm()

    async def async_step_edit_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_user()

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._data.get(CONF_NAME) or DEFAULT_NAME, data=self._data
        )


class DiscordWebhookNotifyOptionsFlow(config_entries.OptionsFlow):
    """Edit an existing entry (options flow)."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._test_result = ""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            data = normalize_input(user_input)
            # Keep empty strings as "" (not None) so stale values in
            # entry.data do not survive the {**data, **options} merge.
            if data[CONF_USERNAME] is None:
                data[CONF_USERNAME] = ""
            if data[CONF_AVATAR_URL] is None:
                data[CONF_AVATAR_URL] = ""
            webhook_id = webhook_id_from_url(data[CONF_WEBHOOK_URL])
            if webhook_id is None:
                errors[CONF_WEBHOOK_URL] = "invalid_webhook_url"
            elif webhook_id != self.config_entry.unique_id:
                others = {
                    entry.unique_id
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                    if entry.entry_id != self.config_entry.entry_id
                }
                if webhook_id in others:
                    errors[CONF_WEBHOOK_URL] = "already_configured"
            if not errors:
                self._data = data
                self._test_result = ""
                return await self.async_step_confirm()

        defaults = user_input or self._data or current
        return self.async_show_form(
            step_id="init",
            data_schema=form_schema(defaults, suggested=True),
            errors=errors,
            last_step=False,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="confirm",
            menu_options=["test_webhook", "edit_settings", "save"],
            description_placeholders={"test_result": self._test_result},
        )

    async def async_step_test_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        ok = await async_test_webhook(self.hass, self._data[CONF_WEBHOOK_URL])
        self._test_result = (
            "✅ Test message sent." if ok else "❌ Test failed. Check the webhook URL."
        )
        return await self.async_step_confirm()

    async def async_step_edit_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init()

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        webhook_id = webhook_id_from_url(self._data[CONF_WEBHOOK_URL])
        updates: dict[str, Any] = {}
        if webhook_id != self.config_entry.unique_id:
            updates["unique_id"] = webhook_id
        new_title = self._data.get(CONF_NAME) or DEFAULT_NAME
        if new_title != self.config_entry.title:
            updates["title"] = new_title
        if updates:
            self.hass.config_entries.async_update_entry(self.config_entry, **updates)
        return self.async_create_entry(data=self._data)

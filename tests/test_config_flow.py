"""Tests for config_flow.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.discord_webhook_notify.config_flow import (
    normalize_input,
)
from custom_components.discord_webhook_notify.const import (
    CONF_AVATAR_URL,
    CONF_TTS,
    CONF_WEBHOOK_URL,
    DOMAIN,
    webhook_id_from_url,
)

WEBHOOK_ID = "123456789012345678"
WEBHOOK_URL = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/abcdef-ghijkl_mnopqr"
WEBHOOK_ID_2 = "987654321098765432"
WEBHOOK_URL_2 = f"https://discord.com/api/webhooks/{WEBHOOK_ID_2}/stuvwx-yzabcd_efghij"


def _mock_session_ok():
    mock_response = MagicMock()
    mock_response.status = 204
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_response
    mock_cm.__aexit__.return_value = False
    session = MagicMock()
    session.post = MagicMock(return_value=mock_cm)
    return session


async def _save_from_menu(hass: HomeAssistant, flow_id: str) -> dict:
    return await hass.config_entries.flow.async_configure(
        flow_id, user_input={"next_step_id": "save"}
    )


# ---------------------------------------------------------------------------
# URL validation (pure)
# ---------------------------------------------------------------------------


def test_webhook_id_from_url_accepts_discord_domains() -> None:
    assert webhook_id_from_url(WEBHOOK_URL) == WEBHOOK_ID
    assert (
        webhook_id_from_url(
            f"https://discordapp.com/api/webhooks/{WEBHOOK_ID}/token-abc"
        )
        == WEBHOOK_ID
    )
    assert (
        webhook_id_from_url(
            f"https://canary.discord.com/api/webhooks/{WEBHOOK_ID}/token-abc"
        )
        == WEBHOOK_ID
    )


def test_webhook_id_from_url_rejects_others() -> None:
    assert (
        webhook_id_from_url("https://example.com/api/webhooks/123456789012345678/x")
        is None
    )
    assert (
        webhook_id_from_url("http://discord.com/api/webhooks/123456789012345678/x")
        is None
    )
    assert webhook_id_from_url("https://discord.com/api/webhooks/123/short") is None
    assert webhook_id_from_url("not-a-url") is None
    assert webhook_id_from_url("") is None


def test_normalize_input_trims_and_defaults() -> None:
    data = normalize_input({CONF_NAME: "  ", CONF_WEBHOOK_URL: f" {WEBHOOK_URL} "})
    assert data[CONF_NAME] == "Discord"
    assert data[CONF_WEBHOOK_URL] == WEBHOOK_URL
    assert data[CONF_USERNAME] is None
    assert data[CONF_AVATAR_URL] is None
    assert data[CONF_TTS] is False


# ---------------------------------------------------------------------------
# Add flow
# ---------------------------------------------------------------------------


async def test_user_step_shows_form(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_step_rejects_non_discord_url(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_WEBHOOK_URL: "https://example.com/hook/abc"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_WEBHOOK_URL] == "invalid_webhook_url"


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_WEBHOOK_URL: WEBHOOK_URL, CONF_NAME: "discord_alerts"},
    )
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "confirm"
    result = await _save_from_menu(hass, result["flow_id"])
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "discord_alerts"
    assert result["data"][CONF_WEBHOOK_URL] == WEBHOOK_URL
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == WEBHOOK_ID


async def test_user_step_aborts_on_duplicate_webhook_id(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "discord_alerts", CONF_WEBHOOK_URL: WEBHOOK_URL},
        unique_id=WEBHOOK_ID,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_WEBHOOK_URL: f"https://discord.com/api/webhooks/{WEBHOOK_ID}/a-different-token",
            CONF_NAME: "other",
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_confirm_menu_test_webhook_success(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_WEBHOOK_URL: WEBHOOK_URL, CONF_NAME: "discord_alerts"},
    )
    with patch(
        "custom_components.discord_webhook_notify.config_flow.async_get_clientsession",
        return_value=_mock_session_ok(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"next_step_id": "test_webhook"}
        )
    assert result["type"] == FlowResultType.MENU
    assert "✅" in result["description_placeholders"]["test_result"]


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_flow_updates_username(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="discord_alerts",
        data={
            CONF_NAME: "discord_alerts",
            CONF_WEBHOOK_URL: WEBHOOK_URL,
            CONF_USERNAME: None,
            CONF_AVATAR_URL: None,
            CONF_TTS: False,
        },
        unique_id=WEBHOOK_ID,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "discord_alerts",
            CONF_WEBHOOK_URL: WEBHOOK_URL,
            CONF_USERNAME: "NewName",
            CONF_AVATAR_URL: "",
            CONF_TTS: False,
        },
    )
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "save"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_USERNAME] == "NewName"


async def test_options_flow_rejects_other_entry_url(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="discord_alerts",
        data={CONF_NAME: "discord_alerts", CONF_WEBHOOK_URL: WEBHOOK_URL},
        unique_id=WEBHOOK_ID,
    )
    entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        title="discord_general",
        data={CONF_NAME: "discord_general", CONF_WEBHOOK_URL: WEBHOOK_URL_2},
        unique_id=WEBHOOK_ID_2,
    )
    other.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "discord_alerts",
            CONF_WEBHOOK_URL: WEBHOOK_URL_2,
            CONF_USERNAME: "",
            CONF_AVATAR_URL: "",
            CONF_TTS: False,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_WEBHOOK_URL] == "already_configured"

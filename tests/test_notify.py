"""Tests for notify.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.components.notify import ATTR_DATA, ATTR_TITLE
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant

from custom_components.discord_webhook_notify.const import (
    ATTR_EMBEDS,
    ATTR_FILES,
    ATTR_IMAGES,
    CONF_AVATAR_URL,
    CONF_WEBHOOK_URL,
    DEFAULT_TTS,
)
from custom_components.discord_webhook_notify.notify import (
    DiscordWebhookNotificationService,
    build_payload,
    get_service,
)

WEBHOOK_URL = "https://discord.com/api/webhooks/123456789012345678/abcdef-ghijkl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    hass: HomeAssistant,
    *,
    username: str | None = None,
    avatar_url: str | None = None,
    tts: bool = DEFAULT_TTS,
) -> DiscordWebhookNotificationService:
    return DiscordWebhookNotificationService(
        hass=hass,
        name="Test",
        webhook_url=WEBHOOK_URL,
        username=username,
        avatar_url=avatar_url,
        tts=tts,
    )


def _response_cm(status: int, text: str = "", content: bytes = b""):
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.text = AsyncMock(return_value=text)
    mock_response.content = MagicMock()
    mock_response.content.read = AsyncMock(return_value=content)
    mock_response.content_type = "application/octet-stream"
    mock_response.headers = {}
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_response
    mock_cm.__aexit__.return_value = False
    return mock_cm


def _make_session(post_statuses=(204,), post_texts=None, get_content=b""):
    post_texts = post_texts or [""] * len(post_statuses)
    cms = [
        _response_cm(status, text) for status, text in zip(post_statuses, post_texts)
    ]
    session = MagicMock()
    if len(cms) == 1:
        session.post = MagicMock(return_value=cms[0])
    else:
        session.post = MagicMock(side_effect=cms)
    session.get = MagicMock(return_value=_response_cm(200, content=get_content))
    session.close = AsyncMock()
    return session


def _patch_session(session):
    return patch(
        "custom_components.discord_webhook_notify.notify.async_get_clientsession",
        return_value=session,
    )


def _sent_json(session) -> dict:
    return session.post.call_args.kwargs["json"]


def _form_fields(session) -> dict:
    """Extract {field_name: (filename, value)} from the last post's FormData."""
    form = session.post.call_args.kwargs["data"]
    fields = {}
    for disposition, _headers, value in form._fields:
        fields[disposition["name"]] = (disposition.get("filename"), value)
    return fields


# ---------------------------------------------------------------------------
# build_payload (pure)
# ---------------------------------------------------------------------------


def test_build_payload_basic() -> None:
    payload = build_payload(
        "Hello",
        None,
        {},
        default_username=None,
        default_avatar_url=None,
        default_tts=False,
    )
    assert payload == {"content": "Hello", "tts": False}


def test_build_payload_title_and_truncation() -> None:
    payload = build_payload(
        "x" * 3000,
        "Title",
        {},
        default_username=None,
        default_avatar_url=None,
        default_tts=False,
    )
    assert payload["content"].startswith("**Title**\n")
    assert len(payload["content"]) == 2000


def test_build_payload_per_message_username_override() -> None:
    payload = build_payload(
        "Hi",
        None,
        {CONF_USERNAME: "Override", CONF_AVATAR_URL: "https://e.com/a.png"},
        default_username="Default",
        default_avatar_url=None,
        default_tts=False,
    )
    assert payload["username"] == "Override"
    assert payload["avatar_url"] == "https://e.com/a.png"


def test_build_payload_embeds_and_images_capped_at_10_total() -> None:
    data = {
        ATTR_EMBEDS: [{"title": str(i)} for i in range(7)],
        ATTR_IMAGES: [f"https://example.com/{i}.jpg" for i in range(7)],
    }
    payload = build_payload(
        "Hi",
        None,
        data,
        default_username=None,
        default_avatar_url=None,
        default_tts=False,
    )
    assert len(payload["embeds"]) == 10
    assert payload["embeds"][7] == {"image": {"url": "https://example.com/0.jpg"}}


# ---------------------------------------------------------------------------
# get_service / basic sending
# ---------------------------------------------------------------------------


def test_get_service(hass: HomeAssistant) -> None:
    assert get_service(hass, {}, discovery_info=None) is None
    service = get_service(hass, {}, discovery_info={CONF_WEBHOOK_URL: WEBHOOK_URL})
    assert isinstance(service, DiscordWebhookNotificationService)


async def test_send_message_posts_json(hass: HomeAssistant) -> None:
    service = _make_service(hass)
    session = _make_session()
    with _patch_session(session):
        await service.async_send_message("Hello world", **{ATTR_TITLE: "Alert"})
    args, kwargs = session.post.call_args
    assert args[0] == WEBHOOK_URL
    assert kwargs["json"]["content"] == "**Alert**\nHello world"


async def test_send_message_client_error_reraised(hass: HomeAssistant) -> None:
    service = _make_service(hass)
    session = MagicMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = aiohttp.ClientError("boom")
    session.post = MagicMock(return_value=mock_cm)
    with _patch_session(session), pytest.raises(aiohttp.ClientError):
        await service.async_send_message("Hello")


async def test_429_is_retried_and_then_succeeds(hass: HomeAssistant) -> None:
    service = _make_service(hass)
    session = _make_session(
        post_statuses=(429, 204),
        post_texts=[json.dumps({"retry_after": 0.01}), ""],
    )
    with _patch_session(session):
        await service.async_send_message("Hello")
    assert session.post.call_count == 2


async def test_error_status_is_logged_not_raised(hass: HomeAssistant) -> None:
    service = _make_service(hass)
    session = _make_session(post_statuses=(404,), post_texts=["unknown webhook"])
    with _patch_session(session):
        await service.async_send_message("Hello")  # must not raise
    assert session.post.call_count == 1


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


async def test_local_image_file_is_attached_as_multipart(
    hass: HomeAssistant, tmp_path
) -> None:
    image = tmp_path / "snapshot.jpg"
    image.write_bytes(b"\xff\xd8\xff fake-jpeg")
    hass.config.allowlist_external_dirs.add(str(tmp_path))

    service = _make_service(hass)
    session = _make_session()
    with _patch_session(session):
        await service.async_send_message(
            "Motion detected",
            **{ATTR_DATA: {ATTR_FILES: [str(image)]}},
        )

    fields = _form_fields(session)
    assert "payload_json" in fields
    assert json.loads(fields["payload_json"][1])["content"] == "Motion detected"
    filename, content = fields["files[0]"]
    assert filename == "snapshot.jpg"
    assert content == b"\xff\xd8\xff fake-jpeg"


async def test_file_outside_allowlist_is_skipped(hass: HomeAssistant, tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    # note: tmp_path is NOT added to the allowlist here

    service = _make_service(hass)
    session = _make_session()
    with _patch_session(session):
        await service.async_send_message(
            "Hello", **{ATTR_DATA: {ATTR_FILES: [str(secret)]}}
        )

    # fell back to a plain JSON post without the file
    assert "json" in session.post.call_args.kwargs


async def test_url_file_is_downloaded_and_attached(hass: HomeAssistant) -> None:
    service = _make_service(hass)
    session = _make_session(get_content=b"PNGDATA")
    with _patch_session(session):
        await service.async_send_message(
            "See attached",
            **{ATTR_DATA: {ATTR_FILES: ["https://example.com/pic.png"]}},
        )

    fields = _form_fields(session)
    filename, content = fields["files[0]"]
    assert filename == "pic.png"
    assert content == b"PNGDATA"


async def test_missing_file_is_skipped(hass: HomeAssistant, tmp_path) -> None:
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    service = _make_service(hass)
    session = _make_session()
    with _patch_session(session):
        await service.async_send_message(
            "Hello",
            **{ATTR_DATA: {ATTR_FILES: [str(tmp_path / "missing.jpg")]}},
        )
    assert "json" in session.post.call_args.kwargs

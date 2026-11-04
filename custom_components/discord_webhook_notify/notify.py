"""Discord webhook notification service.

Message data (``data:`` in the notify service call) supports:

- ``embeds``: list of Discord embed dicts (passed through, max 10 in total)
- ``images``: list of image URLs. Each becomes an embed image; Discord's
  servers fetch the URL, so it must be reachable from the internet.
- ``files``: list of attachments. Each item is either a local file path
  (must be inside a Home Assistant allowed directory) or an http(s) URL
  that Home Assistant downloads first. Attached images and videos are
  rendered inline by Discord. Max 10 files, 25 MB each.
- ``username`` / ``avatar_url``: per-message overrides
- ``tts``: per-message text-to-speech override
- ``allowed_mentions``: passed through to Discord (e.g. ``{"parse": []}``
  to disable all pings)
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_TITLE,
    BaseNotificationService,
)
from homeassistant.const import CONF_NAME, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_ALLOWED_MENTIONS,
    ATTR_EMBEDS,
    ATTR_FILES,
    ATTR_IMAGES,
    CONF_AVATAR_URL,
    CONF_TTS,
    CONF_WEBHOOK_URL,
    DEFAULT_NAME,
    DEFAULT_TTS,
    MAX_CONTENT_LENGTH,
    MAX_EMBEDS,
    MAX_FILE_BYTES,
    MAX_FILES,
)

_LOGGER = logging.getLogger(__name__)

SUCCESS_STATUSES = (200, 201, 204)
MAX_RETRIES = 2


def build_payload(
    message: str,
    title: str | None,
    data: dict[str, Any],
    *,
    default_username: str | None,
    default_avatar_url: str | None,
    default_tts: bool,
) -> dict[str, Any]:
    """Build the Discord webhook JSON payload (pure function, testable)."""
    text = f"**{title}**\n{message}" if title else message
    payload: dict[str, Any] = {
        "content": text[:MAX_CONTENT_LENGTH],
        "tts": bool(data.get(CONF_TTS, default_tts)),
    }

    username = data.get(CONF_USERNAME, default_username)
    if username:
        payload["username"] = username
    avatar_url = data.get(CONF_AVATAR_URL, default_avatar_url)
    if avatar_url:
        payload["avatar_url"] = avatar_url

    embeds: list[Any] = []
    raw_embeds = data.get(ATTR_EMBEDS)
    if isinstance(raw_embeds, list):
        embeds.extend(raw_embeds)
    raw_images = data.get(ATTR_IMAGES)
    if isinstance(raw_images, list):
        for url in raw_images:
            if isinstance(url, str) and url:
                embeds.append({"image": {"url": url}})
    if embeds:
        # Cap the combined total (embeds + image embeds) at Discord's limit.
        payload["embeds"] = embeds[:MAX_EMBEDS]

    if ATTR_ALLOWED_MENTIONS in data:
        payload[ATTR_ALLOWED_MENTIONS] = data[ATTR_ALLOWED_MENTIONS]

    return payload


def _read_file_bytes(path: Path) -> bytes:
    """Read a file synchronously (called in the executor)."""
    return path.read_bytes()


class DiscordWebhookNotificationService(BaseNotificationService):
    """Notification service bound to one Discord webhook."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        webhook_url: str,
        username: str | None = None,
        avatar_url: str | None = None,
        tts: bool = DEFAULT_TTS,
    ) -> None:
        self._hass = hass
        self._name = name
        self._webhook_url = webhook_url
        self._username = username or None
        self._avatar_url = avatar_url or None
        self._tts = tts

    # -- attachment collection --------------------------------------------
    async def _collect_attachments(
        self, items: list[Any]
    ) -> list[tuple[str, bytes, str | None]]:
        """Resolve the ``files`` list into (filename, bytes, mime) tuples."""
        session = async_get_clientsession(self._hass)
        attachments: list[tuple[str, bytes, str | None]] = []
        for item in items[:MAX_FILES]:
            if not isinstance(item, str) or not item:
                continue
            if item.startswith(("http://", "https://")):
                resolved = await self._download(session, item)
            else:
                resolved = await self._read_local(item)
            if resolved is not None:
                attachments.append(resolved)
        return attachments

    async def _read_local(self, item: str) -> tuple[str, bytes, str | None] | None:
        path = Path(item).expanduser()
        if not self._hass.config.is_allowed_path(str(path)):
            _LOGGER.error(
                "%s: file is outside the allowed directories and was skipped: %s "
                "(add it to allowlist_external_dirs in configuration.yaml)",
                self._name,
                item,
            )
            return None
        if not await self._hass.async_add_executor_job(path.is_file):
            _LOGGER.error("%s: file not found, skipped: %s", self._name, item)
            return None
        size = (await self._hass.async_add_executor_job(path.stat)).st_size
        if size > MAX_FILE_BYTES:
            _LOGGER.error(
                "%s: file exceeds the 25 MB Discord limit and was skipped: %s",
                self._name,
                item,
            )
            return None
        content = await self._hass.async_add_executor_job(_read_file_bytes, path)
        mime, _ = mimetypes.guess_type(path.name)
        return path.name, content, mime

    async def _download(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[str, bytes, str | None] | None:
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "%s: could not download attachment (HTTP %s): %s",
                        self._name,
                        response.status,
                        url,
                    )
                    return None
                content = await response.content.read(MAX_FILE_BYTES + 1)
        except aiohttp.ClientError as err:
            _LOGGER.error("%s: download failed for %s: %s", self._name, url, err)
            return None
        if len(content) > MAX_FILE_BYTES:
            _LOGGER.error(
                "%s: downloaded file exceeds the 25 MB Discord limit, skipped: %s",
                self._name,
                url,
            )
            return None
        filename = Path(url.split("?", 1)[0]).name or "download"
        mime, _ = mimetypes.guess_type(filename)
        return filename, content, mime or response.content_type

    # -- sending ------------------------------------------------------------
    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        """Send a message (and any attachments) to the Discord webhook."""
        title = kwargs.get(ATTR_TITLE)
        data: dict[str, Any] = kwargs.get(ATTR_DATA) or {}

        payload = build_payload(
            message or "",
            title,
            data,
            default_username=self._username,
            default_avatar_url=self._avatar_url,
            default_tts=self._tts,
        )

        attachments: list[tuple[str, bytes, str | None]] = []
        raw_files = data.get(ATTR_FILES)
        if isinstance(raw_files, list) and raw_files:
            attachments = await self._collect_attachments(raw_files)

        session = async_get_clientsession(self._hass)
        await self._post(session, payload, attachments)

    async def _post(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
        attachments: list[tuple[str, bytes, str | None]],
    ) -> None:
        for attempt in range(MAX_RETRIES + 1):
            try:
                if attachments:
                    form = aiohttp.FormData()
                    form.add_field(
                        "payload_json",
                        json.dumps(payload),
                        content_type="application/json",
                    )
                    for index, (filename, content, mime) in enumerate(attachments):
                        form.add_field(
                            f"files[{index}]",
                            content,
                            filename=filename,
                            content_type=mime,
                        )
                    request = session.post(self._webhook_url, data=form)
                else:
                    request = session.post(self._webhook_url, json=payload)

                async with request as response:
                    if response.status in SUCCESS_STATUSES:
                        _LOGGER.debug("%s: message sent to Discord", self._name)
                        return
                    body = (await response.text())[:500]
                    if response.status == 429 and attempt < MAX_RETRIES:
                        wait = await self._retry_wait(response, body)
                        _LOGGER.warning(
                            "%s: rate limited by Discord, retrying in %.1fs",
                            self._name,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    _LOGGER.error(
                        "%s: Discord webhook returned HTTP %s: %s",
                        self._name,
                        response.status,
                        body,
                    )
                    return
            except aiohttp.ClientError as err:
                _LOGGER.error(
                    "%s: error communicating with Discord webhook: %s",
                    self._name,
                    err,
                )
                raise

    @staticmethod
    async def _retry_wait(response: aiohttp.ClientResponse, body: str) -> float:
        """Seconds to wait before retrying after a 429 (capped at 10s)."""
        try:
            parsed = json.loads(body)
            return min(max(float(parsed.get("retry_after", 1.0)), 0.1), 10.0)
        except (ValueError, TypeError):
            header = response.headers.get("Retry-After")
            try:
                return min(max(float(header or 1.0), 0.1), 10.0)
            except (ValueError, TypeError):
                return 1.0


def get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> DiscordWebhookNotificationService | None:
    """Return the notification service for a discovered config entry."""
    if discovery_info is None:
        _LOGGER.error("Discord Webhook Notify is only available via config entries")
        return None

    name = discovery_info.get(CONF_NAME, DEFAULT_NAME)
    webhook_url = discovery_info.get(CONF_WEBHOOK_URL)
    if not webhook_url:
        _LOGGER.error("%s: no webhook URL provided", name)
        return None

    return DiscordWebhookNotificationService(
        hass=hass,
        name=name,
        webhook_url=webhook_url,
        username=discovery_info.get(CONF_USERNAME),
        avatar_url=discovery_info.get(CONF_AVATAR_URL),
        tts=discovery_info.get(CONF_TTS, DEFAULT_TTS),
    )

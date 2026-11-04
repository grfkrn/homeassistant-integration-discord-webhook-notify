"""Constants for the Discord Webhook Notify integration."""

import re

DOMAIN = "discord_webhook_notify"

CONF_WEBHOOK_URL = "webhook_url"
CONF_AVATAR_URL = "avatar_url"
CONF_TTS = "tts"
# CONF_NAME / CONF_USERNAME come from homeassistant.const

ATTR_IMAGES = "images"
ATTR_FILES = "files"
ATTR_EMBEDS = "embeds"
ATTR_ALLOWED_MENTIONS = "allowed_mentions"

DEFAULT_NAME = "Discord"
DEFAULT_TTS = False

# Discord limits
MAX_CONTENT_LENGTH = 2000
MAX_EMBEDS = 10
MAX_FILES = 10
MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB per file (Discord default upload limit)

# A Discord webhook URL looks like:
#   https://discord.com/api/webhooks/<id>/<token>
# (canary./ptb. subdomains and the legacy discordapp.com domain also exist)
WEBHOOK_URL_RE = re.compile(
    r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/"
    r"(\d{15,25})/[\w.\-~]+/?(?:\?.*)?$"
)


def webhook_id_from_url(url: str) -> str | None:
    """Return the webhook ID if the URL is a valid Discord webhook URL."""
    match = WEBHOOK_URL_RE.match(url.strip())
    return match.group(1) if match else None

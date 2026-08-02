from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API_BASE = "https://api.telegram.org"
_SEND_TIMEOUT_SECONDS = 10.0
_MAX_CAPTION_LENGTH = 1024
_MAX_MESSAGE_LENGTH = 4096


class TelegramNotifier:
    """Sends a photo + caption to a single configured Telegram chat.

    A misconfigured or unreachable bot must never interrupt the semantic
    analysis pipeline: failures are logged and swallowed, never raised.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=_SEND_TIMEOUT_SECONDS)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def send_photo(self, jpeg: bytes, *, caption: str) -> bool:
        url = f"{_TELEGRAM_API_BASE}/bot{self._bot_token}/sendPhoto"
        try:
            response = self._client.post(
                url,
                data={"chat_id": self._chat_id, "caption": caption[:_MAX_CAPTION_LENGTH]},
                files={"photo": ("frame.jpg", jpeg, "image/jpeg")},
            )
            if response.status_code >= 400:
                logger.error(
                    "Telegram respondió HTTP %d al enviar la notificación.",
                    response.status_code,
                )
                return False
        except Exception:
            logger.exception("No se pudo enviar la notificación de Telegram.")
            return False
        return True

    def send_message(self, text: str) -> bool:
        """Send a text-only notification, used when no capture is available."""

        url = f"{_TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        try:
            response = self._client.post(
                url,
                data={"chat_id": self._chat_id, "text": text[:_MAX_MESSAGE_LENGTH]},
            )
            if response.status_code >= 400:
                logger.error(
                    "Telegram respondió HTTP %d al enviar el mensaje.",
                    response.status_code,
                )
                return False
        except Exception:
            logger.exception("No se pudo enviar el mensaje de Telegram.")
            return False
        return True

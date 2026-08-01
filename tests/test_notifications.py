from __future__ import annotations

from typing import Any

import httpx
import pytest

from iris.notifications import TelegramNotifier


class FakeHTTPClient:
    def __init__(self, outcome: httpx.Response | Exception) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def post(self, url: str, *, data: dict[str, Any], files: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "data": data, "files": files})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        self.closed = True


def test_send_photo_posts_chat_id_caption_and_jpeg_to_the_bot_endpoint() -> None:
    fake_http = FakeHTTPClient(httpx.Response(200, json={"ok": True}))
    notifier = TelegramNotifier("secret-token", "12345", client=fake_http)

    result = notifier.send_photo(b"\xff\xd8fake-jpeg\xff\xd9", caption="Cámara 1: riesgo alto")

    assert result is True
    assert len(fake_http.calls) == 1
    call = fake_http.calls[0]
    assert call["url"] == "https://api.telegram.org/botsecret-token/sendPhoto"
    assert call["data"] == {"chat_id": "12345", "caption": "Cámara 1: riesgo alto"}
    assert call["files"]["photo"][0] == "frame.jpg"
    assert call["files"]["photo"][1] == b"\xff\xd8fake-jpeg\xff\xd9"


def test_send_photo_truncates_captions_over_telegrams_limit() -> None:
    fake_http = FakeHTTPClient(httpx.Response(200, json={"ok": True}))
    notifier = TelegramNotifier("secret-token", "12345", client=fake_http)
    long_caption = "x" * 2000

    notifier.send_photo(b"jpeg", caption=long_caption)

    assert len(fake_http.calls[0]["data"]["caption"]) == 1024


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.Response(401, json={"ok": False, "description": "Unauthorized"}),
        httpx.ConnectError("network unreachable"),
    ],
)
def test_send_photo_swallows_failures_and_returns_false(
    outcome: httpx.Response | Exception,
) -> None:
    fake_http = FakeHTTPClient(outcome)
    notifier = TelegramNotifier("secret-token", "12345", client=fake_http)

    result = notifier.send_photo(b"jpeg", caption="algo")

    assert result is False


def test_close_closes_owned_client_but_not_an_injected_one() -> None:
    fake_http = FakeHTTPClient(httpx.Response(200, json={"ok": True}))
    notifier = TelegramNotifier("secret-token", "12345", client=fake_http)

    notifier.close()

    assert fake_http.closed is False

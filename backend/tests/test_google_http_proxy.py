from types import SimpleNamespace
from urllib.request import Request

from zhiju.services import google_http


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_google_transport_is_direct_without_proxy(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        google_http,
        "get_settings",
        lambda: SimpleNamespace(google_proxy_url=""),
    )
    monkeypatch.setattr(
        google_http,
        "urlopen",
        lambda request, timeout: calls.append((request.full_url, timeout)) or _Response(),
    )

    with google_http.open_google_url(
        Request("https://www.googleapis.com/youtube/v3/channels"), timeout=20
    ):
        pass

    assert calls == [("https://www.googleapis.com/youtube/v3/channels", 20)]


def test_google_transport_uses_configured_proxy(monkeypatch) -> None:
    captured = {}

    class _Opener:
        def open(self, request, timeout):
            captured["request"] = (request.full_url, timeout)
            return _Response()

    def fake_build_opener(handler):
        captured["proxies"] = handler.proxies
        return _Opener()

    monkeypatch.setattr(
        google_http,
        "get_settings",
        lambda: SimpleNamespace(google_proxy_url="http://127.0.0.1:17888"),
    )
    monkeypatch.setattr(google_http, "build_opener", fake_build_opener)

    with google_http.open_google_url(
        Request("https://oauth2.googleapis.com/token"), timeout=30
    ):
        pass

    assert captured == {
        "proxies": {
            "http": "http://127.0.0.1:17888",
            "https": "http://127.0.0.1:17888",
        },
        "request": ("https://oauth2.googleapis.com/token", 30),
    }

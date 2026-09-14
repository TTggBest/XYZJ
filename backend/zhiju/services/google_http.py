from urllib.request import ProxyHandler, Request, build_opener, urlopen

from zhiju.config import get_settings


def open_google_url(request: Request, *, timeout: float):
    """Open one Google-owned request through the optional dedicated proxy."""
    proxy_url = get_settings().google_proxy_url.strip()
    if not proxy_url:
        return urlopen(request, timeout=timeout)
    opener = build_opener(
        ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    return opener.open(request, timeout=timeout)

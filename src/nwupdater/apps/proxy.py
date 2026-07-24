"""Server-side download of catalogue apps (``.nwa``), SSRF-guarded.

The browser cannot fetch these itself (CORS), so the local server proxies them. Only ``https``
URLs that already appear in the app catalogue are allowed — the single guard below is shared by
both entry points:

  - :func:`fetch` buffers the whole payload in memory (for staging + icon preview);
  - :func:`open_stream` returns the live response so the caller can stream it and show a
    byte-accurate progress bar.
"""

from __future__ import annotations

from .store import AppStore

MAX_APP_BYTES = 9 * 1024 * 1024  # in-memory staging cap for a buffered download


def _require_allowed(store: AppStore, url: str) -> None:
    """Raise ValueError unless ``url`` is an https URL present in the app catalogue."""
    allowed = {e.url for e in store.entries if e.url}
    if url not in allowed or not url.startswith("https://"):
        raise ValueError("URL not allowed (not in catalog or not https)")


def fetch(store: AppStore, url: str, *, transport=None) -> dict:
    """Download a catalogue app's ``.nwa`` into memory. Reuses the catalogue transport (proper
    TLS via certifi, follows the GitHub→CDN redirect). Size-capped; nothing is written to disk."""
    import base64

    from ..catalog import auth as A
    from ..formats.appicon import decode_app_icon
    _require_allowed(store, url)
    tr = transport or A.UrllibTransport()
    try:
        resp = tr.open("GET", url, headers={"User-Agent": "nwupdater"},
                       allow_redirects=True, timeout=30)
    except A.TransportError as exc:
        raise ValueError(str(exc)) from exc
    if resp.status != 200:
        raise ValueError(f"HTTP {resp.status} for {url}")
    if len(resp.body) > MAX_APP_BYTES:
        raise ValueError("file too large")
    return {"ok": True, "size": len(resp.body), "icon": decode_app_icon(resp.body),
            "data_b64": base64.b64encode(resp.body).decode("ascii")}


def open_stream(store: AppStore, url: str):
    """Open a catalogue app's URL for streaming. Returns ``(content_length_or_None, response)`` —
    the caller streams and closes the response. Same allowlist/https guard as :func:`fetch`."""
    import urllib.request

    from ..catalog.auth import _ssl_context
    _require_allowed(store, url)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))
    req = urllib.request.Request(url, headers={"User-Agent": "nwupdater"})
    resp = opener.open(req, timeout=30)  # noqa: S310 - https + catalogue allowlist enforced above
    cl = resp.headers.get("Content-Length")
    return (int(cl) if cl and cl.isdigit() else None), resp

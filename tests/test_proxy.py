"""apps.proxy — server-side .nwa download behind the SSRF allowlist (offline, fake transport)."""

import pytest

from nwupdater.apps import proxy
from nwupdater.apps.store import AppStore
from nwupdater.formats.nwa import build_nwa


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self.body = body


class _Transport:
    def __init__(self, resp):
        self._resp = resp

    def open(self, method, url, *, headers=None, allow_redirects=False, timeout=30):
        return self._resp


def _store_and_url():
    store = AppStore.bundled()
    return store, next(e.url for e in store.entries if e.url)  # an allowlisted catalogue URL


def test_fetch_ok_with_fake_transport():
    store, url = _store_and_url()
    blob = build_nwa("Demo", api_level=0, code=b"\x00" * 128)
    out = proxy.fetch(store, url, transport=_Transport(_Resp(200, blob)))
    assert out["ok"] is True and out["size"] == len(blob) and out["data_b64"]


def test_fetch_rejects_non_200():
    store, url = _store_and_url()
    with pytest.raises(ValueError, match="HTTP 404"):
        proxy.fetch(store, url, transport=_Transport(_Resp(404, b"")))


def test_fetch_rejects_oversized():
    store, url = _store_and_url()
    big = _Transport(_Resp(200, b"x" * (proxy.MAX_APP_BYTES + 1)))
    with pytest.raises(ValueError, match="too large"):
        proxy.fetch(store, url, transport=big)


def test_fetch_rejects_url_not_in_catalog():
    store, _ = _store_and_url()
    with pytest.raises(ValueError, match="not allowed"):
        proxy.fetch(store, "https://evil.example/x.nwa", transport=_Transport(_Resp(200, b"")))

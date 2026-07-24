"""Headless-browser smoke test of the local web UI (Playwright).

Skipped unless Playwright and a Chromium/Chrome are available:
``pip install '.[dev,test-ui]'`` then ``playwright install chromium`` (CI does this in a
dedicated job). It proves the served page loads and runs without JS errors, and that the
browser's own same-origin fetches reach the CSRF-hardened API and render the identity — the
automated coverage the pure-Python suite can't give the JS/UI layer.
"""

import os
import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from nwupdater.server.httpd import make_server
from nwupdater.server.session import Session


def _launch(p):
    """Prefer Playwright's managed Chromium (CI); fall back to a system Chromium/Chrome so the
    test also runs on a dev machine that has a browser but not the Playwright download."""
    candidates: list[dict] = [{}]
    mac_chromium = "/Applications/Chromium.app/Contents/MacOS/Chromium"
    if os.path.exists(mac_chromium):
        candidates.append({"executable_path": mac_chromium})
    candidates += [{"channel": "chrome"}, {"channel": "msedge"}]
    for kw in candidates:
        try:
            return p.chromium.launch(headless=True, **kw)
        except Exception:
            continue
    return None


def test_ui_loads_and_renders_identity(tmp_path):
    session = Session(model_name="n0110", os_version="16.4.4", cache_dir=tmp_path / "cache")
    httpd = make_server(session, port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    errors: list[str] = []
    try:
        with sync_api.sync_playwright() as p:
            browser = _launch(p)
            if browser is None:
                pytest.skip("no Chromium/Chrome available for the headless UI smoke test")
            page = browser.new_page()
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="load")
            # The page fetches the identity on load (same-origin, sends Origin): rendering it proves
            # the CSRF-hardened API is reachable from a real browser and that app.js runs.
            page.wait_for_function("document.body.innerText.includes('16.4.4')", timeout=8000)
            body = page.inner_text("body")
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert "n0110" in body.lower()  # model rendered from /api/identity
    assert "16.4.4" in body  # installed OS version rendered
    assert not errors, f"UI console/page errors: {errors}"

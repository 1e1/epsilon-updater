"""Browser-real tests of the web UI's JS logic (Playwright) — a safety net for refactoring
``server/web/app.js``, which the pure-Python suite cannot reach.

Two angles, both against the real JS engine (no Node toolchain added to this Python project):
  * **pure logic** — call app.js's own functions with controlled inputs via ``page.evaluate``
    (the memory-write planner, the cache-entry resolver, the security-critical ``jsStr``);
  * **interaction** — drive the real workshop (stage an app → Write → the device list updates),
    exercising the stage/plan/commit reactivity path end to end.

Skipped unless Playwright and a Chromium/Chrome are available (CI ``test-ui`` job installs them).
"""

import contextlib
import os
import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from nwupdater.server.httpd import make_server
from nwupdater.server.session import Session


def _launch(p):
    """Playwright's managed Chromium (CI), else a system Chromium/Chrome (dev machine)."""
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


@contextlib.contextmanager
def _ui(tmp_path, model="n0110", os_version="16.4.4"):
    """Serve a connected demo device and yield ``(page, errors)`` with app.js loaded."""
    session = Session(model_name=model, os_version=os_version, cache_dir=tmp_path / "cache")
    httpd = make_server(session, port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            browser = _launch(p)
            if browser is None:
                pytest.skip("no Chromium/Chrome available for the UI logic tests")
            page = browser.new_page()
            errors: list[str] = []
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_function("typeof planFor === 'function'")  # app.js evaluated
            try:
                yield page, errors
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


# -- pure logic (option b) -----------------------------------------------------------------
def test_planfor_computes_frozen_prefix_and_sizes(tmp_path):
    with _ui(tmp_path) as (page, errors):
        r = page.evaluate(
            """() => {
                STATE.apps = { device: [{name:'A', size:1000}], capacity: 100000, avail: [], apiLevel: 0 };
                STATE.stage.apps = [
                  {name:'A', size:1000, onDevice:true, deleted:false},
                  {name:'B', size:2000, onDevice:false, deleted:false},
                ];
                const p = planFor('apps');
                return {un:p.un, rw:p.rw, nw:p.nw, usedB:p.usedB, freeB:p.freeB, dirty:p.dirty};
            }"""
        )
        assert r == {"un": 1, "rw": 0, "nw": 1, "usedB": 3000, "freeB": 97000, "dirty": True}
        assert not errors


def test_planfor_clean_plan_is_not_dirty(tmp_path):
    with _ui(tmp_path) as (page, errors):
        dirty = page.evaluate(
            """() => {
                STATE.apps = { device: [{name:'A', size:10}], capacity: 1000, avail: [], apiLevel: 0 };
                STATE.stage.apps = [{name:'A', size:10, onDevice:true, deleted:false}];
                return planFor('apps').dirty;
            }"""
        )
        assert dirty is False
        assert not errors


def test_cached_entry_for_device_matches_connected_model(tmp_path):
    with _ui(tmp_path) as (page, errors):
        r = page.evaluate(
            """() => {
                STATE.identity = { model:'n0120', connected:true, virtual:false };
                STATE.cache = { entries: [
                  {model:'n0110', version:'25.2.0'}, {model:'n0120', version:'25.2.0'}
                ]};
                const e = cachedEntryForDevice();
                const none = (() => { STATE.identity = {model:'n0200'}; return cachedEntryForDevice(); })();
                return { hit: e ? e.model + ':' + e.version : null, miss: none };
            }"""
        )
        assert r["hit"] == "n0120:25.2.0" and r["miss"] is None
        assert not errors


def test_jsstr_escaping_round_trips_and_is_injection_safe(tmp_path):
    with _ui(tmp_path) as (page, errors):
        r = page.evaluate(
            """() => {
                const raw = "O'Brien\\" ;alert(1)// <img>";
                const enc = jsStr(raw);
                const back = eval("'" + enc + "'");   // enc embedded in a single-quoted JS string
                return { ok: back === raw, enc };
            }"""
        )
        assert r["ok"] is True  # decodes back to the exact original
        assert "'" not in r["enc"] and '"' not in r["enc"] and "<" not in r["enc"]
        assert not errors


def test_fmtbytes_units(tmp_path):
    with _ui(tmp_path) as (page, errors):
        r = page.evaluate("() => [fmtBytes(512), fmtBytes(2048), fmtBytes(3*1024*1024)]")
        assert r == ["512 o", "2 Kio", "3 Mio"]
        assert not errors


# -- interaction (option a) ----------------------------------------------------------------
def test_stage_and_commit_app_reaches_the_device(tmp_path):
    with _ui(tmp_path) as (page, errors):
        # The workshop lives under the Apps tab now — reveal it first.
        page.click("#tab-apps")
        page.wait_for_selector("#pane-apps", state="visible")
        # Stage a bundled catalogue app via its "+" (aria-label = the app name).
        page.click("#pane-apps button.add[aria-label='Tetris']")
        page.wait_for_function("STATE.stage.apps.some(s => s.name === 'Tetris' && !s.onDevice)")
        # The "Write" button (the non-ghost .btn in the plan bar) is now enabled.
        commit = page.query_selector("#pane-apps .wplan button.btn.sm:not(.ghost)")
        assert commit is not None and commit.is_enabled()
        commit.click()
        # Commit installs to the (demo) device; after refresh the device list holds Tetris.
        page.wait_for_function("STATE.apps.device.some(a => a.name === 'Tetris')", timeout=8000)
        assert not errors


def test_serial_reveal_and_calc_name_are_wired(tmp_path):
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector("#serial-btn")
        # Serial is blurred by default; clicking the whole value reveals it, clicking again re-blurs.
        assert "blur" in (page.get_attribute("#serial-btn", "class") or "")
        page.click("#serial-btn")
        assert "blur" not in (page.get_attribute("#serial-btn", "class") or "")
        page.click("#serial-btn")
        assert "blur" in (page.get_attribute("#serial-btn", "class") or "")
        # Editable calculator name persists to the local store via POST /api/device/name.
        page.fill("#calc-name", "Lab bench")
        page.eval_on_selector("#calc-name", "el => el.blur()")
        page.wait_for_function("STATE.name && STATE.name.name === 'Lab bench'", timeout=8000)
        assert "Lab bench" in page.inner_text("#titlebar-text")
        assert not errors

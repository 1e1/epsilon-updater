"""Browser-real tests of ``server/web/calc.js`` — the SVG calculator renderer.

Isolated from the app: the file is a self-contained IIFE exposing a single global
``buildCalc``, so we load *only* ``calc.js`` into a blank page (no Session, no httpd, no
app.js) and inspect the SVG strings it returns. This guards the render contract the roster
UI depends on — notably ``buildCalc({variant, mode:"icon"})``, consumed by ``parcTypeCell``
in app.js — plus the string/object API and the textless-by-default screens.

Skipped unless Playwright and a Chromium/Chrome are available (same gate as the other UI tests).
"""

import contextlib
import os
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

CALC_JS = Path(__file__).resolve().parents[1] / "src/nwupdater/server/web/calc.js"


def _launch(p):
    """Playwright's managed Chromium (CI), else a system Chromium/Chrome (dev machine)."""
    candidates: list[dict] = [{}]
    mac_chromium = "/Applications/Chromium.app/Contents/MacOS/Chromium"
    if os.path.exists(mac_chromium):
        candidates.append({"executable_path": mac_chromium})
    candidates += [{"channel": "chrome"}, {"channel": "msedge"}]
    for kw in candidates:
        with contextlib.suppress(Exception):
            return p.chromium.launch(headless=True, **kw)
    return None


@contextlib.contextmanager
def _calc():
    """Yield a page with only calc.js loaded and ``buildCalc`` available."""
    with sync_api.sync_playwright() as p:
        browser = _launch(p)
        if browser is None:
            pytest.skip("no Chromium/Chrome available for the calc render tests")
        page = browser.new_page()
        page.set_content("<!doctype html><meta charset=utf-8><body>")
        page.add_script_tag(path=str(CALC_JS))
        page.wait_for_function("typeof buildCalc === 'function'")
        try:
            yield page
        finally:
            browser.close()


def test_string_api_stays_backwards_compatible():
    """``buildCalc("graphing"|"scientific")`` — app.js:189's call shape — returns the full device."""
    with _calc() as page:
        r = page.evaluate(
            """() => ({
                g: buildCalc('graphing'),
                s: buildCalc('scientific'),
                objEqStr: buildCalc({variant:'graphing'}) === buildCalc('graphing'),
            })"""
        )
        assert r["g"].startswith("<svg") and 'viewBox="0 0 232 466"' in r["g"]
        assert 'viewBox="0 0 232 372"' in r["s"]  # scientific body is shorter
        assert r["objEqStr"] is True  # object form with only variant == string form


def test_icon_mode_is_the_compact_family_glyph():
    """``mode:"icon"`` — the roster cell glyph (parcTypeCell) — is a 44×44 badge that reads the
    family by colour: light body for graphing, graphite for scientific, and the two differ."""
    with _calc() as page:
        r = page.evaluate(
            """() => ({
                g: buildCalc({variant:'graphing', mode:'icon'}),
                s: buildCalc({variant:'scientific', mode:'icon'}),
            })"""
        )
        assert 'viewBox="0 0 44 44"' in r["g"] and 'viewBox="0 0 44 44"' in r["s"]
        assert "#eceef1" in r["g"]  # light graphing body
        assert "#3b3e44" in r["s"]  # graphite scientific body
        assert r["g"] != r["s"]  # the glyph distinguishes the two families
        # No localized words baked into the glyph (it is pure silhouette).
        for word in ("APPLICATIONS", "Calculs", "Grapheur"):
            assert word not in r["g"] and word not in r["s"]


def test_thumb_mode_renders_the_screen_only():
    with _calc() as page:
        r = page.evaluate(
            """() => ({
                g: buildCalc({variant:'graphing', mode:'thumb', uid:'tg'}),
                s: buildCalc({variant:'scientific', mode:'thumb', uid:'ts'}),
            })"""
        )
        # A thumbnail is far shorter than the full device and labels itself as a screen.
        assert r["g"].startswith("<svg") and "écran" in r["g"]
        assert 'viewBox="0 0 232 466"' not in r["g"]  # not the whole device
        assert r["s"].startswith("<svg") and "écran" in r["s"]


def test_screens_are_textless_by_default_and_flag_restores_text():
    """Default screens carry no localized text (i18n); the hidden ``textless`` flag brings it back."""
    with _calc() as page:
        r = page.evaluate(
            """() => ({
                g:      buildCalc({variant:'graphing'}),
                s:      buildCalc({variant:'scientific'}),
                gText:  buildCalc({variant:'graphing',   textless:false}),
                sText:  buildCalc({variant:'scientific', textless:false, uid:'st'}),
            })"""
        )
        # default: no on-screen words
        assert "APPLICATIONS" not in r["g"] and ">Grapheur<" not in r["g"]
        assert ">Calculs<" not in r["s"] and ">deg<" not in r["s"]
        # hidden flag off: the localized screen chrome comes back
        assert "APPLICATIONS" in r["gText"] and ">Grapheur<" in r["gText"]
        assert ">Calculs<" in r["sText"] and ">deg<" in r["sText"]

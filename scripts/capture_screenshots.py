#!/usr/bin/env python3
"""Regenerate the marketing-site "Interface preview" screenshots from the live web UI.

This is a developer tool (it is NOT run in CI): it boots the local nwupdater web UI in-process,
drives it with headless Chromium via Playwright, and overwrites the two PNGs under
``docs/screenshots/`` that ``site/index.html`` shows:

* ``nwupdater-n0120-individual.png`` — Individual mode, an N0120 (Graphing) demo calculator, the
  **Apps** workshop tab (the calculator's contents next to the available items).
* ``nwupdater-n0200-classroom.png`` — Classroom mode, the local-fleet **Parc** tab, rendered from a
  seeded roster of N0200 (Scientific) + N0120 calculators grouped in classes. Shown WITHOUT a
  connected calculator, to make the point that the Parc is device-independent.

Each shot runs against a throwaway config directory (a fresh temp dir), so the capture never reads
or writes your real ``~/.config/nwupdater`` data; it is safe to re-run and it overwrites the PNGs
in place.

Prerequisites (already provided by the dev extras)::

    pip install '.[dev,test-ui]'
    playwright install chromium

Usage::

    python scripts/capture_screenshots.py

The window is captured at 2x device-scale for crisp output, in the light theme, with reduced
motion so nothing animates.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Browser, Playwright, ViewportSize, sync_playwright

from nwupdater.server.httpd import make_server
from nwupdater.server.session import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
VIEWPORT: ViewportSize = {"width": 1180, "height": 760}
DEVICE_SCALE = 2


def _launch(p: Playwright) -> Browser | None:
    """Prefer Playwright's managed Chromium; fall back to a system Chromium / Chrome / Edge so the
    tool also runs on a dev machine that has a browser but not the Playwright download (mirrors the
    fallback used by ``tests/test_ui_smoke.py``)."""
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


def _serve(session: Session) -> tuple[ThreadingHTTPServer, str]:
    """Start the local UI server on an OS-chosen port in a daemon thread; return it and its URL."""
    httpd = make_server(session, port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}"


def _isolate_config(tmp: Path) -> None:
    """Point every on-disk store (device names, classroom roster, user apps/scripts libraries) at a
    throwaway directory, so a capture never touches the developer's real config."""
    os.environ["NWUPDATER_CONFIG_DIR"] = str(tmp)
    os.environ["XDG_CONFIG_HOME"] = str(tmp)


def _seed_classroom_roster(tmp: Path) -> None:
    """Seed a believable classroom fleet (roster + names) so the Parc tab isn't empty.

    A mix of N0200 (Scientific) and one N0120 (Graphing) calculator, spread across two classes plus
    an unfiled bucket, with varied "known firmware" (some up to date, some behind, one unknown) and
    staggered last-scan times so the relative-time column reads naturally. Keys are the internal
    ``model:serial`` used everywhere in the roster; the serials never surface in the UI."""
    cfg = tmp / "nwupdater"
    cfg.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    def scanned(**delta: int) -> str:
        return (now - timedelta(**delta)).isoformat()

    # firmware baselines (bundled snapshots): Scientific latest 3.0.0, Graphing latest 25.2.0.
    # A compact fleet (two classes + an unfiled bucket) sized so every row fits the window without a
    # vertical scroll; up-to-date / behind / unknown firmware are all represented.
    roster = {
        "schema": 1,
        "classes": ["2nde 4", "3e B"],
        "calculators": {
            "n0200:Mk7Qa1uid": _rec("2nde 4", "3.0.0", "scientifique", "n0200", scanned(minutes=3)),
            "n0200:Bd2Rf9uid": _rec("2nde 4", "2.9.0", "scientifique", "n0200", scanned(hours=2)),
            "n0200:Qw4Ty7uid": _rec("3e B", "3.0.0", "scientifique", "n0200", scanned(days=1)),
            "n0200:Hn5Pk2uid": _rec("3e B", "2.9.0", "scientifique", "n0200", scanned(days=3)),
            "n0120:Gr3Ph8uid": _rec(None, "25.2.0", "graphique", "n0120", scanned(hours=5)),
            "n0200:Ss9Wq4uid": _rec(None, None, "scientifique", "n0200", scanned(days=7)),
        },
    }
    names = {
        "n0200:Mk7Qa1uid": "Poste 01",
        "n0200:Bd2Rf9uid": "Poste 02",
        "n0200:Qw4Ty7uid": "Poste 07",
        "n0200:Hn5Pk2uid": "Poste 08",
        "n0120:Gr3Ph8uid": "Demo prof",
        "n0200:Ss9Wq4uid": "Poste 12",
    }
    (cfg / "classroom-roster.json").write_text(json.dumps(roster, indent=2), encoding="utf-8")
    (cfg / "device-names.json").write_text(json.dumps(names, indent=2), encoding="utf-8")


def _rec(cls: str | None, firmware: str | None, family: str, model: str, last_scan: str) -> dict:
    """One roster record (as written by an on-scan enrolment)."""
    return {
        "class": cls,
        "known_firmware": firmware,
        "known_family": family,
        "known_model": model,
        "last_scan": last_scan,
    }


def _shot_individual(browser: Browser, tmp: Path, out: Path) -> None:
    """Individual mode · N0120 (Graphing) demo · the Apps workshop tab."""
    _isolate_config(tmp)
    session = Session(model_name="n0120", os_version="24.11.0", connect=True)
    httpd, base = _serve(session)
    try:
        ctx = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE,
            color_scheme="light",
            reduced_motion="reduce",
        )
        page = ctx.new_page()
        page.goto(f"{base}/?theme=light&lang=fr&mode=individual", wait_until="load")
        page.wait_for_selector('#window[data-conn="1"]', timeout=10000)
        page.click("#tab-apps")
        # The Apps workshop and at least one installed app row must be laid out before we shoot.
        page.wait_for_selector("#pane-apps.on .wk .cols2", timeout=10000)
        page.wait_for_selector("#pane-apps .item", timeout=10000)
        # let icons decode / layout settle (reduced motion means nothing animates)
        page.wait_for_timeout(500)
        page.locator("#window").screenshot(path=str(out))
        ctx.close()
        print(f"  wrote {out.relative_to(REPO_ROOT)}")
    finally:
        httpd.shutdown()
        httpd.server_close()


def _shot_classroom(browser: Browser, tmp: Path, out: Path) -> None:
    """Classroom mode · the local-fleet Parc tab · seeded roster · no connected calculator."""
    _isolate_config(tmp)
    _seed_classroom_roster(tmp)
    session = Session(connect=False)
    session.set_mode("classroom")  # server policy: lets /api/roster serve the seeded fleet
    httpd, base = _serve(session)
    try:
        ctx = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE,
            color_scheme="light",
            reduced_motion="reduce",
        )
        page = ctx.new_page()
        page.goto(f"{base}/?theme=light&lang=fr&mode=classroom", wait_until="load")
        page.wait_for_selector("#tab-parc", state="visible", timeout=10000)
        page.wait_for_selector("#pane-parc table.parc-tbl tbody tr", timeout=10000)
        # let the calculator glyphs / layout settle
        page.wait_for_timeout(500)
        page.locator("#window").screenshot(path=str(out))
        ctx.close()
        print(f"  wrote {out.relative_to(REPO_ROOT)}")
    finally:
        httpd.shutdown()
        httpd.server_close()


def main() -> int:
    import tempfile

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Capturing interface-preview screenshots (headless Chromium, light theme, 2x)...")
    with sync_playwright() as p:
        browser = _launch(p)
        if browser is None:
            print("No Chromium/Chrome available. Run: playwright install chromium")
            return 1
        try:
            with tempfile.TemporaryDirectory() as d1:
                _shot_individual(browser, Path(d1), OUT_DIR / "nwupdater-n0120-individual.png")
            with tempfile.TemporaryDirectory() as d2:
                _shot_classroom(browser, Path(d2), OUT_DIR / "nwupdater-n0200-classroom.png")
        finally:
            browser.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

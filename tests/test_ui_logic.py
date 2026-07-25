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
    from nwupdater.apps.store import AppEntry

    session = Session(model_name=model, os_version=os_version, cache_dir=tmp_path / "cache")
    # A placeholder catalogue entry so staging/committing an app stays offline (synth demo, no
    # network fetch); the shipped catalogue now holds only real, downloadable apps.
    session.store.entries.append(
        AppEntry(
            name="DemoApp",
            version="1.0",
            api_level=0,
            family="graphique",
            url="https://example.invalid/demoapp.nwa",
            size=65536,
        )
    )
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
        # Stage a catalogue app via its "+" (aria-label = the app name). DemoApp is an offline
        # placeholder injected by the fixture, so the commit synthesizes rather than downloads.
        page.click("#pane-apps button.add[aria-label='DemoApp']")
        page.wait_for_function("STATE.stage.apps.some(s => s.name === 'DemoApp' && !s.onDevice)")
        # The "Write" button (the non-ghost .btn in the plan bar) is now enabled.
        commit = page.query_selector("#pane-apps .wplan button.btn.sm:not(.ghost)")
        assert commit is not None and commit.is_enabled()
        commit.click()
        # Commit installs to the (demo) device; after refresh the device list holds DemoApp.
        page.wait_for_function("STATE.apps.device.some(a => a.name === 'DemoApp')", timeout=8000)
        assert not errors


def test_write_busy_highlights_only_rewritten_items(tmp_path):
    """A write must animate ONLY the slots actually being (re)written (rw/new); the frozen "un"
    prefix and every "Available" card stay still."""
    with _ui(tmp_path) as (page, errors):
        page.click("#tab-apps")
        page.wait_for_selector("#pane-apps", state="visible")
        r = page.evaluate(
            """() => {
                // Device order [A, B]; stage reorders to [A, C, B] so A stays frozen (un),
                // C is added (new) and B is pushed past the divergence (rw).
                STATE.apps.device = [{name:'A', size:100, api_level:0}, {name:'B', size:200, api_level:0}];
                STATE.apps.avail = [{name:'Z', api_level:0, url:'', source:'demo'}];
                STATE.stage.apps = [
                  {name:'A', size:100, api_level:0, onDevice:true, deleted:false},
                  {name:'C', size:150, api_level:0, onDevice:false, deleted:false},
                  {name:'B', size:200, api_level:0, onDevice:true, deleted:false},
                ];
                STATE.busy.apps = { op: 'write' };
                renderWorkbench();
                const pane = document.getElementById('pane-apps');
                const nm = e => e.querySelector('.nm').textContent.replace(/\\s+/g, ' ').trim();
                return {
                  oncalcBusy: [...pane.querySelectorAll('.item.oncalc.busy')].map(nm),
                  availBusy: pane.querySelectorAll('.wcol:nth-child(2) .item.busy').length,
                  totalBusy: pane.querySelectorAll('.item.busy').length,
                };
            }"""
        )
        assert r["totalBusy"] == 2  # exactly the two written slots, nothing else
        assert r["availBusy"] == 0  # no "Available" card animates during a write
        assert any(x.startswith("C") for x in r["oncalcBusy"])  # new item animates
        assert any(x.startswith("B") for x in r["oncalcBusy"])  # rewritten item animates
        assert not any(x.startswith("A") for x in r["oncalcBusy"])  # frozen (un) item does NOT
        assert not errors


def test_download_busy_highlights_only_the_target_available_item(tmp_path):
    """A remote download must animate ONLY the single Available item in flight — no on-calc card."""
    with _ui(tmp_path) as (page, errors):
        page.click("#tab-apps")
        page.wait_for_selector("#pane-apps", state="visible")
        r = page.evaluate(
            """() => {
                STATE.apps.device = [{name:'A', size:100, api_level:0}];
                STATE.apps.avail = [
                  {name:'Alpha', api_level:0, url:'https://ex/alpha.nwa', source:'demo'},
                  {name:'Beta', api_level:0, url:'https://ex/beta.nwa', source:'demo'},
                ];
                STATE.stage.apps = [{name:'A', size:100, api_level:0, onDevice:true, deleted:false}];
                STATE.busy.apps = { op: 'download', name: 'Beta' };
                renderWorkbench();
                const pane = document.getElementById('pane-apps');
                const nm = e => e.querySelector('.nm').textContent.replace(/\\s+/g, ' ').trim();
                return {
                  busyNames: [...pane.querySelectorAll('.item.busy')].map(nm),
                  oncalcBusy: pane.querySelectorAll('.item.oncalc.busy').length,
                };
            }"""
        )
        assert r["oncalcBusy"] == 0  # nothing on the calculator animates during a download
        assert len(r["busyNames"]) == 1 and r["busyNames"][0].startswith("Beta")
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
        assert page.input_value("#calc-name") == "Lab bench"
        assert not errors


def test_parc_tab_is_classroom_only_renders_roster_and_hides_serial(tmp_path, monkeypatch):
    """The "Parc" tab appears only in classroom mode, renders the classes rail + calculator table
    from the roster, filters by class (single-click, with the click/dblclick discrimination delay),
    and NEVER puts a serial in the DOM."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R
    from nwupdater import device_names as N

    # Seed a two-calculator fleet BEFORE the page loads: one named + filed, one unnamed + unfiled.
    R.upsert_on_scan("n0110", "SECRETAAA111", firmware="25.2.0", family="graphique")
    R.upsert_on_scan("n0120", "SECRETBBB222", firmware="19.0.0", family="graphique")
    N.set_name("n0110", "SECRETAAA111", "Poste 3")
    R.move(["n0110:SECRETAAA111"], "Seconde A")
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector(
            "#serial-btn"
        )  # the connected UI has fully loaded (no in-flight GETs)
        # Individual mode: the Parc tab is hidden.
        assert page.eval_on_selector("#tab-parc", "el => getComputedStyle(el).display") == "none"
        # Detach the fixture's demo device so switching to classroom enrols nothing extra; the Parc
        # then reflects exactly the seeded fleet.
        page.evaluate(
            "async () => { stopPoll(); await post('/api/device/detach');"
            " STATE.identity = { connected:false }; setMode('classroom'); }"
        )
        page.wait_for_selector("#pane-parc.on .parc-tbl")
        page.wait_for_function(
            "document.querySelectorAll('#pane-parc .parc-tbl tbody tr').length === 2"
        )
        r = page.evaluate(
            """() => {
                const pane = document.getElementById('pane-parc');
                return {
                  tabShown: getComputedStyle(document.getElementById('tab-parc')).display !== 'none',
                  selected: document.getElementById('tab-parc').getAttribute('aria-selected'),
                  names: [...pane.querySelectorAll('.pnm-txt')].map(e => e.textContent),
                  html: pane.innerHTML,
                };
            }"""
        )
        assert r["tabShown"] is True and r["selected"] == "true"
        # Names are display labels (double-click to edit); the unnamed calc shows its fallback.
        assert "Poste 3" in r["names"] and "calc N0120" in r["names"]
        # The serial (inside the internal key) is never rendered — not even in an attribute.
        assert "SECRETAAA111" not in r["html"] and "SECRETBBB222" not in r["html"]
        # Single-clicking the "Seconde A" class name filters to its calculator. The select is
        # delayed (click/dblclick discrimination) so wait for the filtered tbody.
        page.click("#rail .clsbtn:has-text('Seconde A') .nm")
        page.wait_for_function("document.querySelectorAll('.parc-tbl tbody tr').length === 1")
        # Back to individual mode: the Parc tab hides and falls back to System.
        page.click("#mode-individual")
        assert page.eval_on_selector("#tab-parc", "el => getComputedStyle(el).display") == "none"
        assert not errors


def test_parc_edit_ui_mutates_via_server(tmp_path, monkeypatch):
    """The Parc edit affordances (double-click rename, per-row move, create/delete class with the
    move/purge confirm, multi-select) drive the real roster endpoints; the serial never reaches the
    DOM (handlers key on the row index)."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R
    from nwupdater import device_names as N

    # Seed a fleet in the store the server reads (same config dir) BEFORE the page loads.
    R.upsert_on_scan("n0110", "SECRETUI01", firmware="16.4.4", family="graphique")
    R.upsert_on_scan("n0120", "SECRETUI02", firmware="16.4.4", family="graphique")
    N.set_name("n0110", "SECRETUI01", "Poste 1")
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector(
            "#serial-btn"
        )  # the connected UI has fully loaded (no in-flight GETs)
        # Detach the demo device so classroom mode enrols nothing extra, then switch mode.
        page.evaluate(
            "async () => { stopPoll(); await post('/api/device/detach');"
            " STATE.identity = { connected:false }; setMode('classroom'); }"
        )
        page.wait_for_selector("#pane-parc.on .parc-tbl")
        page.wait_for_function("document.querySelectorAll('#pane-parc tbody tr').length === 2")
        # Names are display labels (double-click to edit); the seeded name is joined from the store.
        assert page.eval_on_selector_all(
            "#pane-parc .pnm-txt", "els => els.some(e => e.textContent === 'Poste 1')"
        )
        # The serial is never rendered — not as text, not in an attribute (handlers use row indices).
        html = page.inner_html("#pane-parc")
        assert "SECRETUI01" not in html and "SECRETUI02" not in html
        # Every edit handler is wired.
        assert page.evaluate(
            "() => ['parcRename','parcNameEdit','parcRowMove','parcRowDelete','parcBulkMove',"
            "'parcBulkDelete','parcDeleteClass','parcAddClass','parcClassRename','parcFilter',"
            "'parcDragStart'].every(f => typeof window[f] === 'function')"
        )
        # Inline rename by double-clicking the name label → edit → the name store records it.
        page.dblclick("#pane-parc .pnm-txt:has-text('Poste 1')")
        page.fill("#parc-nameedit", "Poste 9")
        page.eval_on_selector("#parc-nameedit", "el => el.blur()")
        page.wait_for_function("STATE.roster.calculators.some(c => c.name === 'Poste 9')")
        # Create a class from the rail input → it appears as a bucket.
        page.fill("#parc-newclass", "Seconde A")
        page.click("#rail .cls-add .ib")
        page.wait_for_function(
            "[...document.querySelectorAll('#rail .clsbtn .nm')].some(e => e.textContent === 'Seconde A')"
        )
        # Move the first calculator into it via the row dropdown → the server count reflects it.
        page.select_option("#pane-parc tbody tr:first-child .pc-act .mv", "Seconde A")
        page.wait_for_function("STATE.roster.counts && STATE.roster.counts['Seconde A'] === 1")
        # Multi-select all → the bulk bar appears (Phase-3 selection is already wired).
        page.check("#pane-parc thead input[type=checkbox]")
        page.wait_for_selector("#pane-parc .parc-bulk")
        # Delete the (now non-empty) class → the 2-choice confirm → "move" re-files its member.
        page.evaluate("() => parcDeleteClass('Seconde A')")
        page.wait_for_selector("#pane-parc .cls-confirm")
        page.click("#pane-parc .cls-confirm .confirm-move")
        page.wait_for_function("!STATE.roster.classes.includes('Seconde A')")
        assert page.evaluate("() => STATE.roster.unfiled_count === 2")  # both back to unfiled
        assert not errors


def test_parc_name_filter_and_class_double_click_rename(tmp_path, monkeypatch):
    """The "Nom" header filter narrows only the tbody and keeps its own focus; double-clicking a
    class name enters inline rename (single-click still selects, via the discrimination delay)."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R
    from nwupdater import device_names as N

    R.upsert_on_scan("n0110", "SERALPHA", firmware="16.4.4", family="graphique")
    R.upsert_on_scan("n0120", "SERBRAVO", firmware="16.4.4", family="graphique")
    N.set_name("n0110", "SERALPHA", "Alpha")
    N.set_name("n0120", "SERBRAVO", "Bravo")
    R.create_class("Seconde A")
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector(
            "#serial-btn"
        )  # the connected UI has fully loaded (no in-flight GETs)
        page.evaluate(
            "async () => { stopPoll(); await post('/api/device/detach');"
            " STATE.identity = { connected:false }; setMode('classroom'); }"
        )
        page.wait_for_selector("#pane-parc.on .parc-tbl")
        page.wait_for_function("document.querySelectorAll('#pane-parc tbody tr').length === 2")
        # Type in the header filter → only the tbody narrows, and the input keeps focus.
        page.fill(".pc-filter-in", "brav")
        page.wait_for_function("document.querySelectorAll('#pane-parc tbody tr').length === 1")
        assert page.evaluate(
            "() => document.activeElement === document.querySelector('.pc-filter-in')"
        )
        assert page.eval_on_selector_all(
            "#pane-parc .pnm-txt", "els => els.map(e => e.textContent)"
        ) == ["Bravo"]
        # Clear the filter → both rows return.
        page.fill(".pc-filter-in", "")
        page.wait_for_function("document.querySelectorAll('#pane-parc tbody tr').length === 2")
        # Double-click the class name → inline rename input; committing renames it on the server.
        page.dblclick("#rail .clsbtn:has-text('Seconde A') .nm")
        page.wait_for_selector("#parc-clsedit")
        page.fill("#parc-clsedit", "Terminale S")
        page.eval_on_selector("#parc-clsedit", "el => el.blur()")
        page.wait_for_function("STATE.roster.classes.includes('Terminale S')")
        assert page.evaluate("() => !STATE.roster.classes.includes('Seconde A')")
        assert not errors


def test_parc_usable_without_a_device_in_classroom(tmp_path, monkeypatch):
    """Decouple (plan §1 + 'afficher au plus tôt'): the classroom console (Calculatrices +
    Distribution, incl. the firmware cache) is device-independent, so it shows and edits with NO
    calculator connected — the workspace is not hidden behind "plug one in"."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R

    R.upsert_on_scan("n0110", "SEROFFLINE1", firmware="16.4.4", family="graphique")
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector(
            "#serial-btn"
        )  # the connected UI has fully loaded (no in-flight GETs)
        page.evaluate(
            """async () => {
                stopPoll();  // pin the simulated disconnect
                await post('/api/device/detach');  // no connected device → nothing auto-enrols
                STATE.identity = { connected:false };  // the calculator is unplugged
                await setMode('classroom');
                [STATE.roster, STATE.cache] = await Promise.all([api('/api/roster'), api('/api/cache')]);
                renderAll();
            }"""
        )
        page.wait_for_selector("#pane-parc.on .parc-tbl")
        assert page.eval_on_selector("#window", "el => el.dataset.conn") == "0"
        assert page.eval_on_selector(".nodev-main", "el => getComputedStyle(el).display") == "none"
        # Classroom is a fleet console: Calculatrices + Distribution show; the per-device tabs
        # (System/Apps/Scripts) are hidden — the firmware cache moved into Distribution → Firmware.
        assert page.eval_on_selector("#tab-parc", "el => getComputedStyle(el).display") != "none"
        assert page.eval_on_selector("#tab-dist", "el => getComputedStyle(el).display") != "none"
        assert page.eval_on_selector("#tab-system", "el => getComputedStyle(el).display") == "none"
        assert page.eval_on_selector("#tab-apps", "el => getComputedStyle(el).display") == "none"
        # The LEFT rail is the classes list (device-independent): at least Toutes + Sans classe.
        assert page.eval_on_selector_all("#rail .clsbtn", "els => els.length") >= 2
        # The seeded calculator is listed and editable (disk-only, offline).
        assert page.eval_on_selector_all("#pane-parc .pnm-txt", "els => els.length") == 1
        assert page.evaluate("() => typeof parcNameEdit === 'function'")
        # Distribution is reachable; with no real class selected it prompts to pick one.
        page.click("#tab-dist")
        page.wait_for_selector("#pane-dist.on")
        assert not errors


def test_distribution_tab_gates_panels_and_persists(tmp_path, monkeypatch):
    """Distribution tab: picking a class shows Recensement + a 4-node action chain (firmware OFF by
    default → its panel hidden); toggling an action shows/hides its panel and persists to the server."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R

    R.create_class("Seconde A")
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector("#serial-btn")
        page.evaluate(
            "async () => { stopPoll(); await post('/api/device/detach');"
            " STATE.identity = { connected:false }; await setMode('classroom');"
            " STATE.roster = await api('/api/roster'); renderAll(); }"
        )
        page.click("#rail .clsbtn:has-text('Seconde A') .nm")
        page.click("#tab-dist")
        page.wait_for_selector("#pane-dist.on .dist")
        # 4-node chain; firmware OFF by default → no firmware panel, apps/scripts panels present.
        assert page.eval_on_selector_all("#pane-dist .node", "els => els.length") == 4
        assert page.evaluate(
            "() => STATE.roster.distributions['Seconde A'].actions.firmware === false"
        )
        assert page.evaluate("() => !!document.querySelector('#dist-add-app')")
        # Toggle firmware ON → the cache panel appears and the config persists to the server.
        page.evaluate("() => toggleDistAction('firmware')")
        page.wait_for_function("STATE.roster.distributions['Seconde A'].actions.firmware === true")
        page.wait_for_function(
            "[...document.querySelectorAll('#pane-dist .dist-card h4')].some(h => /caches firmware|firmware caches/i.test(h.textContent))"
        )
        # Toggle apps OFF → its set panel disappears and the change persists.
        page.evaluate("() => toggleDistAction('apps')")
        page.wait_for_function("STATE.roster.distributions['Seconde A'].actions.apps === false")
        page.wait_for_function("!document.querySelector('#dist-add-app')")
        # Onboarding rule persists.
        page.evaluate("() => setDistOnboarding('ignore')")
        page.wait_for_function("STATE.roster.distributions['Seconde A'].onboarding === 'ignore'")
        assert not errors


def test_batch_mode_runs_chain_and_journals(tmp_path, monkeypatch):
    """Mode batch: arming opens the overlay; 'Simuler' attaches a virtual calculator and runs the
    class chain for real, appending a journal row and filing the calc; re-simulating the same model
    greys the previous pass; the serial never reaches the journal DOM."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R

    R.create_class("Seconde A")
    with _ui(tmp_path) as (page, errors):
        page.wait_for_selector("#serial-btn")
        page.evaluate(
            "async () => { stopPoll(); await post('/api/device/detach');"
            " STATE.identity = { connected:false }; await setMode('classroom');"
            " STATE.roster = await api('/api/roster'); renderAll(); }"
        )
        page.click("#rail .clsbtn:has-text('Seconde A') .nm")
        page.click("#btn-batch")
        page.wait_for_selector("#batch-overlay:not([hidden]) .bjournal")
        # Simulate a first calculator → one journal row, and the calc is filed in the class.
        page.select_option("#batch-model", "n0110")
        page.click(".bsim .simbtn")
        page.wait_for_function(
            "document.querySelectorAll('#batch-jbody tr').length === 1 && !!(STATE.roster.counts||{})['Seconde A']"
        )
        assert page.eval_on_selector_all("#batch-jbody .pc-dist .dist-ic", "els => els.length") >= 1
        # The serial never reaches the journal DOM (rows render names/models only).
        serial = page.evaluate("() => STATE.identity && STATE.identity.serial_number")
        assert serial and serial not in page.inner_html("#batch-jbody")
        # Simulate the SAME model again → a second row; the older one is greyed (same identity).
        page.click(".bsim .simbtn")
        page.wait_for_function("document.querySelectorAll('#batch-jbody tr').length === 2")
        page.wait_for_function("document.querySelectorAll('#batch-jbody tr.jprev').length === 1")
        # Stop → the overlay hides and the classroom console returns.
        page.click(".arm .stop")
        page.wait_for_function("document.getElementById('batch-overlay').hidden === true")
        assert page.eval_on_selector("#tab-parc", "el => getComputedStyle(el).display") != "none"
        assert not errors


def test_account_reachable_without_a_device_in_individual(tmp_path, monkeypatch):
    """The account card (P2) is device-independent, so individual mode can sign in with no
    calculator; the firmware-flash card (device-dependent) is hidden until one is present."""
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    with _ui(tmp_path) as (page, errors):
        page.evaluate(
            """async () => {
                stopPoll();
                STATE.auth = await api('/api/auth');
                STATE.identity = { connected:false };
                setMode('individual');
                renderAll();
            }"""
        )
        page.wait_for_selector("#window[data-conn='0']")
        assert page.eval_on_selector("#tab-system", "el => getComputedStyle(el).display") != "none"
        page.click("#tab-system")
        assert (
            page.eval_on_selector("#account-card", "el => getComputedStyle(el).display") != "none"
        )
        assert page.eval_on_selector("#flash-card", "el => getComputedStyle(el).display") == "none"
        assert page.query_selector("#auth-email") is not None  # the login form is available offline
        assert not errors

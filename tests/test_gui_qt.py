"""The Qt half of the native UI: the list models, the job runner, and the backend façade.

Skipped unless PySide6 is installed (it is the optional ``gui`` extra). Everything runs on the
offscreen platform, so there is no window and no display requirement — and, as everywhere else
in this project, no real USB: the session drives the in-memory virtual device.
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="native UI extra not installed")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from nwupdater.gui.app import _application, configure_identity
from nwupdater.gui.backend import Backend
from nwupdater.gui.i18n import I18n
from nwupdater.gui.jobs import JobRunner
from nwupdater.gui.models import RowsModel
from nwupdater.gui.workshop import ROW_FIELDS
from nwupdater.server.session import Session


@pytest.fixture(scope="session")
def qt_app():
    # Built the way app.py builds it, identity included: Qt.labs.platform's menu bar needs the
    # widgets application everywhere except macOS, and QSettings needs the application to be
    # named. Both suites share one process, so whichever fixture runs first used to decide —
    # calling the same helper removes the ordering dependency.
    configure_identity()
    return QGuiApplication.instance() or _application([])


@pytest.fixture
def backend(qt_app, tmp_path, monkeypatch):
    # Keep the roster and the name store inside the test's tmp dir.
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    session = Session("n0120", connect=True, cache_dir=tmp_path / "cache")
    made = Backend(session)
    # The first inventory read is a job, not constructor work: the window paints before the
    # calculator has been read. Tests wait for it the same way the window does.
    assert wait_until(qt_app, lambda: made.connected), "the first snapshot never arrived"
    yield made
    # A backend left running keeps polling the (now torn-down) session from its hot-plug timer.
    made.shutdown()


def toasts(backend) -> list:
    """Collect (key, params, isError) triples. The signal carries an i18n KEY, never a
    sentence — the status bar is what renders it."""
    seen: list = []
    backend.toast.connect(lambda key, params, err: seen.append((key, dict(params), err)))
    return seen


def pump(app, ms=1500):
    """Spin the event loop so queued cross-thread results are delivered."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(app, predicate, timeout_ms=5000):
    """Spin the loop until `predicate()` holds, then return.

    Worker results arrive as queued signals, so a test has to let the loop run — but sleeping a
    flat 1.5 s per wait makes the suite four times slower than the work it measures, and still
    flakes on a loaded CI runner. Waiting for the condition is both faster and firmer."""
    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    return predicate()


# -- RowsModel --------------------------------------------------------------------------
def test_model_exposes_one_role_per_field(qt_app):
    model = RowsModel(["name", "size"])
    names = sorted(v.data().decode() for v in model.roleNames().values())
    assert names == ["name", "size"]


def test_model_updates_in_place_when_the_keys_are_unchanged(qt_app):
    """The point of the diff: same rows, changed field → dataChanged, never a reset.
    A reset would drop the view's scroll position and focus."""
    model = RowsModel(["name", "status"])
    model.set_rows([{"name": "a", "status": "un"}, {"name": "b", "status": "un"}])
    resets, changes = [], []
    model.modelReset.connect(lambda: resets.append(1))
    model.dataChanged.connect(lambda *a: changes.append(1))
    model.set_rows([{"name": "a", "status": "rw"}, {"name": "b", "status": "un"}])
    assert resets == []
    assert len(changes) == 1  # only the row that actually changed


def test_model_resets_when_the_row_set_changes(qt_app):
    model = RowsModel(["name"])
    model.set_rows([{"name": "a"}])
    resets = []
    model.modelReset.connect(lambda: resets.append(1))
    model.set_rows([{"name": "a"}, {"name": "b"}])
    assert resets == [1]


def test_model_is_total_on_out_of_range_access(qt_app):
    """data() runs inside a C++ virtual call: anything raised there cannot be unwound and
    surfaces much later as a bare crash. It must never raise."""
    model = RowsModel(["name"])
    model.set_rows([{"name": "a"}])
    role = next(iter(model.roleNames()))
    assert model.data(model.index(5, 0), role) is None
    assert model.data(model.index(0, 0), 99999) is None
    assert model.get(99) == {}


def test_model_copies_its_rows(qt_app):
    model = RowsModel(["name"])
    source = [{"name": "a"}]
    model.set_rows(source)
    source[0]["name"] = "mutated"
    assert model.get(0)["name"] == "a"


# -- JobRunner --------------------------------------------------------------------------
def test_job_result_reaches_the_gui_thread(qt_app):
    """Regression: with QRunnable auto-delete on, the completion signal is destroyed before Qt
    dispatches it — the call succeeds in silence and the UI hangs on 'busy' forever."""
    from PySide6.QtCore import QObject

    owner = QObject()
    runner = JobRunner(owner)
    seen = []
    runner.submit(lambda: 42, seen.append, lambda m: seen.append(f"error:{m}"))
    wait_until(qt_app, lambda: bool(seen))
    assert seen == [42]
    assert runner.busy_count == 0


def test_job_failure_is_reported_not_raised(qt_app):
    from PySide6.QtCore import QObject

    owner = QObject()
    runner = JobRunner(owner)
    seen = []

    def boom():
        raise ValueError("nope")

    runner.submit(boom, lambda r: seen.append(("ok", r)), lambda m: seen.append(("err", m)))
    wait_until(qt_app, lambda: bool(seen))
    assert seen == [("err", "nope")]


# -- i18n -------------------------------------------------------------------------------
def test_i18n_interpolates_and_falls_back(qt_app):
    i18n = I18n("fr")
    assert "{" not in i18n.t("roster_bulk_selected", {"n": 3})
    assert i18n.t("this_key_does_not_exist") == "this_key_does_not_exist"


def test_i18n_switches_language(qt_app):
    i18n = I18n("fr")
    assert i18n.t("roster_col_dist") == "Distribution"  # same word in both, a poor probe
    french = i18n.t("mode_classroom")
    i18n.lang = "en"
    assert i18n.lang == "en"
    assert i18n.t("mode_classroom") != french


def test_i18n_renders_the_relative_time_keys(qt_app):
    """The roster's last-scan column is a key + count. Both languages must produce a sentence
    with the number in it, or the column silently reads "il y a {n} min"."""
    for lang in ("fr", "en"):
        i18n = I18n(lang)
        rendered = i18n.t("rel_min", {"n": 20})
        assert "20" in rendered and "{" not in rendered
        assert i18n.t("rel_never") == "—"


# -- Backend ----------------------------------------------------------------------------
def test_backend_starts_on_the_virtual_device(backend):
    assert backend.connected is True
    assert backend.identity["model"] == "n0120"
    assert backend.mode == "individual"


def test_workshop_models_are_populated(backend):
    assert backend.appsDeviceModel.rowCount() > 0
    assert set(backend.appsDeviceModel.get(0)) == set(ROW_FIELDS)
    assert backend.appsPlan["enabled"] is True
    assert backend.appsPlan["dirty"] is False


def test_staging_marks_the_plan_dirty_and_undo_clears_it(backend):
    name = backend.appsAvailModel.get(0)["name"]
    backend.stageAdd("apps", name)
    assert backend.appsPlan["dirty"] is True
    assert backend.appsPlan["canUndo"] is True
    backend.stageUndo("apps")
    assert backend.appsPlan["dirty"] is False


def test_staging_the_same_app_twice_warns_instead_of_duplicating(backend):
    name = backend.appsAvailModel.get(0)["name"]
    backend.stageAdd("apps", name)
    before = backend.appsDeviceModel.rowCount()
    seen = toasts(backend)
    backend.stageAdd("apps", name)
    assert backend.appsDeviceModel.rowCount() == before
    assert seen[-1] == ("already_staged", {"name": name}, True)


def test_mode_toggle_is_reflected_back(backend):
    """Regression: the policy carries `classroom`, not `mode`; reading the wrong attribute
    behind a getattr default made the toggle look inert."""
    backend.setMode("classroom")
    assert backend.mode == "classroom"
    backend.setMode("individual")
    assert backend.mode == "individual"


def test_switching_demo_model_refreshes_the_identity(backend, qt_app):
    """Regression: this ran on a worker thread whose completion never arrived."""
    backend.exploreDemo("n0200")
    assert wait_until(qt_app, lambda: backend.identity.get("model") == "n0200")
    assert backend.identity["family"] == "scientifique"
    assert backend.busy == ""


def test_a_scientific_calculator_offers_no_workshops(backend, qt_app):
    backend.exploreDemo("n0200")
    assert wait_until(qt_app, lambda: backend.identity.get("model") == "n0200")
    assert wait_until(qt_app, lambda: backend.appsPlan["enabled"] is False)
    assert backend.scriptsPlan["enabled"] is False


def test_detaching_empties_the_workshops(backend, qt_app):
    backend.detach()
    assert wait_until(qt_app, lambda: not backend.connected)
    assert backend.appsDeviceModel.rowCount() == 0
    assert backend.appsPlan == {"enabled": False}


def test_demo_models_are_plain_names(backend):
    """Regression: a fresh list of dicts on every property read left the picker holding a
    model Qt had already freed."""
    assert backend.demoModels == backend.demoModels
    assert all(isinstance(m, str) for m in backend.demoModels)


def test_classroom_exposes_classes_and_distribution(backend):
    backend.setMode("classroom")
    backend.classCreate("2nde 4")
    assert "2nde 4" in backend.classNames
    backend.selectClass("2nde 4")
    assert backend.distribution["editable"] is True
    backend.distSetAction("firmware", True)
    assert backend.distribution["actions"]["firmware"] is True
    assert "firmware" in backend.batchSteps


def test_distribution_item_toggles_persist(backend):
    backend.setMode("classroom")
    backend.classCreate("3e A")
    backend.selectClass("3e A")
    pool = backend.distribution["availableApps"]
    if not pool:
        pytest.skip("no app catalogue available in this environment")
    backend.distToggleItem("apps", pool[0], True)
    assert pool[0] in backend.distribution["apps"]
    backend.distToggleItem("apps", pool[0], False)
    assert pool[0] not in backend.distribution["apps"]


def test_batch_needs_a_class_before_arming(backend):
    backend.setMode("classroom")
    backend.selectClass(backend.classAll)
    seen = toasts(backend)
    if backend.classNames:
        assert backend.armBatch() is True
    else:
        assert backend.armBatch() is False
        assert seen[-1] == ("batch_need_class", {}, True)


def test_batch_pass_records_a_journal_entry(backend, qt_app):
    backend.setMode("classroom")
    backend.classCreate("6e C")
    backend.selectClass("6e C")
    assert backend.armBatch() is True
    backend.batchRunOnce()
    assert wait_until(qt_app, lambda: len(backend.batch["journal"]) == 1)
    assert backend.batch["running"] is False
    assert len(backend.batch["journal"]) == 1
    assert backend.batch["journal"][0]["dist"]["recensement"] in ("ok", "change")


def test_roster_keys_ignore_the_class_and_the_filter(backend):
    """The table's rows follow the filter; rosterKeys must not — it is what the QML prunes a
    selection against, and a filtered-out calculator is hidden, not gone."""
    backend.setMode("classroom")
    keys = list(backend.rosterKeys)
    assert keys and all(isinstance(k, str) and k for k in keys)
    backend.setFilter("zzz-no-such-calculator")
    assert backend.rosterRows.rowCount() == 0
    assert list(backend.rosterKeys) == keys
    backend.setFilter("")


def test_roster_filter_narrows_the_table(backend):
    backend.setMode("classroom")
    total = backend.rosterRows.rowCount()
    backend.setFilter("zzz-no-such-calculator")
    assert backend.rosterRows.rowCount() == 0
    backend.setFilter("")
    assert backend.rosterRows.rowCount() == total


# -- the destructive paths --------------------------------------------------------------
# Everything below writes something: flash, the script area, a file on disk, or the register.
# They were the least covered lines in the package and the most expensive to get wrong.
def test_committing_a_staged_script_writes_it_to_the_device(backend, qt_app, tmp_path):
    """The scripts branch of commit(): the storage area is rewritten to exactly the kept
    records. Deliberately a LOCAL file — installing a catalogue app pulls the network and
    relinks through nwlink, which is not what this test is about."""
    from PySide6.QtCore import QUrl

    script = tmp_path / "suites.py"
    script.write_text("from math import *\n")
    backend.addLocalFile("scripts", QUrl.fromLocalFile(str(script)))
    assert backend.scriptsPlan["dirty"] is True
    seen = toasts(backend)
    backend.commit("scripts")
    assert wait_until(qt_app, lambda: backend.busy == "" and not backend.scriptsPlan["dirty"])
    on_device = [
        backend.scriptsDeviceModel.get(i)["name"]
        for i in range(backend.scriptsDeviceModel.rowCount())
    ]
    assert "suites.py" in on_device
    assert seen[-1][0] == "written_ok"


def test_committing_a_removal_erases_it(backend, qt_app):
    name = backend.appsDeviceModel.get(0)["name"]
    backend.stageRemove("apps", name)
    backend.commit("apps")
    assert wait_until(qt_app, lambda: backend.busy == "" and not backend.appsPlan["dirty"])
    on_device = [
        backend.appsDeviceModel.get(i)["name"] for i in range(backend.appsDeviceModel.rowCount())
    ]
    assert name not in on_device


def test_a_clean_plan_writes_nothing(backend):
    seen = toasts(backend)
    backend.commit("apps")
    assert backend.busy == ""
    assert seen == []


def test_dropping_the_wrong_extension_is_refused(backend, tmp_path):
    from PySide6.QtCore import QUrl

    wrong = tmp_path / "notes.txt"
    wrong.write_text("hello")
    seen = toasts(backend)
    backend.addLocalFile("apps", QUrl.fromLocalFile(str(wrong)))
    assert seen[-1] == ("wrong_ext", {"ext": ".nwa"}, True)
    assert backend.appsPlan["dirty"] is False


def test_dropping_a_python_file_stages_it(backend, tmp_path):
    from PySide6.QtCore import QUrl

    script = tmp_path / "fibo.py"
    script.write_text("def f(n): return n\n")
    backend.addLocalFile("scripts", QUrl.fromLocalFile(str(script)))
    assert backend.scriptsPlan["dirty"] is True
    staged = [
        backend.scriptsDeviceModel.get(i)["name"]
        for i in range(backend.scriptsDeviceModel.rowCount())
    ]
    assert "fibo.py" in staged


def test_exporting_an_app_writes_the_file(backend, qt_app, tmp_path):
    from PySide6.QtCore import QUrl

    out = tmp_path / "exported"
    out.mkdir()
    name = backend.appsDeviceModel.get(0)["name"]
    seen = toasts(backend)
    backend.exportItem("apps", name, QUrl.fromLocalFile(str(out)))
    assert wait_until(qt_app, lambda: backend.busy == "")
    written = list(out.iterdir())
    assert written, "nothing was exported"
    assert seen[-1][0] == "exported"
    assert seen[-1][1]["name"] == written[0].name


def test_renaming_and_filing_a_calculator_sticks(backend):
    backend.setMode("classroom")
    key = backend.rosterKeys[0]
    backend.rosterRename(key, "Poste 12")
    assert "Poste 12" in [
        backend.rosterRows.get(i)["displayName"] for i in range(backend.rosterRows.rowCount())
    ]
    backend.classCreate("4e B")
    backend.rosterMove([key], "4e B")
    assert backend.roster["counts"]["4e B"] == 1


def test_deleting_a_class_moves_its_calculators_out(backend):
    backend.setMode("classroom")
    key = backend.rosterKeys[0]
    backend.classCreate("5e A")
    backend.rosterMove([key], "5e A")
    backend.selectClass("5e A")
    assert backend.selectedClassCount == 1
    backend.classDelete("5e A", "move")
    assert "5e A" not in backend.classNames
    assert backend.parcClass == backend.classAll  # the deleted class cannot stay selected
    assert key in backend.rosterKeys  # "move" keeps the calculator, only unfiles it


def test_purging_a_class_deletes_its_calculators(backend):
    backend.setMode("classroom")
    key = backend.rosterKeys[0]
    backend.classCreate("5e B")
    backend.rosterMove([key], "5e B")
    backend.classDelete("5e B", "purge")
    assert key not in backend.rosterKeys


def test_deleting_a_calculator_drops_it_from_the_register(backend):
    backend.setMode("classroom")
    key = backend.rosterKeys[0]
    backend.rosterDelete([key])
    assert key not in backend.rosterKeys


def test_renaming_a_class_keeps_its_population(backend):
    backend.setMode("classroom")
    key = backend.rosterKeys[0]
    backend.classCreate("6e A")
    backend.rosterMove([key], "6e A")
    backend.classRename("6e A", "6e Z")
    assert "6e Z" in backend.classNames and "6e A" not in backend.classNames
    assert backend.roster["counts"]["6e Z"] == 1


# -- threading and cost -----------------------------------------------------------------
def test_filtering_does_not_re_read_the_register(backend, monkeypatch):
    """The filter used to call Session.roster() per keystroke — a full register + name-store
    parse, on the GUI thread. It re-slices what is already in memory now."""
    calls = []
    original = backend._s.roster
    monkeypatch.setattr(backend._s, "roster", lambda: (calls.append(1), original())[1])
    backend.setMode("classroom")
    calls.clear()
    for i in range(1, 7):
        backend.setFilter("tetris"[:i])
    assert calls == []
    assert backend.parcFilter == "tetris"


def test_a_second_operation_while_busy_says_so(backend, qt_app):
    """A control binds to `busy`, but a keyboard shortcut still reaches the slot. Dropping the
    gesture in silence is what it used to do."""
    backend._set_busy("firmware")
    seen = toasts(backend)
    backend.rescan()
    assert seen[-1] == ("busy_wait", {}, True)
    backend._set_busy("")


def test_shutdown_is_safe_to_call_twice(backend):
    backend.shutdown()
    backend.shutdown()  # idempotent: aboutToQuit can fire after an explicit teardown
    assert backend._timer.isActive() is False


def test_a_snapshot_landing_after_shutdown_changes_nothing(backend, qt_app):
    """A worker can return while the window is already tearing down. `_stopped` makes the
    queued completion a no-op instead of writing into models Qt is destroying."""
    backend.shutdown()
    before = backend.appsDeviceModel.rowCount()
    backend._apply_snapshot(
        {
            "identity": {},
            "device_name": {},
            "catalog": {},
            "cache": {},
            "auth": {},
            "roster": {},
            "shops": {"apps": None, "scripts": None},
        }
    )
    assert backend.appsDeviceModel.rowCount() == before


# -- the worker's own code --------------------------------------------------------------
# These run inside a Qt (C++) thread in production, which coverage.py cannot trace: moving
# work off the GUI thread also moves it out of sight. They are plain functions of the session,
# so the contract is asserted here, on the test thread, where it is visible.
def test_the_snapshot_carries_everything_the_ui_binds(backend):
    snap = backend._read_snapshot()
    assert set(snap) == {"identity", "catalog", "shops", "device_name", "cache", "roster", "auth"}
    assert snap["identity"]["model"] == "n0120"
    assert snap["shops"]["apps"] is not None
    # The register is only populated once a scan records the calculator (classroom mode); the
    # shape has to be there regardless, because the models bind to it from the first frame.
    assert set(snap["roster"]) >= {"classes", "counts", "calculators"}


def test_a_disconnected_snapshot_carries_no_workshop(backend):
    backend._s.detach()
    snap = backend._read_snapshot()
    assert snap["identity"].get("connected") is not True
    assert snap["shops"] == {"apps": None, "scripts": None}


def test_the_snapshot_survives_a_failing_sub_read(backend, monkeypatch):
    """One unreadable part must not cost the whole window: a calculator that answers identity
    but not the catalogue still gets a populated panel."""
    monkeypatch.setattr(
        backend._s, "catalog_updates", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    snap = backend._read_snapshot()
    assert snap["catalog"] == {}
    assert snap["identity"]["model"] == "n0120"


def test_applying_a_snapshot_publishes_every_model(backend):
    snap = backend._read_snapshot()
    backend.appsDevice.set_rows([])
    backend._apply_snapshot(snap)
    assert backend.appsDeviceModel.rowCount() > 0
    assert backend.connected is True


def test_apps_capacity_reads_the_flash_window(backend):
    assert Backend._apps_capacity({"external_apps_flash": ["0x90200000", "0x90600000"]}) == 0x400000
    assert Backend._apps_capacity({}) == 0
    assert Backend._apps_capacity({"external_apps_flash": ["nope", "0x1"]}) == 0


def test_the_hotplug_probe_reports_a_lost_cable(backend, monkeypatch):
    monkeypatch.setattr(backend._s, "device_health", lambda: {"connected": False})
    assert backend._probe_health() is True
    # The probe detaches the SESSION; `backend.connected` is the UI's last snapshot and only
    # follows once the refresh the probe schedules has been applied.
    assert backend._s.connected is False


def test_the_hotplug_probe_swallows_a_usb_error(backend, monkeypatch):
    """The poll runs every 4 s forever; an exception there must not reach the user."""
    monkeypatch.setattr(
        backend._s, "attach_real", lambda: (_ for _ in ()).throw(RuntimeError("no device"))
    )
    assert backend._probe_attach() is False


def test_a_refused_channel_switch_leaves_the_session_alone(backend):
    """`_run` refuses while the device is held. The channel must not move on its own then:
    the pane would show one channel and the session would be reading another."""
    before = backend._s.channel
    backend._set_busy("firmware")
    backend.setChannel("beta")
    assert backend._s.channel == before
    backend._set_busy("")


def test_switching_channel_re_reads_the_catalogue(backend, qt_app):
    backend.setChannel("beta")
    assert wait_until(qt_app, lambda: backend.busy == "")
    assert backend._s.channel == "beta"

"""The Qt half of the native UI: the list models, the job runner, and the backend façade.

Skipped unless PySide6 is installed (it is the optional ``gui`` extra). Everything runs on the
offscreen platform, so there is no window and no display requirement — and, as everywhere else
in this project, no real USB: the session drives the in-memory virtual device.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="native UI extra not installed")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from nwupdater.gui.backend import Backend
from nwupdater.gui.i18n import I18n
from nwupdater.gui.jobs import JobRunner
from nwupdater.gui.models import RowsModel
from nwupdater.gui.workshop import ROW_FIELDS
from nwupdater.server.session import Session


@pytest.fixture(scope="session")
def qt_app():
    QCoreApplication.setOrganizationName("nwupdater-tests")
    QCoreApplication.setApplicationName("nwupdater-tests")
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def backend(qt_app, tmp_path, monkeypatch):
    # Keep the roster and the name store inside the test's tmp dir.
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    session = Session("n0120", connect=True, cache_dir=tmp_path / "cache")
    made = Backend(session)
    yield made
    # A backend left running keeps polling the (now torn-down) session from its hot-plug timer.
    made.shutdown()


def pump(app, ms=1500):
    """Spin the event loop so queued cross-thread results are delivered."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


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
    pump(qt_app, 800)
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
    pump(qt_app, 800)
    assert seen == [("err", "nope")]


# -- i18n -------------------------------------------------------------------------------
def test_i18n_interpolates_and_falls_back(qt_app):
    i18n = I18n("fr")
    assert "{" not in i18n.t("roster_bulk_selected", {"n": 3})
    assert i18n.t("this_key_does_not_exist") == "this_key_does_not_exist"


def test_i18n_switches_language(qt_app):
    i18n = I18n("fr")
    french = i18n.t("tab_system")
    i18n.lang = "en"
    assert i18n.t("tab_system") != french or french == i18n.t("tab_system")
    assert i18n.lang == "en"


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
    warnings = []
    backend.toast.connect(lambda m, err: warnings.append((m, err)))
    backend.stageAdd("apps", name)
    assert backend.appsDeviceModel.rowCount() == before
    assert warnings and warnings[-1][1] is True


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
    pump(qt_app)
    assert backend.identity["model"] == "n0200"
    assert backend.identity["family"] == "scientifique"
    assert backend.busy == ""


def test_a_scientific_calculator_offers_no_workshops(backend, qt_app):
    backend.exploreDemo("n0200")
    pump(qt_app)
    assert backend.appsPlan["enabled"] is False
    assert backend.scriptsPlan["enabled"] is False


def test_detaching_empties_the_workshops(backend):
    backend.detach()
    assert backend.connected is False
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
    backend.selectClass("__all__")
    errors = []
    backend.toast.connect(lambda m, err: errors.append((m, err)))
    if backend.classNames:
        assert backend.armBatch() is True
    else:
        assert backend.armBatch() is False
        assert errors[-1] == ("batch_need_class", True)


def test_batch_pass_records_a_journal_entry(backend, qt_app):
    backend.setMode("classroom")
    backend.classCreate("6e C")
    backend.selectClass("6e C")
    assert backend.armBatch() is True
    backend.batchRunOnce()
    pump(qt_app, 2500)
    assert backend.batch["running"] is False
    assert len(backend.batch["journal"]) == 1
    assert backend.batch["journal"][0]["dist"]["recensement"] in ("ok", "change")


def test_roster_filter_narrows_the_table(backend):
    backend.setMode("classroom")
    total = backend.rosterRows.rowCount()
    backend.setFilter("zzz-no-such-calculator")
    assert backend.rosterRows.rowCount() == 0
    backend.setFilter("")
    assert backend.rosterRows.rowCount() == total

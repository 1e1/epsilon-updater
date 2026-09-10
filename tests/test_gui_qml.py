"""The QML scene itself: does it load, and does it load without complaining?

Nothing used to exercise these 3 000 lines. A typo in a binding, a role a delegate stopped
declaring, a `textRole` on a model that has none — all of it surfaced only when a user opened
the window, because ``QQmlApplicationEngine`` reports such things as *warnings* and carries on
with an empty control. The demo-model picker on the "no calculator" screen shipped broken for
exactly that reason: it rendered blank entries and passed ``undefined`` to the backend.

Runs on the offscreen platform, against the in-memory virtual device, like the rest of the
Qt suite.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="native UI extra not installed")

from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from nwupdater.gui.app import _application, install_context
from nwupdater.gui.backend import Backend
from nwupdater.gui.i18n import I18n
from nwupdater.server.session import Session

QML = Path(__file__).resolve().parents[1] / "src" / "nwupdater" / "gui" / "qml"


@pytest.fixture(scope="session")
def qt_app():
    return QGuiApplication.instance() or _application([])


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Scene:
    """A loaded window plus every warning Qt raised while it lived."""

    def __init__(self, session):
        self.warnings: list[str] = []
        self.backend = Backend(session)
        self.i18n = I18n("fr")
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(str(QML))
        self.engine.warnings.connect(lambda ws: self.warnings.extend(w.toString() for w in ws))
        install_context(self.engine, self.backend, self.i18n)
        self.engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))

    def close(self) -> None:
        self.backend.shutdown()
        del self.engine


@pytest.fixture
def scene(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    session = Session("n0120", connect=True, cache_dir=tmp_path / "cache")
    made = Scene(session)
    spin(400)
    yield made
    made.close()


def test_the_window_loads(scene):
    assert scene.engine.rootObjects(), "Main.qml produced no root object"


def test_loading_raises_no_qml_warning(scene):
    """A QML warning is not cosmetic: an unresolved binding leaves a control blank or inert
    while the window looks fine."""
    assert scene.warnings == []


def test_every_pane_and_both_modes_load_clean(scene, qt_app):
    """Walk the app the way a user does. Panes are built lazily, so a fault in one of them is
    invisible until its tab is opened — which is why this switches modes and visits each."""
    win = scene.engine.rootObjects()[0]
    for tab in win.property("tabOrder").toVariant():
        win.setProperty("currentTab", tab)
        spin(120)
    scene.backend.setMode("classroom")
    spin(200)
    for tab in win.property("tabOrder").toVariant():
        win.setProperty("currentTab", tab)
        spin(120)
    scene.backend.setMode("individual")
    spin(200)
    assert scene.warnings == []


def test_the_disconnected_screen_loads_clean(scene, qt_app):
    """The no-calculator rail is the first thing a user without a cable sees, and the one
    place nothing was ever instantiated in a test."""
    scene.backend.detach()
    spin(400)
    assert scene.engine.rootObjects()[0].property("visible") is True
    assert scene.warnings == []


def test_the_batch_window_loads_clean(scene, qt_app):
    scene.backend.setMode("classroom")
    scene.backend.classCreate("3e A")
    scene.backend.selectClass("3e A")
    spin(150)
    win = scene.engine.rootObjects()[0]
    win.openBatch()
    spin(300)
    assert scene.backend.batch["armed"] is True
    assert scene.warnings == []


def pickers(root):
    """Every visible ComboBox in the loaded scene, as (name, count, currentText) snapshots.

    Found by metatype name — the QML type is not importable from Python — and read
    defensively: `findChildren` also returns delegates and popup internals that Qt may have
    recycled between the scan and the read, which raises from shiboken rather than returning
    null.
    """
    from PySide6.QtCore import QObject

    found = []
    for child in root.findChildren(QObject):
        try:
            if "ComboBox" not in child.metaObject().className():
                continue
            if child.property("visible") is not True:
                continue
            found.append(
                (
                    child.metaObject().className(),
                    int(child.property("count") or 0),
                    str(child.property("currentText") or ""),
                )
            )
        except RuntimeError:  # recycled while we were looking at it
            continue
    return found


def test_no_picker_renders_blank_entries(scene, qt_app):
    """A picker whose model has entries must display one.

    This is the shape of the bug that shipped: `textRole: "name"` on a model of plain strings
    makes every entry render empty and `model[currentIndex].name` return undefined. Qt logs
    NOTHING for it — no warning, no error — so loading the scene cleanly is not enough; the
    invariant has to be asserted. The disconnected rail is where it hid, so detach first.
    """
    scene.backend.detach()
    spin(400)
    populated = [p for p in pickers(scene.engine.rootObjects()[0]) if p[1]]
    assert populated, "no populated picker was found — the scan is broken, not the UI"
    for name, count, current in populated:
        assert current, f"{name} has {count} entries but displays nothing"


def test_the_demo_picker_offers_the_backend_models(scene, qt_app):
    scene.backend.detach()
    spin(400)
    populated = [p for p in pickers(scene.engine.rootObjects()[0]) if p[1]]
    assert populated, "the disconnected rail should offer the demo models"
    assert populated[0][2] in list(scene.backend.demoModels)


def test_run_boots_the_whole_app(qt_app, tmp_path, monkeypatch):
    """`nwupdater gui` end to end: build the application, wire the context properties, load the
    scene, run the loop, tear down. Nothing covered this, so a renamed context property or a
    bad QML path would only have failed on a user's machine."""
    import nwupdater.gui.app as gui_app

    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    seen = {}
    original = gui_app._application

    def spy(argv):
        app = original(argv)
        seen["app"] = app
        QTimer.singleShot(600, app.quit)
        return app

    monkeypatch.setattr(gui_app, "_application", spy)
    assert gui_app.run(model="n0120", demo=True, lang="fr", argv=["nwupdater"]) == 0
    # Qt.labs.platform's menu bar needs the widgets application off macOS; a plain
    # QGuiApplication ships a window with no menu bar at all there.
    assert "QApplication" in type(seen["app"]).__name__


def test_run_reports_a_scene_that_will_not_load(qt_app, tmp_path, monkeypatch):
    import nwupdater.gui.app as gui_app

    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(gui_app, "_QML", tmp_path / "no-such-qml")
    assert gui_app.run(model="n0120", demo=True, argv=["nwupdater"]) == 1


def status_line(root):
    """The StatusBar's rendered message, found by its QML type name."""
    from PySide6.QtCore import QObject

    for child in root.findChildren(QObject):
        try:
            if child.metaObject().className().startswith("StatusBar"):
                return str(child.property("message") or "")
        except RuntimeError:
            continue
    return None


def test_the_status_bar_renders_the_message_not_the_key(scene, qt_app):
    """The regression, end to end: a teacher used to read `install_ok::20.4.0` on screen.
    The backend emits a key and its values; the bar is what turns them into a sentence."""
    scene.backend.toast.emit("fw_done", {"v": "20.4.0", "slot": "", "cache": ""}, False)
    spin(120)
    rendered = status_line(scene.engine.rootObjects()[0])
    assert rendered is not None, "no StatusBar in the scene"
    assert "20.4.0" in rendered
    assert "fw_done" not in rendered and "{" not in rendered


def test_the_status_bar_follows_a_language_switch(scene, qt_app):
    """It holds the key, not the sentence, so a message already on screen re-renders."""
    scene.backend.toast.emit("device_lost", {}, True)
    spin(120)
    root = scene.engine.rootObjects()[0]
    french = status_line(root)
    scene.i18n.lang = "en"
    spin(120)
    assert status_line(root) != french
    assert "device_lost" not in status_line(root)


def visible_texts(root):
    from PySide6.QtCore import QObject

    out = []
    for child in root.findChildren(QObject):
        try:
            if child.metaObject().className().startswith("QQuickText") and child.property("text"):
                out.append(str(child.property("text")))
        except RuntimeError:
            continue
    return out


def test_switching_language_redraws_the_window(scene, qt_app):
    """Not just the status line: every label.

    `i18n.t()` is a slot call, so it creates no binding dependency — switching language used to
    change nothing at all on screen (0 of 22 labels), and only took effect on the next launch.
    """
    root = scene.engine.rootObjects()[0]
    french = visible_texts(root)
    scene.i18n.lang = "en"
    spin(200)
    english = visible_texts(root)
    changed = sum(1 for a, b in zip(french, english) if a != b)
    assert changed > 5, f"only {changed} of {len(french)} labels followed the language switch"

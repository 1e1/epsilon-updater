"""Entry point for the native UI: ``nwupdater gui``.

No local HTTP server, no browser — the QML front-end talks to :class:`Session` in-process.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..server.session import Session

_QML = Path(__file__).with_name("qml")


def _application(argv: list[str]):
    """The application object, preferring the widgets one.

    ``Qt.labs.platform``'s MenuBar is native on macOS only. Everywhere else Qt falls back to a
    widget-based menu bar, and that fallback needs a ``QApplication`` — with a plain
    ``QGuiApplication`` it prints "Qt Labs Platform requires Qt Widgets" and the window ships
    with **no menu bar at all** on Windows and on Linux desktops without a global menu. QtWidgets
    is already inside the bundle (see ``packaging/nwupdater-gui.spec``), so this costs nothing we
    were not paying. A stripped build without it still runs: it degrades to QGuiApplication, and
    every menu action is duplicated on screen anyway — the rule this UI holds itself to.
    """
    from PySide6.QtCore import QCoreApplication

    existing = QCoreApplication.instance()
    if existing is not None:  # one per process; a test harness may already have built it
        return existing
    try:
        from PySide6.QtWidgets import QApplication

        return QApplication(argv)
    except ImportError:  # pragma: no cover - only a build that excluded QtWidgets gets here
        from PySide6.QtGui import QGuiApplication

        return QGuiApplication(argv)


def configure_identity() -> None:
    """Name the application to Qt, before anything reads a setting.

    ``QSettings`` — and therefore the QML ``Settings`` element that persists the window geometry,
    the language and the theme — refuses to initialise without an organisation and application
    name. Unset, Qt warns twice and the whole preference block silently does nothing. Called by
    :func:`run` and by the tests, so both exercise the same setup rather than only the shipped
    path being correct.
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QGuiApplication

    QCoreApplication.setOrganizationName("nwupdater")
    QCoreApplication.setOrganizationDomain("nwupdater.local")
    QCoreApplication.setApplicationName("nwupdater")
    QGuiApplication.setApplicationDisplayName("nwupdater")


def install_context(engine, backend, i18n) -> None:
    """Expose the two objects to QML, and make a language switch actually redraw.

    A QML binding re-evaluates when a *property* it read changes. ``i18n.t("key")`` is a slot
    call: it creates no dependency, so switching language left every label on screen in the old
    one — the menu only decided what the NEXT launch would look like. Re-setting the context
    property is the documented way to invalidate bindings that reference it, and it costs
    nothing at the ~200 call sites.
    """
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", backend)
    ctx.setContextProperty("i18n", i18n)
    i18n.langChanged.connect(lambda: ctx.setContextProperty("i18n", i18n))


def run(
    *,
    model: str = "n0110",
    real: bool = False,
    demo: bool = False,
    lang: str = "fr",
    argv: list[str] | None = None,
) -> int:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    configure_identity()
    app = _application(argv if argv is not None else sys.argv)
    icon = Path(__file__).parents[3] / "packaging" / "icon" / "icon_256.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # The shipped app starts DISCONNECTED unless asked otherwise — same contract as the web UI:
    # it never silently pretends a calculator is plugged in.
    session = Session(model, connect=False)
    if real:
        try:
            session.attach_real()
        except Exception as exc:  # stay up and let the UI show the "no calculator" state
            print(f"nwupdater: no real calculator ({exc})", file=sys.stderr)
    elif demo:
        session.attach_demo(model)

    from .backend import Backend
    from .i18n import I18n

    # Parented to the application: C++ owns them, so their lifetime is tied to something the
    # scene cannot outlive, instead of to a Python local freed in an unspecified order.
    backend = Backend(session, parent=app)
    i18n = I18n(lang, parent=app)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(_QML))
    install_context(engine, backend, i18n)
    app.aboutToQuit.connect(backend.shutdown)

    engine.load(QUrl.fromLocalFile(str(_QML / "Main.qml")))
    if not engine.rootObjects():
        print("nwupdater: the QML scene failed to load", file=sys.stderr)
        return 1
    code = app.exec()
    # Tear the scene down BEFORE the objects its bindings read. Dropped, the engine destroys its
    # root objects and their bindings; left to interpreter shutdown, the context properties can
    # go first and every live binding logs a "TypeError: ... of null" on the way out.
    del engine
    return code


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin wrapper
    return run(argv=argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

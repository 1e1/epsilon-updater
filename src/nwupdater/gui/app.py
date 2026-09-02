"""Entry point for the native UI: ``nwupdater gui``.

No local HTTP server, no browser — the QML front-end talks to :class:`Session` in-process.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..server.session import Session

_QML = Path(__file__).with_name("qml")


def run(
    *,
    model: str = "n0110",
    real: bool = False,
    demo: bool = False,
    lang: str = "fr",
    argv: list[str] | None = None,
) -> int:
    from PySide6.QtCore import QCoreApplication, Qt, QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    QCoreApplication.setOrganizationName("nwupdater")
    QCoreApplication.setOrganizationDomain("nwupdater.local")
    QCoreApplication.setApplicationName("nwupdater")
    QGuiApplication.setApplicationDisplayName("nwupdater")
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):  # harmless on Qt 6, kept for older runtimes
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QGuiApplication(argv if argv is not None else sys.argv)
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

    backend = Backend(session)
    i18n = I18n(lang)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(_QML))
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", backend)
    ctx.setContextProperty("i18n", i18n)
    backend.quitRequested.connect(app.quit)
    app.aboutToQuit.connect(backend.shutdown)

    engine.load(QUrl.fromLocalFile(str(_QML / "Main.qml")))
    if not engine.rootObjects():
        print("nwupdater: the QML scene failed to load", file=sys.stderr)
        return 1
    return app.exec()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin wrapper
    return run(argv=argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

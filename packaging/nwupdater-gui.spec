# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds the NATIVE-window app (Qt Quick).

  macOS   -> "NumWorks Updater (natif).app"
  Windows -> "NumWorks Updater (natif).exe"
  Linux   -> "NumWorks Updater (natif)"

Sibling of ``nwupdater.spec``, which builds the browser-based app. Both ship: the browser one is
the compatibility channel (no system floor, ~6 MB), this one is the native channel. See
docs/05-packaging-ui/native-ui-feasibility.md for why both exist.

Build:  pyinstaller packaging/nwupdater-gui.spec --noconfirm
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH)
APP_NAME = "NumWorks Updater (natif)"

# gui/qml/*, gui/assets/*, catalog/data/*.json, apps/data/*.json — but NOT server/web/*: the
# native app never serves a page.
datas = [t for t in collect_data_files("nwupdater")
         if "server/web" not in t[1].replace("\\", "/")]

binaries = []
for pkg in ("libusb_package", "usb"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

icon_icns = str(ROOT / "icon" / "icon.icns")
icon_ico = str(ROOT / "icon" / "icon.ico")
is_mac = sys.platform == "darwin"
is_win = sys.platform.startswith("win")
icon = icon_icns if is_mac else (icon_ico if is_win else None)
target_arch = os.environ.get("NWUPDATER_MAC_ARCH", "universal2") if is_mac else None

# Qt modules this UI never loads. PySide6's hook walks what it finds on disk, so anything the
# build machine happens to have installed can ride along; the list below makes the bundle
# independent of that. Measured on macOS arm64 with PySide6-Addons present: 126 -> 116 MB on
# disk, 40 -> 38 MB zipped. Modest, but it also pins the ceiling: without it, a machine with
# QtWebEngine installed would ship ~200 MB more.
#
# QtWidgets is deliberately NOT in this list, and the reason is narrower than it used to say:
# the file dialogs come from QtQuick.Dialogs, which needs nothing from Widgets. What does need
# it is Qt.labs.platform's MENU BAR — native on macOS only, and a widget-based fallback
# everywhere else, one that additionally requires the application object to be a QApplication
# (see gui/app.py::_application). Without both halves, Windows and any Linux desktop without a
# global menu ship a window with no menu bar at all. 6 MB is the right price for that.
_QT_UNUSED = [
    "WebEngineCore", "WebEngineWidgets", "WebEngineQuick", "WebChannel", "WebSockets",
    "Multimedia", "MultimediaWidgets", "SpatialAudio", "Charts", "DataVisualization",
    "Graphs", "GraphsWidgets", "Pdf", "PdfWidgets", "Bluetooth", "Nfc", "Positioning",
    "Location", "SerialPort", "SerialBus", "RemoteObjects", "Scxml", "StateMachine",
    "Sensors", "TextToSpeech", "NetworkAuth", "HttpServer", "Designer", "UiTools",
    "Help", "Sql", "Test", "Quick3D", "3DCore", "3DRender", "3DInput", "3DLogic",
    "3DAnimation", "3DExtras", "Concurrent", "PrintSupport", "QuickTest", "WebView",
    "CanvasPainter",
]
excludes = ["tkinter", "pytest", "PIL", "playwright"]
excludes += [f"PySide6.Qt{m}" for m in _QT_UNUSED]

a = Analysis(
    [str(ROOT / "gui_entry.py")],
    pathex=[str(ROOT.parent / "src")],
    datas=datas,
    binaries=binaries,
    hiddenimports=[
        "nwupdater.gui.app", "nwupdater.gui.backend",
        "usb", "usb.core", "usb.util", "usb.backend.libusb1", "libusb_package",
    ],
    excludes=excludes,
    noarchive=False,
    optimize=2,
)

# `excludes` stops the IMPORTS; the PySide6 hook still copies the frameworks and the QML plugin
# trees it found on disk. Drop those by path, which is where the megabytes actually are.
_DROP_QML = {
    "QtQuick3D", "QtCharts", "QtDataVisualization", "QtGraphs", "QtMultimedia", "QtWebEngine",
    "QtWebSockets", "QtWebChannel", "QtWebView", "QtPositioning", "QtLocation", "QtBluetooth",
    "QtNfc", "QtSensors", "QtRemoteObjects", "QtScxml", "QtStateMachine", "QtTest",
    "QtPdf", "QtTextToSpeech", "Qt3D", "QtQuickTest", "QtCanvasPainter",
}


def _keep(dest: str) -> bool:
    parts = dest.replace("\\", "/").split("/")
    if any(p.startswith(tuple(_DROP_QML)) for p in parts):
        return False
    # Qt ships a translation catalogue per module per locale; the app carries its own FR/EN.
    return "translations" not in parts


a.binaries = [t for t in a.binaries if _keep(t[0])]
a.datas = [t for t in a.datas if _keep(t[0])]

# Same stdlib trim as the browser app: this is not a numeric tool.
_UNUSED_EXT = {
    "_decimal", "pyexpat", "readline", "_sqlite3", "_curses", "_curses_panel",
    "_codecs_jp", "_codecs_kr", "_codecs_cn", "_codecs_tw", "_codecs_hk",
    "_codecs_iso2022", "_multibytecodec",
}
a.binaries = [t for t in a.binaries
              if Path(t[0]).name.split(".")[0] not in _UNUSED_EXT
              and "libncursesw" not in Path(t[0]).name]

pyz = PYZ(a.pure)

if is_mac:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
              console=False, icon=icon, target_arch=target_arch, strip=True)
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, strip=True)
    app = BUNDLE(coll, name=f"{APP_NAME}.app", icon=icon_icns,
                 bundle_identifier="com.numworks.updater.native",
                 info_plist={"CFBundleShortVersionString": "3.0.0",
                             "LSMinimumSystemVersion": "12.0",
                             "NSHighResolutionCapable": True})
else:
    # Qt is LGPL: keep it as separate, replaceable shared libraries (onedir), not a one-file
    # bundle. See docs/05-packaging-ui/native-ui-feasibility.md, "Licence".
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
              console=False, icon=icon, upx=False, target_arch=target_arch, strip=True)
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, strip=True)

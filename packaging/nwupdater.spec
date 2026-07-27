# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds the double-click NumWorks Updater app.

  macOS   -> "NumWorks Updater.app" (unsigned; first run: right-click > Open)
  Windows -> "NumWorks Updater.exe" (unsigned; first run: More info > Run anyway)
  Linux   -> "NumWorks Updater"     (chmod +x; run from file manager or terminal)

Requires the package importable at spec time (CI does `pip install -e .`).
Build:  pyinstaller packaging/nwupdater.spec --noconfirm
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH)
APP_NAME = "NumWorks Updater"

# bundle web/, catalog/data/*.json, apps/data/*.json
datas = collect_data_files("nwupdater")

# bundle the libusb shared library (from libusb-package) so the app talks to REAL hardware
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
# macOS: build universal2 (Intel + Apple Silicon). GitHub's Intel runners (macos-13) hang
# forever, and an arm64-only .app won't launch on Intel. The CI step "Universalize libusb"
# lipo-merges the libusb dylib to universal2 first so this build can succeed.
target_arch = "universal2" if is_mac else None

a = Analysis(
    [str(ROOT / "entry.py")],
    pathex=[str(ROOT.parent / "src")],
    datas=datas,
    binaries=binaries,
    hiddenimports=["nwupdater.cli", "usb", "usb.core", "usb.util",
                   "usb.backend.libusb1", "libusb_package"],
    excludes=["tkinter", "pytest", "PIL"],
    noarchive=False,
    optimize=2,  # drop docstrings/asserts from the bundled .pyc
)

# Trim the binary. This is a stdlib-only tool (no numpy/etc.), so the size is CPython + its
# stdlib. `excludes` above does NOT drop lib-dynload on a framework build — PyInstaller copies
# the whole dir — so filter the C-extension TOC directly. Verified by booting the frozen app
# and serving a request. KEEP: unicodedata (http.server's bind path pulls the IDNA codec, which
# needs it), _ssl/_hashlib (HTTPS + firmware hashing), ctypes (pyusb loads it lazily), lzma/bz2
# (pulled by shutil). Names are arch/ext-agnostic (.so / .pyd), so this is cross-platform.
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
    # onedir inside an .app bundle
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
              console=False, icon=icon, target_arch=target_arch, strip=True)
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, strip=True)
    app = BUNDLE(coll, name=f"{APP_NAME}.app", icon=icon_icns,
                 bundle_identifier="com.numworks.updater",
                 info_plist={"CFBundleShortVersionString": "0.1.0",
                             "LSMinimumSystemVersion": "10.13",
                             "NSHighResolutionCapable": True})
else:
    # single double-click file on Windows / Linux
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name=APP_NAME,
              console=False, icon=icon, upx=False, target_arch=target_arch, strip=True)

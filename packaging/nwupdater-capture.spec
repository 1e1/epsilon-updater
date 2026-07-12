# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds the `nwupdater-capture` CLI executable (web-feature discovery).

Single-file console binary bundling capture-hook.js. No USB/libusb (capture goes through the
browser), so it stays small. Build:  pyinstaller packaging/nwupdater-capture.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)
APP = "nwupdater-capture"
# macOS: build a universal2 (Intel + Apple Silicon) binary — GitHub Intel runners are gone,
# and an arm64-only binary won't run on Intel Macs. Pure-Python here → universal2 is clean.
TARGET_ARCH = "universal2" if sys.platform == "darwin" else None

# bundle package data incl. nwupdater/tools/web/capture-hook.js (read by capture_cli at runtime)
datas = collect_data_files("nwupdater")

a = Analysis(
    [str(ROOT / "capture_entry.py")],
    pathex=[str(ROOT.parent / "src")],
    datas=datas,
    hiddenimports=["nwupdater.tools.capture_cli", "nwupdater.tools.capture_analyze",
                   "nwupdater.tools.scrub"],
    excludes=["tkinter", "pytest", "PIL", "usb", "libusb_package", "pyusb"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# one-file console executable (binaries + datas embedded)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name=APP, console=True, upx=False,
          target_arch=TARGET_ARCH)

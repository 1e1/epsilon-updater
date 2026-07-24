"""nwupdater CLI entry point: argument parsing + dispatch.

Command handlers live in :mod:`nwupdater.cli_commands`; device acquisition in
:mod:`nwupdater.cli_device`.

    nwupdater identify --virtual n0110
    nwupdater identify              # real device (requires: pip install nwupdater[usb])
"""

from __future__ import annotations

import argparse

from . import DISCLAIMER_SHORT
from .cli_commands import (
    _cmd_apps,
    _cmd_cache,
    _cmd_capture,
    _cmd_catalog,
    _cmd_diagnose,
    _cmd_identify,
    _cmd_install,
    _cmd_login,
    _cmd_pair,
    _cmd_preload,
    _cmd_scripts,
    _cmd_ui,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwupdater",
        description="NumWorks updater (headless, no WebUSB) — independent, UNofficial project",
        epilog=f"WARNING: {DISCLAIMER_SHORT}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="sign in to my.numworks.com (token, to download the OS)")
    p_login.add_argument("--token", metavar="VALUE", help="paste the remember_user_token cookie value directly")
    p_login.add_argument("--email", metavar="ADDR", help="built-in login: account email (password prompted)")
    p_login.add_argument("--password", metavar="PWD", help="password (otherwise prompted without echo) — never stored")
    p_login.add_argument("--status", action="store_true", help="show the stored token status")
    p_login.add_argument("--logout", action="store_true", help="remove the stored token")
    p_login.set_defaults(func=_cmd_login)

    p_id = sub.add_parser("identify", help="read a calculator's model + OS version")
    p_id.add_argument("--virtual", metavar="MODEL", help="use a virtual device (n0110, n0120, n0200…)")
    p_id.add_argument("--os-version", default="23.2.4", help="virtual device OS version")
    p_id.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_id.set_defaults(func=_cmd_identify)

    p_cat = sub.add_parser("catalog", help="list available updates for a calculator")
    p_cat.add_argument("--virtual", metavar="MODEL", help="use a virtual device (n0110, n0200…)")
    p_cat.add_argument("--os-version", default="23.2.4", help="virtual device OS version")
    p_cat.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_cat.add_argument("--fetch", action="store_true", help="refresh the catalog online (my.numworks.com)")
    p_cat.add_argument("--catalog-file", metavar="PATH", help="load the catalog from a local JSON file")
    p_cat.set_defaults(func=_cmd_catalog)

    p_ins = sub.add_parser("install", help="flash a firmware (demo: against the virtual device)")
    p_ins.add_argument("--virtual", metavar="MODEL", help="use a virtual device (n0110, n0200…)")
    p_ins.add_argument("--os-version", default="23.2.4", help="virtual device current OS version")
    p_ins.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_ins.add_argument("--to-version", default="99.9.9", help="target version (synthetic image)")
    p_ins.add_argument("--download", action="store_true",
                       help="download the real official firmware (requires 'login')")
    p_ins.add_argument("--channel", default="stable", choices=["stable", "beta"],
                       help="download channel (stable/beta)")
    p_ins.add_argument("--dfuse", metavar="PATH", help="flash a real .dfu (DfuSe) file")
    p_ins.add_argument("--from-cache", action="store_true", help="flash from the cache (pre-downloaded)")
    p_ins.add_argument("--cache-dir", metavar="DIR", help="firmware cache directory")
    p_ins.add_argument("--active-slot", default="A", choices=["A", "B"], help="active slot (A/B)")
    p_ins.add_argument("--no-verify", action="store_true", help="disable read-back verification")
    p_ins.add_argument("--boot", action="store_true", help="boot the flashed slot (detach+jump)")
    p_ins.add_argument("--yes", "-y", action="store_true",
                       help="skip the confirmation before flashing a REAL calculator")
    p_ins.set_defaults(func=_cmd_install)

    p_app = sub.add_parser("apps", help="list / install / uninstall / reorder third-party apps")
    p_app.add_argument("--virtual", metavar="MODEL", help="use a virtual device (n0110, n0200…)")
    p_app.add_argument("--os-version", default="23.2.4", help="virtual device OS version")
    p_app.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_app.add_argument("--api-level", type=int, default=0, help="device EXTERNAL_APPS_API_LEVEL")
    p_app.add_argument("--store-file", metavar="PATH", help="local app catalog JSON")
    p_app.add_argument("--install", metavar="NAME", help="install a catalog app (demo: synthetic .nwa)")
    p_app.add_argument("--list-device", action="store_true",
                       help="list the apps installed ON the calculator (read-only)")
    p_app.add_argument("--push", metavar="FILE", help="install a local .nwa onto the calculator")
    p_app.add_argument("--uninstall", metavar="NAME",
                       help="remove an installed app (compacts the region)")
    p_app.add_argument("--reorder", metavar="A,B,C",
                       help="reorder installed apps (comma-separated names)")
    p_app.add_argument("--yes", "-y", action="store_true",
                       help="skip the confirmation prompt before writing to the device")
    p_app.set_defaults(func=_cmd_apps)

    p_pre = sub.add_parser("preload", help="pre-download an OS into the cache (classroom mode)")
    p_pre.add_argument("model", help="model (n0110, n0120, n0200…)")
    p_pre.add_argument("version", nargs="?", help="version to cache (e.g. 25.2.0); omit with --download")
    p_pre.add_argument("--download", action="store_true",
                       help="download the real official firmware (requires 'login')")
    p_pre.add_argument("--channel", default="stable", choices=["stable", "beta"],
                       help="download channel (stable/beta)")
    p_pre.add_argument("--cache-dir", metavar="DIR", help="firmware cache directory")
    p_pre.set_defaults(func=_cmd_preload)

    p_ca = sub.add_parser("cache", help="firmware cache status (status / prune / clear)")
    p_ca.add_argument("--prune", action="store_true", help="remove expired entries (>30 d)")
    p_ca.add_argument("--clear", action="store_true", help="clear the cache")
    p_ca.add_argument("--cache-dir", metavar="DIR", help="firmware cache directory")
    p_ca.set_defaults(func=_cmd_cache)

    p_diag = sub.add_parser("diagnose", help="read-only diagnostic + USB capture (hardware harness)")
    p_diag.add_argument("--virtual", metavar="MODEL", help="self-test against a virtual device (n0110…)")
    p_diag.add_argument("--os-version", default="23.2.4", help="virtual device OS version")
    p_diag.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_diag.add_argument("--out", metavar="FILE", help="JSON report path (default: nwupdater-diagnostic-<ts>.json)")
    p_diag.set_defaults(func=_cmd_diagnose)

    p_cap = sub.add_parser("capture", help="capture the USB+WEB sequence (no flash) → JSON dump")
    p_cap.add_argument("--virtual", metavar="MODEL", help="self-test against a virtual device")
    p_cap.add_argument("--os-version", default="1.0.0", help="virtual device OS version")
    p_cap.add_argument("--model", metavar="Nxxxx", help="server-side target model (default: derived from bcdDevice)")
    p_cap.add_argument("--channel", default="stable", choices=["stable", "beta"], help="firmware channel")
    p_cap.add_argument("--out", metavar="FILE", help="JSON dump path")
    p_cap.set_defaults(func=_cmd_capture)

    p_pair = sub.add_parser("pair", help="pair the calculator to the account (heartbeat POST /devices)")
    p_pair.add_argument("--virtual", metavar="MODEL", help="virtual device (n0110, n0200…)")
    p_pair.add_argument("--os-version", default="3.0.0", help="virtual device OS version")
    p_pair.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_pair.add_argument("--dry-run", action="store_true",
                        help="read the identity and print the request WITHOUT sending it (no auth)")
    p_pair.set_defaults(func=_cmd_pair)

    p_ui = sub.add_parser("ui", help="open the local web UI in the browser")
    p_ui.add_argument("--virtual", metavar="MODEL", default=None,
                      help="force a demo (virtual) device instead of real-first detection")
    p_ui.add_argument("--os-version", default="23.2.4", help="virtual device OS version")
    p_ui.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_ui.add_argument("--api-level", type=int, default=0, help="device EXTERNAL_APPS_API_LEVEL")
    p_ui.add_argument("--host", default="127.0.0.1", help="listen address (loopback by default)")
    p_ui.add_argument("--port", type=int, default=8765, help="listen port")
    p_ui.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p_ui.add_argument("--single-instance", action="store_true", help="reuse an already-running instance")
    p_ui.add_argument("--idle-timeout", type=float, default=0, help="auto-stop after N s idle (0=disabled)")
    p_ui.set_defaults(func=_cmd_ui)

    p_scr = sub.add_parser("scripts", help="list / export / push Python scripts (storage)")
    p_scr.add_argument("--virtual", metavar="MODEL", help="virtual device (n0110, n0120…)")
    p_scr.add_argument("--os-version", default="23.2.4", help="virtual device OS version")
    p_scr.add_argument("--commit", default="abc1234", help="virtual device commit")
    p_scr.add_argument("--pull", metavar="NAME", help="export a script from storage to a .py file")
    p_scr.add_argument("--push", metavar="FILE", help="push a local .py into storage (RAM write)")
    p_scr.add_argument("--out", metavar="FILE", help="output file for --pull")
    p_scr.add_argument("--no-auto-import", action="store_true",
                       help="do not mark the script as auto-imported")
    p_scr.add_argument("--yes", "-y", action="store_true",
                       help="skip the confirmation prompt before writing")
    p_scr.set_defaults(func=_cmd_scripts)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""nwupdater CLI.

For now it exposes an ``identify`` command. Against a real calculator it needs pyusb
(extra ``usb``); against the built-in virtual device it needs nothing — this is how we
develop and demo without ever touching real USB.

    nwupdater identify --virtual n0110
    nwupdater identify              # real device (requires: pip install nwupdater[usb])
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable, NamedTuple

from . import DISCLAIMER_SHORT
from .dfu.identity import read_identity
from .dfu.protocol import DfuClient
from .models import describe_bcd


def _print_disclaimer() -> None:
    print(f"⚠️  {DISCLAIMER_SHORT}\n", file=sys.stderr)


def _cmd_identify(args) -> int:
    opened = _open_device(args)
    client, bcd = opened.client, opened.bcd
    print(f"[virtual] {describe_bcd(bcd)}" if args.virtual else describe_bcd(bcd))

    ident = read_identity(client, bcd)
    print(f"  model     : {ident.model_name} ({ident.family})")
    print(f"  serial    : {ident.serial_number or '?'}")
    print(f"  OS        : {ident.os_version or '?'}  kernel={ident.kernel_version or '?'}")
    print(f"  commit    : {ident.commit or '?'}")
    if ident.external_apps_flash and ident.external_apps_flash != (0, 0):
        s, e = ident.external_apps_flash
        print(f"  apps zone : 0x{s:08x}-0x{e:08x} ({(e - s) // 1024} KiB)")
    print(f"  slotinfo  : {'valid' if ident.slot_info_valid else 'missing/invalid'}")
    return 0


def _cmd_catalog(args) -> int:
    from .catalog.firmware import FirmwareCatalog

    if args.fetch:
        try:
            catalog = FirmwareCatalog.fetch()
            src = "live (my.numworks.com)"
        except Exception as exc:  # network issues -> fall back to snapshot
            print(f"live fetch failed ({exc}); falling back to the bundled snapshot", file=sys.stderr)
            catalog = FirmwareCatalog.bundled()
            src = "bundled snapshot"
    elif args.catalog_file:
        catalog = FirmwareCatalog.load(args.catalog_file)
        src = args.catalog_file
    else:
        catalog = FirmwareCatalog.bundled()
        src = "bundled snapshot"

    # identity (virtual by default so it runs without USB)
    opened = _open_device(args)
    client, bcd = opened.client, opened.bcd
    ident = read_identity(client, bcd)

    latest = catalog.latest()
    print(f"catalog   : {len(catalog)} versions (source: {src}) — latest {latest}")
    print(f"calc      : {ident.model_name} ({ident.family}) OS {ident.os_version or '?'}")
    if ident.os_version and catalog.is_up_to_date(ident.os_version):
        print("→ up to date ✅")
        return 0
    updates = catalog.updates_for(ident.os_version or "0.0.0")
    print(f"→ {len(updates)} update(s) available:")
    for r in updates:
        tag = "  (latest)" if r is latest else ""
        print(f"    {r.version}{tag}")
    return 0


def _cmd_login(args) -> int:
    """Manage the NumWorks auth token (bring-your-own-token style)."""
    from .catalog import auth as A

    if args.status:
        a = A.load_auth()
        if a is None:
            print("not signed in — no token stored.")
            return 1
        print(f"signed in: {a.summary()}")
        print(f"stored in: {A.config_path()}")
        return 1 if a.is_expired() else 0
    if args.logout:
        print("token removed." if A.clear_auth() else "no token to remove.")
        return 0

    _print_disclaimer()
    if args.email:
        # Option B: built-in login (the password is never stored, only the token).
        import getpass
        pwd = args.password or getpass.getpass("NumWorks password: ")
        try:
            a = A.login_with_password(args.email, pwd)
        except (A.AuthError, A.TransportError) as exc:
            print(f"login failed: {exc}", file=sys.stderr)
            return 1
    else:
        # Option A: the user pastes the token (the password never touches the tool).
        if not args.token:
            print("Open https://my.numworks.com/users/sign_in in your browser and sign in")
            print("(tick \u201cRemember me\u201d), then copy the value of the cookie")
            print("\u201cremember_user_token\u201d (DevTools \u2192 Application \u2192 Cookies \u2192 my.numworks.com).\n")
        token = (args.token or input("remember_user_token > ")).strip()
        if not token:
            print("no token provided.", file=sys.stderr)
            return 1
        a = A.Auth(token)

    if not a.info().get("looks_valid"):
        print("\u26a0\ufe0f  this token does not look like a NumWorks remember_user_token — saved anyway.",
              file=sys.stderr)
    path = A.save_auth(a)
    print(f"✓ {a.summary()} — saved to {path}")
    return 0


def _require_auth():
    """Load the stored token, or None + a help message."""
    from .catalog import auth as A
    a = A.load_auth()
    if a is None:
        print("not signed in — run: nwupdater login", file=sys.stderr)
        return None
    if a.is_expired():
        print("token expired — run: nwupdater login", file=sys.stderr)
        return None
    return a


def _cmd_install(args) -> int:
    from .install.image import FirmwareImage
    from .install.installer import Installer
    from .models import MODELS

    _print_disclaimer()
    opened = _open_device(args)
    client, bcd = opened.client, opened.bcd

    model = MODELS.get(bcd)
    if model is None:
        print(f"unknown model (bcd 0x{bcd:04x})", file=sys.stderr)
        return 1
    ident = read_identity(client, bcd)
    print(f"calc      : {ident.model_name} ({ident.family}) OS {ident.os_version or '?'}")

    # Safety: flashing REAL hardware is destructive and irreversible if interrupted.
    if not args.virtual and not args.yes:
        print(f"\n\u26a0\ufe0f  You are about to FLASH a REAL calculator ({ident.model_name}). A "
              "power loss\n   or a wrong image can damage it or brick it.")
        print("   Classroom use: if the user is a minor, operate under adult supervision.")
        if input("   Type 'yes' to confirm (counts as acknowledgment): ").strip().lower() not in ("y", "yes"):
            print("cancelled.", file=sys.stderr)
            return 1

    if args.from_cache:
        from .cache.store import FirmwareCache
        blob = FirmwareCache(args.cache_dir).get(model.name, args.to_version)
        if blob is None:
            print(f"not in cache: {model.name} v{args.to_version} — run 'preload' first",
                  file=sys.stderr)
            return 1
        image = FirmwareImage.from_dfuse(blob)
        print(f"image     : from cache — {model.name} v{args.to_version} ({image.total_size} B)")
    elif args.download:
        from .catalog import download as D
        a = _require_auth()
        if a is None:
            return 1
        try:
            manifest, blob = D.fetch_firmware(model.name, args.channel, a)
        except (D.AuthRequired, D.DownloadError) as exc:
            print(f"download failed: {exc}", file=sys.stderr)
            return 1
        image = FirmwareImage.from_dfuse(blob)
        from datetime import datetime, timezone
        sha256 = D.sha256_hex(blob)
        log_path = D.record_download(manifest, sha256,
                                     when=datetime.now(timezone.utc).isoformat())
        print(f"image     : downloaded {model.name} [{args.channel}] v{manifest.version} "
              f"(patch {manifest.patch_level}, {image.total_size} B)")
        print(f"sha256    : {sha256}")
        print(f"provenance: logged to {log_path}")
    elif args.dfuse:
        with open(args.dfuse, "rb") as f:
            image = FirmwareImage.from_dfuse(f.read())
        print(f"image     : {args.dfuse} (DfuSe, {image.total_size} B)")
    else:
        image = FirmwareImage.synthetic(model, version=args.to_version)
        print(f"image     : synthetic v{args.to_version} ({image.total_size} B) [offline demo]")

    def progress(phase, done, total):
        pct = 100 * done // max(total, 1)
        print(f"\r  {phase:6s} {pct:3d}% ({done}/{total} o)", end="", flush=True)

    inst = Installer(client, model, progress=progress)
    try:
        plan = inst.install(image, active_slot=args.active_slot, verify=not args.no_verify, boot=args.boot)
    except Exception as exc:
        print(f"\ninstall failed: {exc}", file=sys.stderr)
        return 1
    print()
    if plan.full_image:
        print("image     : full — slots A+B written verbatim (like the official updater)")
    elif plan.target_slot:
        print(f"target    : slot {plan.target_slot} (inactive) — flashed + verified")
    installed = inst.read_installed_version(plan)
    if installed is None and model.opaque_firmware:
        print("verify    : N02xx firmware is encrypted/opaque — version not readable from the binary "
              "(source = manifest; see docs/01-specs/n02xx-firmware-format.md)")
    else:
        print(f"verify    : installed version read back = {installed}")
    if args.boot:
        print(f"boot      : jump requested to 0x{plan.boot_address:08x} (device detached)")
    return 0


def _cmd_apps(args) -> int:
    from pathlib import Path

    from .apps.installer import AppInstaller
    from .apps.manage import AppError, AppManager
    from .apps.store import THIRD_PARTY_WARNING, AppStore

    opened = _open_device(args)
    client, bcd = opened.client, opened.bcd
    ident = read_identity(client, bcd)
    has_region = bool(ident.external_apps_flash and ident.external_apps_flash != (0, 0))
    mgr = AppManager(client, ident.external_apps_flash, device_api_level=args.api_level)

    def confirm(prompt: str) -> bool:
        return args.virtual or getattr(args, "yes", False) or \
            input(prompt).strip().lower() in ("y", "yes")

    # write actions (mutate the device) — install / uninstall / reorder
    if args.push or args.uninstall or args.reorder:
        if not has_region:
            print("this model has no external-apps region", file=sys.stderr)
            return 1
        try:
            if args.push:
                if not confirm(f"{THIRD_PARTY_WARNING}\nInstall this .nwa? [y/N] "):
                    print("cancelled.", file=sys.stderr)
                    return 1
                m = mgr.push(Path(args.push).read_bytes())
                print(f"→ installed '{m.name}' ({len(m.blob)} B), region rewritten, verified ✅")
            if args.uninstall:
                if not confirm(f"Uninstall '{args.uninstall}'? [y/N] "):
                    print("cancelled.", file=sys.stderr)
                    return 1
                mgr.uninstall(args.uninstall)
                print(f"→ uninstalled '{args.uninstall}', region compacted, verified ✅")
            if args.reorder:
                mgr.reorder([s.strip() for s in args.reorder.split(",") if s.strip()])
                print(f"→ reordered: {args.reorder}")
        except (AppError, OSError, ValueError) as exc:
            print(f"failed: {exc}", file=sys.stderr)
            return 1
        return 0

    # list the apps installed on the calculator (read-only)
    if getattr(args, "list_device", False):
        installed = mgr.installed()
        print(f"on the calculator: {len(installed)} app(s) installed")
        for m in installed:
            print(f"    {m.name:16s} API {m.api_level}  ({len(m.blob)} B)")
        return 0

    # list the catalog + client-side compatibility
    store = AppStore.load(args.store_file) if args.store_file else AppStore.bundled()
    compat = store.compatible(family=ident.family, device_api_level=args.api_level,
                              has_external_apps=has_region)
    print(f"calc      : {ident.model_name} ({ident.family}) OS {ident.os_version or '?'}")
    print(f"catalog   : {len(store)} apps — {len(compat)} compatible (API level {args.api_level})")
    for e in compat:
        print(f"    {e.name:12s} v{e.version:5s} — {e.description}")
    if not has_region:
        print("    (no external-apps region on this model)")

    if args.install:
        from .formats.nwa import build_nwa
        entry = store.get(args.install)
        if entry is None:
            print(f"unknown app: {args.install}", file=sys.stderr)
            return 1
        print(f"\n⚠️  {THIRD_PARTY_WARNING}")
        if not confirm("   Install? [y/N] "):
            print("cancelled.", file=sys.stderr)
            return 1
        # offline demo: synthesize a .nwa (catalog URLs are placeholders)
        blob = build_nwa(entry.name, api_level=entry.api_level, code=b"\x00" * 1024)
        inst = AppInstaller(client, external_apps_flash=ident.external_apps_flash or (0, 0),
                            device_api_level=args.api_level)
        try:
            res = inst.install(blob)
        except Exception as exc:
            print(f"app install failed: {exc}", file=sys.stderr)
            return 1
        print(f"→ installed '{res.name}' @0x{res.address:08x} ({res.size} B), verified ✅")
    return 0


def _cmd_scripts(args) -> int:
    from pathlib import Path

    from .formats.storage import make_python, python_scripts
    from .scripts import read_storage, write_storage

    opened = _open_device(args)
    client, bcd = opened.client, opened.bcd
    ident = read_identity(client, bcd)
    if not ident.storage_ram:
        print("this model has no Python scripts (no storage).", file=sys.stderr)
        return 1
    addr, size = ident.storage_ram
    records = read_storage(client, addr, size)
    pys = python_scripts(records)

    if args.pull:
        want = args.pull if args.pull.endswith(".py") else args.pull + ".py"
        rec = next((r for r in pys if r.fullname == want), None)
        if rec is None:
            print(f"script not found: {args.pull}", file=sys.stderr)
            return 1
        Path(args.out or rec.fullname).write_text(rec.code, encoding="utf-8")
        print(f"→ exported {rec.fullname} to {args.out or rec.fullname}")
        return 0

    if args.push:
        src = Path(args.push)
        name = src.stem
        target = [r for r in records if r.fullname != name + ".py"]  # read-modify-write
        target.append(make_python(name, src.read_text(encoding="utf-8"),
                                   auto_import=not args.no_auto_import))
        if not args.virtual and not args.yes:
            if input(f"Write {name}.py to storage (RAM)? [y/N] ").strip().lower() not in ("y", "yes"):
                print("cancelled.", file=sys.stderr)
                return 1
        n = write_storage(client, addr, target, capacity=size)
        print(f"→ pushed {name}.py; storage rewritten ({n} B / {size} B), verified ✅")
        return 0

    print(f"calc      : {ident.model_name} ({ident.family}) — storage {size} B")
    print(f"scripts   : {len(pys)}")
    for r in pys:
        print(f"    {r.fullname:20s} {len(r.code):5d} B  [{'auto-import' if r.auto_import else '—'}]")
    return 0


def _human(n):
    for u in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} GB"


def _cmd_preload(args) -> int:
    """Pre-download an OS into the cache (demo: synthetic image)."""
    from .cache.store import FirmwareCache
    from .install.image import FirmwareImage
    from .models import MODELS

    model = next((m for m in MODELS.values() if m.name == args.model), None)
    if model is None:
        print(f"unknown model: {args.model}", file=sys.stderr)
        return 1
    if args.download:
        from .catalog import download as D
        a = _require_auth()
        if a is None:
            return 1
        try:
            manifest, blob = D.fetch_firmware(model.name, args.channel, a)
        except (D.AuthRequired, D.DownloadError) as exc:
            print(f"download failed: {exc}", file=sys.stderr)
            return 1
        version = manifest.version
    else:
        if not args.version:
            print("give a version, or use --download to fetch the latest official one",
                  file=sys.stderr)
            return 1
        blob = FirmwareImage.synthetic(model, version=args.version).to_dfuse()
        version = args.version
    cache = FirmwareCache(args.cache_dir)
    entry = cache.put(model.name, version, blob)
    st = cache.status()
    print(f"pre-downloaded: {model.name} v{version} ({_human(entry.size)})")
    print(f"cache         : version {st['version']} · models {st['models']} · {_human(st['total_size'])}")
    print("→ ready to flash a whole class offline (one version kept, purged at 30 days).")
    return 0


def _cmd_cache(args) -> int:
    import time as _t

    from .cache.store import FirmwareCache
    cache = FirmwareCache(args.cache_dir)
    if args.clear:
        cache.clear()
        print("cache cleared.")
        return 0
    if args.prune:
        removed = cache.prune()
        print(f"pruned: {len(removed)} expired entry(ies) removed.")
    st = cache.status()
    if not st["version"]:
        print("cache empty.")
        return 0
    days = max(0, (st["expires_at"] - _t.time()) / 86400)
    print(f"version   : {st['version']}")
    print(f"models    : {', '.join(st['models'])}")
    print(f"size      : {_human(st['total_size'])}")
    print(f"expires   : in {days:.0f} d (TTL {st['ttl_days']} d)")
    return 0


def _cmd_ui(args) -> int:
    from .server.httpd import serve
    from .server.session import Session

    # Real-first: the shipped app starts DISCONNECTED and attaches a real calculator only if
    # one is actually plugged in. --virtual forces a demo device; otherwise the UI offers a
    # "rescan" and an explicit "explore a demo" button. It never fakes a detection.
    session = Session(os_version=args.os_version, commit=args.commit,
                      api_level=args.api_level, connect=False, live_catalog=True)
    if args.virtual:
        session.attach_demo(args.virtual, os_version=args.os_version, commit=args.commit)
    else:
        try:
            session.attach_real()
        except Exception as exc:  # no hardware → stay disconnected; the browser UI handles it
            print(f"no calculator detected ({exc}); connect one or use demo from the browser.",
                  file=sys.stderr)
    serve(session, host=args.host, port=args.port, open_browser=not args.no_browser,
          single_instance=args.single_instance,
          idle_timeout=args.idle_timeout if args.idle_timeout > 0 else None)
    return 0


def _cmd_diagnose(args) -> int:
    """Read-only diagnostic + USB capture harness (for volunteers on a real machine)."""
    import datetime
    import json

    from .diagnose import diagnose
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    opened = _open_device(args)
    report = diagnose(opened.dev, interface=opened.iface, bcd_device=opened.bcd,
                      sleep=opened.sleep, timestamp=ts)

    out = args.out or f"nwupdater-diagnostic-{ts.replace(':', '').replace('-', '')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"model     : {report['model']} ({report['family']})")
    print(f"serial    : {report['serial_number'] or '?'}")
    print(f"OS        : {report['os_version'] or '?'}  kernel={report['kernel_version'] or '?'}"
          f"  commit={report['commit'] or '?'}")
    print(f"transfers : {report['transfer_count']} captured")
    if report["error"]:
        print(f"error     : {report['error']}", file=sys.stderr)
    print(f"→ report written: {out}")
    print("  (READ-ONLY — nothing was written to the calculator; send this file.)")
    return 0


def _cmd_capture(args) -> int:
    """Bespoke capture (real hardware): USB + WEB dialogue, NO flash. Needs login + pyusb."""
    import datetime
    import json

    from .capture_session import run_capture
    from .catalog import auth as A
    a = A.load_auth()
    if a is None or a.is_expired():
        print("authentication required: run `nwupdater login` first", file=sys.stderr)
        return 2
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    opened = _open_device(args)
    dev, bcd, iface, sleep = opened.dev, opened.bcd, opened.iface, opened.sleep
    # Serial number via the transport-agnostic client (works virtual + real).
    from .dfu import constants as C
    serial = opened.client.get_string_descriptor(C.SERIAL_STRING_INDEX)

    model = args.model or f"n{bcd:04x}"
    dump = run_capture(dev, auth=a, transport=A.UrllibTransport(), interface=iface,
                       bcd_device=bcd, model=model, channel=args.channel, sleep=sleep,
                       timestamp=ts, serial=serial)
    out = args.out or f"nwupdater-capture-{ts.replace(':', '').replace('-', '')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

    print(f"calc      : {dump['usb']['model']} ({dump['usb']['family']}) OS {dump['usb']['os_version'] or '?'}")
    print(f"USB       : {dump['usb']['transfer_count']} transfers (read-only)")
    print(f"WEB       : {model}/{args.channel} → {dump['web']['outcome']}"
          + (f" — {dump['web'].get('error')}" if dump['web'].get('error') else ""))
    enr = dump.get("enrollment", {})
    nforms = len(enr.get("forms") or [])
    print(f"enroll    : portal read (HTTP {enr.get('status', '?')}), {nforms} form(s) "
          f"— READ-ONLY, nothing enrolled"
          + (f" — {enr['error']}" if enr.get("error") else ""))
    print(f"flashed   : {dump['flashed']}  (replayable sequence)")
    print(f"→ dump written: {out}  — send this file (secrets redacted, firmware not included).")
    return 0


def _cmd_pair(args) -> int:
    """Pair the calculator to the account: POST /devices/{serial} (heartbeat)."""
    import json as _json

    from .catalog import device as DEV
    from .models import MODELS

    opened = _open_device(args)
    client, bcd = opened.client, opened.bcd
    model = MODELS.get(bcd)
    if model is None:
        print(f"unknown model (bcd 0x{bcd:04x})", file=sys.stderr)
        return 1

    ident = DEV.read_device_identity(client, model)
    body = {"device": {"device_model": ident["device_model"]},
            "firmware": {"software_version": ident["software_version"],
                         "software_patch_level": ident["software_patch_level"]}}
    print(f"calc      : {ident['device_model']}  serial {ident['serial'] or '?'}")
    print(f"firmware  : {ident['software_version'] or '?'} (patch {ident['software_patch_level'] or '?'})")
    print(f"heartbeat : POST /devices/{ident['serial'] or '{serial}'}  "
          f"{_json.dumps(body, ensure_ascii=False)}")

    if args.dry_run:
        print("→ dry-run: nothing sent.")
        return 0
    if not ident["serial"]:
        print("serial number unavailable — cannot pair", file=sys.stderr)
        return 1
    a = _require_auth()
    if a is None:
        return 1
    from .catalog import auth as A
    try:
        res = DEV.pair_device(client, model, a, transport=A.UrllibTransport())
    except (A.TransportError, ValueError) as exc:
        print(f"pairing failed: {exc}", file=sys.stderr)
        return 1
    print(f"→ registered: HTTP {res['register']['status']}")
    return 0


def _open_real_device():
    """Open + configure + claim a real calculator's DFU interface. Production only.

    Returns ``(device, bcdDevice, interface)``. Exits with a helpful message if pyusb is
    missing or no calculator/DFU interface is available."""
    from .dfu import usbio
    try:
        od = usbio.open_calculator()
    except usbio.PyusbMissing as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except usbio.UsbError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    return od.dev, od.bcd_device, od.interface


def _nosleep(*_) -> None:
    """No-op sleep for the in-memory virtual device (no real DFU polling delay)."""


class _Opened(NamedTuple):
    """A device opened for a CLI command (virtual or real)."""

    dev: object
    bcd: int
    client: DfuClient
    iface: int
    sleep: Callable[..., None]


def _open_device(args) -> _Opened:
    """Open the device a CLI command targets — the in-memory virtual device when ``--virtual``,
    otherwise a real calculator (pyusb). One place instead of the per-command copy.

    ``client`` is ``DfuClient(dev, interface=iface, sleep=sleep)`` in both cases; ``iface`` and
    ``sleep`` are also returned for the read-only harnesses (diagnose/capture) that drive the raw
    device with their own timing."""
    if args.virtual:
        from .testing.virtual_dfu import virtual_calculator
        kw: dict[str, str] = {}
        if getattr(args, "os_version", None) is not None:
            kw["os_version"] = args.os_version
        if getattr(args, "commit", None) is not None:
            kw["commit"] = args.commit
        dev = virtual_calculator(args.virtual, **kw)
        return _Opened(dev, dev.bcdDevice, DfuClient(dev, sleep=_nosleep), 0, _nosleep)
    dev, bcd, iface = _open_real_device()
    return _Opened(dev, bcd, DfuClient(dev, interface=iface), iface, time.sleep)


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

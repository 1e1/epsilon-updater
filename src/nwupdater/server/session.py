"""Session layer: holds a connected calculator (virtual by default) and exposes the Lot
2/3/4 operations as plain dicts for the local HTTP API.

Virtual by default so the whole UI runs with zero hardware. ``real=True`` would use pyusb.
"""

from __future__ import annotations

from ..apps.installer import AppInstaller
from ..apps.store import AppStore
from ..cache.store import FirmwareCache
from ..capabilities import Capabilities, Policy, resolve
from ..catalog.firmware import FirmwareCatalog
from ..dfu.identity import CalculatorIdentity, read_identity
from ..dfu.protocol import DfuClient
from ..formats.nwa import AppInfo, build_nwa
from ..install.image import FirmwareImage
from ..install.installer import Installer
from ..models import MODELS, describe_bcd


class Session:
    def __init__(self, model_name: str = "n0110", os_version: str = "23.2.4",
                 commit: str = "abc1234", *, api_level: int = 0, real: bool = False,
                 cache_dir=None, connect: bool = True, live_catalog: bool = False):
        self.api_level = api_level
        self.installed_apps: list[dict] = []
        self._cache_dir = cache_dir
        self._cache = None
        self._last_boot_address = None  # set after a flash: address to jump to on "boot now"
        self.channel = "stable"
        self.catalog = FirmwareCatalog.bundled()                      # Graphing N01xx (2x.x)
        self.sci_catalog = FirmwareCatalog.bundled("firmwares-n0200")  # Scientific N0200 (3.x)
        self.store = AppStore.bundled()
        # Live per-model catalogue: when signed in, the official manifest gives the *real*
        # latest for {model}/{channel}. OFF by default so tests never touch the network — the
        # `ui` server turns it on. Bundled snapshots stay the offline/anonymous fallback.
        self._live_catalog = live_catalog
        self._manifest_cache: dict = {}
        self._auth_override = None  # tests inject an Auth here; production reads the stored token
        self._transport = None      # tests inject a fake transport here
        # Device state. The shipped app starts DISCONNECTED and either attaches a real
        # calculator (hardware plugged in) or an explicit demo device — it never fakes a
        # detection silently. Tests keep the old ergonomics via connect=True (default).
        self._demo_defaults = (model_name, os_version, commit)
        self.device = self.client = self.model = self.bcd = None
        self.virtual = False
        self.connected = False
        self.policy = Policy()  # UX overlay (e.g. classroom mode); feeds the capability resolver
        if connect:
            self.attach_real() if real else self.attach_demo(model_name,
                                                              os_version=os_version, commit=commit)

    # -- device attach / detach ----------------------------------------------------
    def attach_real(self) -> dict:
        """Open a real calculator over USB (pyusb). Raises a plain RuntimeError if none is
        plugged in, so a long-running server stays up and reports it instead of exiting."""
        from ..dfu import usbio
        try:
            od = usbio.open_calculator()
        except usbio.UsbError as exc:
            raise RuntimeError(str(exc)) from exc
        self.device, self.bcd = od.dev, od.bcd_device
        self.client = DfuClient(self.device, interface=od.interface)
        self.virtual = False
        self._on_attached()
        return self.identity()

    def attach_demo(self, model_name: str | None = None, *, os_version: str | None = None,
                    commit: str | None = None) -> dict:
        """Attach an in-memory virtual device — only ever on an explicit user/dev request."""
        from ..testing.virtual_dfu import virtual_calculator
        dm, dov, dcm = self._demo_defaults
        name = model_name or dm
        if os_version is None:  # UI demo picker: pick a version on the device's own family line
            os_version = self._demo_os_for(name, dov)
        self.device = virtual_calculator(name, os_version=os_version, commit=commit or dcm)
        self.bcd = self.device.bcdDevice
        self.client = DfuClient(self.device, sleep=lambda *_: None)
        self.virtual = True
        self._on_attached()
        return self.identity()

    def _on_attached(self) -> None:
        self.model = MODELS.get(self.bcd)
        self.connected = True
        self.installed_apps = []
        self._last_boot_address = None

    def detach(self) -> dict:
        self.device = self.client = self.model = self.bcd = None
        self.connected = self.virtual = False
        return self.identity()

    @staticmethod
    def demo_models() -> list[dict]:
        """Models offered by the 'explore a demo' picker (virtual devices only)."""
        return [{"name": m.name, "family": m.family, "mcu": m.mcu} for m in MODELS.values()]

    @staticmethod
    def _demo_os_for(model_name: str, default: str) -> str:
        """A believable 'installed' OS for a demo device — one line behind the family latest so
        an update shows. Scientific (N0200) is on the 3.x track, Graphing on 2x.x."""
        model = next((m for m in MODELS.values() if m.name == model_name), None)
        return "2.9.0" if (model and model.family == "scientifique") else default

    def _catalog_for(self, family: str, channel: str = "stable") -> FirmwareCatalog:
        base = self.sci_catalog if family == "scientifique" else self.catalog
        if channel != "beta":
            return base
        # Illustrative beta line for the offline/demo fallback: a pre-release one minor ahead of
        # the stable latest (signed-in users get the REAL beta manifest instead). Makes the
        # stable/beta toggle show a difference offline.
        latest = base.latest()
        if latest is None:
            return base
        from ..catalog.firmware import FirmwareRelease
        p = latest.version.split(".")
        beta_v = f"{p[0]}.{(int(p[1]) + 1) if len(p) > 1 and p[1].isdigit() else 0}.0"
        return FirmwareCatalog([FirmwareRelease(beta_v, "beta")] + list(base.releases))

    def _live_latest(self, model: str, channel: str):
        """Real per-model latest from the official manifest (needs sign-in). Returns None when
        live mode is off, anonymous, offline, or on any error — the caller falls back to the
        bundled snapshot. Cached per (model, channel) so a render never re-hits the network."""
        if not self._live_catalog:
            return None
        from ..catalog import auth as A
        from ..catalog import download as D
        a = self._auth_override or A.load_auth()
        if a is None or a.is_expired():
            return None
        key = (model, channel)
        if key not in self._manifest_cache:
            try:
                self._manifest_cache[key] = D.fetch_manifest(model, channel, a,
                                                             transport=self._transport)
            except Exception:  # network/auth/parse error → fall back to the bundled snapshot
                self._manifest_cache[key] = None
        return self._manifest_cache[key]

    def set_channel(self, channel: str) -> dict:
        from ..catalog import download as D
        if channel not in D.CHANNELS:
            raise ValueError(f"unknown channel: {channel!r}")
        self.channel = channel
        return {"channel": self.channel, "channels": list(D.CHANNELS)}

    # -- reads ---------------------------------------------------------------------
    def _identity(self) -> CalculatorIdentity:
        if not self.connected:
            raise ValueError("no calculator connected")
        return read_identity(self.client, self.bcd)

    def _capabilities(self, identity: CalculatorIdentity) -> Capabilities:
        """Effective capabilities for the connected device (structural ∧ observed ∧ policy)."""
        return resolve(self.model, identity, self.policy)

    def identity(self) -> dict:
        if not self.connected:
            return {"connected": False, "virtual": False}
        i = self._identity()
        caps = self._capabilities(i)
        region = i.external_apps_flash if (i.external_apps_flash and i.external_apps_flash != (0, 0)) else None
        return {
            "connected": True,
            "virtual": self.virtual,
            "bcd_device": f"0x{self.bcd:04x}",
            "model": i.model_name,
            "family": i.family,
            "mcu": self.model.mcu if self.model else None,
            "description": describe_bcd(self.bcd),
            "serial_number": i.serial_number,
            "os_version": i.os_version,
            "kernel_version": i.kernel_version,
            "commit": i.commit,
            "has_external_apps": caps.external_apps,
            "external_apps_flash": ([f"0x{region[0]:08x}", f"0x{region[1]:08x}"] if region else None),
            "slot_info_valid": i.slot_info_valid,
            "capabilities": caps.to_dict(),
        }

    def catalog_updates(self) -> dict:
        from ..catalog import download as D
        from ..catalog import version as V
        i = self._identity()
        cur = i.os_version or "0.0.0"
        base = {"current": i.os_version, "channel": self.channel, "channels": list(D.CHANNELS)}
        # Solution 1: prefer the REAL per-model manifest when signed in (source="official").
        man = self._live_latest(self.model.name, self.channel) if self.model else None
        if man is not None:
            newer = V.is_newer(man.version, cur)
            return {**base, "source": "official", "latest": man.version,
                    "up_to_date": not newer, "count": 1,
                    "updates": ([{"version": man.version, "patch_level": man.patch_level,
                                  "latest": True}] if newer else [])}
        # Offline / anonymous fallback: the bundled snapshot for this device's family + channel.
        cat = self._catalog_for(i.family, self.channel)
        latest = cat.latest()
        ups = cat.updates_for(cur)
        return {**base, "source": "sample",
                "latest": latest.version if latest else None,
                "up_to_date": cat.is_up_to_date(cur), "count": len(cat),
                "updates": [{"version": r.version, "patch_level": r.patch_level,
                             "latest": (latest is not None and r.version == latest.version)}
                            for r in ups]}

    def apps(self) -> dict:
        i = self._identity()
        caps = self._capabilities(i)
        compat = self.store.compatible(family=i.family, device_api_level=self.api_level,
                                       has_external_apps=caps.external_apps)
        return {
            "has_external_apps": caps.external_apps,
            "api_level": self.api_level,
            "apps": [{"name": e.name, "version": e.version, "api_level": e.api_level,
                      "description": e.description, "source": e.source, "size": e.size}
                     for e in compat],
            "installed": self.installed_apps,
        }

    # -- auth (my.numworks.com, pour télécharger le vrai firmware) ------------------
    def auth_status(self) -> dict:
        from ..catalog import auth as A
        a = A.load_auth()
        if a is None:
            return {"authenticated": False, "expired": False, "expires_at": None}
        return {
            "authenticated": not a.is_expired(),
            "expired": a.is_expired(),
            "expires_at": (a.expires_at.date().isoformat() if a.expires_at else None),
        }

    def login_token(self, token: str) -> dict:
        """Store a remember_user_token pasted by the user (Mi Unlock style)."""
        from ..catalog import auth as A
        a = A.Auth((token or "").strip())
        if not a.remember_token:
            raise ValueError("empty token")
        A.save_auth(a)
        return self.auth_status()

    def login_password(self, email: str, password: str) -> dict:
        """Built-in Devise login; only the token is kept, never the password."""
        from ..catalog import auth as A
        a = A.login_with_password(email, password)
        A.save_auth(a)
        return self.auth_status()

    def logout(self) -> dict:
        from ..catalog import auth as A
        A.clear_auth()
        return {"authenticated": False, "expired": False, "expires_at": None}

    def _serial(self) -> str | None:
        """Serial number via a standard string-descriptor read (works virtual + real)."""
        from ..dfu import constants as C
        return self.client.get_string_descriptor(C.SERIAL_STRING_INDEX)

    def capture_sequence(self, *, timestamp: str, transport=None, model: str | None = None,
                         channel: str = "stable") -> dict:
        """Bespoke capture: USB + WEB dialogue for the scenario, WITHOUT flashing.

        Requires a signed-in account. The web side always hits the real server (that is what
        we want to capture); ``transport`` is injectable for tests only."""
        import time as _t

        from ..capture_session import run_capture
        from ..catalog import auth as A
        a = A.load_auth()
        if a is None or a.is_expired():
            raise ValueError("authentication required — sign in first")
        tr = transport if transport is not None else A.UrllibTransport()
        return run_capture(
            self.device, auth=a, transport=tr,
            interface=getattr(self.client, "interface", 0), bcd_device=self.bcd,
            model=model or (self.model.name if self.model else "n0200"), channel=channel,
            sleep=(lambda *_: None) if self.virtual else _t.sleep,
            timestamp=timestamp, serial=self._serial())

    # -- firmware cache (classroom mode) -------------------------------------------
    @property
    def cache(self) -> FirmwareCache:
        if self._cache is None:
            self._cache = FirmwareCache(self._cache_dir)
        return self._cache

    def cache_status(self) -> dict:
        import time
        st = self.cache.status()
        expires_in_days = None
        if st.get("expires_at"):
            expires_in_days = max(0, round((st["expires_at"] - time.time()) / 86400))
        return {**st, "expires_in_days": expires_in_days}

    def preload(self, version: str) -> dict:
        if not self.connected:
            raise ValueError("no calculator connected")
        if self.model is None:
            raise ValueError(f"unknown model (bcd 0x{self.bcd:04x})")
        v, blob, real = self._fetch_or_synth(self.model, version)
        self.cache.put(self.model.name, v, blob, real=real)
        return {"ok": True, "real": real, **self.cache_status()}

    def preload_all(self) -> dict:
        """Classroom: cache the latest firmware for EVERY known model (real ``.dfu`` when
        signed in, else a synthetic demo image) so a whole mixed fleet is ready offline."""
        for m in MODELS.values():
            cat = self._catalog_for(m.family, self.channel)
            fallback = cat.latest().version if cat.latest() else "0.0.0"
            v, blob, real = self._fetch_or_synth(m, fallback)
            self.cache.put(m.name, v, blob, real=real)
        return {"ok": True, **self.cache_status()}

    def _fetch_or_synth(self, model, fallback_version: str) -> tuple[str, bytes, bool]:
        """``(version, blob, is_real)`` for a model: the REAL official ``.dfu`` when signed in
        (live mode), else a synthetic demo image. Real downloads are journalled for provenance,
        exactly like a direct install."""
        if self._live_catalog:
            from datetime import datetime, timezone

            from ..catalog import auth as A
            from ..catalog import download as D
            a = self._auth_override or A.load_auth()
            if a is not None and not a.is_expired():
                try:
                    manifest, blob = D.fetch_firmware(model.name, self.channel, a,
                                                      transport=self._transport)
                    D.record_download(manifest, D.sha256_hex(blob),
                                      when=datetime.now(timezone.utc).isoformat())
                    return manifest.version, blob, True
                except Exception:  # offline / auth / integrity error → synthetic fallback
                    pass
        return fallback_version, FirmwareImage.synthetic(model, version=fallback_version).to_dfuse(), False

    def cache_clear(self) -> dict:
        self.cache.clear()
        return {"ok": True, **self.cache_status()}

    # -- writes (against the virtual device) ---------------------------------------
    def install_firmware(self, to_version: str, *, from_cache: bool = False,
                         download: bool = False, channel: str = "stable") -> dict:
        if not self.connected:
            raise ValueError("no calculator connected")
        if self.model is None:
            raise ValueError(f"unknown model (bcd 0x{self.bcd:04x})")
        used_cache = used_download = False
        sha256 = None
        if download:
            # Vrai firmware officiel via my.numworks.com (nécessite un jeton).
            from datetime import datetime, timezone

            from ..catalog import auth as A
            from ..catalog import download as D
            a = A.load_auth()
            if a is None or a.is_expired():
                raise ValueError("authentication required — sign in first (login)")
            manifest, blob = D.fetch_firmware(self.model.name, channel, a)
            image = FirmwareImage.from_dfuse(blob)
            to_version = manifest.version
            # Provenance : empreinte du binaire officiel + journal local (preuve d'intégrité).
            sha256 = D.sha256_hex(blob)
            D.record_download(manifest, sha256, when=datetime.now(timezone.utc).isoformat())
            used_download = True
        else:
            blob = self.cache.get(self.model.name, to_version) if from_cache else None
            if blob is not None:
                image = FirmwareImage.from_dfuse(blob)
                used_cache = True
            else:
                image = FirmwareImage.synthetic(self.model, version=to_version)
        inst = Installer(self.client, self.model)
        plan = inst.install(image, active_slot="A", verify=True, boot=False)
        self._last_boot_address = plan.boot_address  # enables "boot now" (DFU detach+jump)
        return {
            "ok": True,
            "to_version": to_version,
            "from_cache": used_cache,
            "downloaded": used_download,
            "full_image": plan.full_image,
            "target_slot": plan.target_slot,
            "boot_address": (f"0x{plan.boot_address:08x}" if plan.boot_address else None),
            "verified_version": inst.read_installed_version(plan),
            "bytes": plan.total_bytes,
            "sha256": sha256,
        }

    def boot(self) -> dict:
        """Send DFU detach + jump so the calculator reboots on the freshly-flashed slot.

        On real hardware the USB handle drops as the device resets (expected). Requires a
        prior install in this session."""
        addr = self._last_boot_address
        if not addr:
            raise ValueError("no freshly installed firmware to boot")
        self.client.leave(addr)
        return {"ok": True, "jumped_to": f"0x{addr:08x}"}

    def install_app(self, name: str) -> dict:
        entry = self.store.get(name)
        if entry is None:
            raise ValueError(f"unknown app: {name}")
        i = self._identity()
        blob = build_nwa(entry.name, api_level=entry.api_level, code=b"\x00" * 1024)
        inst = AppInstaller(self.client, external_apps_flash=i.external_apps_flash or (0, 0),
                            device_api_level=self.api_level)
        res = inst.install(blob)
        rec = {"name": res.name, "address": f"0x{res.address:08x}", "size": res.size}
        self.installed_apps.append(rec)
        return {"ok": True, **rec}

    def install_local_app(self, filename: str, data: bytes) -> dict:
        """Install a user-supplied .nwa blob (the official upload method)."""
        info = AppInfo.parse(data)
        name = info.name or (filename or "app").rsplit(".", 1)[0]
        i = self._identity()
        inst = AppInstaller(self.client, external_apps_flash=i.external_apps_flash or (0, 0),
                            device_api_level=self.api_level)
        res = inst.install(data)
        rec = {"name": name, "address": f"0x{res.address:08x}", "size": res.size}
        self.installed_apps.append(rec)
        return {"ok": True, **rec}

    # -- device-truth app management (reads the region, minimal-rewrite; see apps/manage.py) --
    def _appmgr(self):
        from ..apps.manage import AppManager
        i = self._identity()
        return AppManager(self.client, i.external_apps_flash, device_api_level=self.api_level)

    def installed_apps_on_device(self) -> dict:
        from ..formats.appicon import decode_app_icon
        apps = self._appmgr().installed()
        return {"installed": [{"name": m.name, "api_level": m.api_level, "size": len(m.blob),
                               "icon": decode_app_icon(m.blob)} for m in apps]}

    def push_app(self, filename: str, data: bytes) -> dict:
        m = self._appmgr().push(data)
        return {"ok": True, "name": m.name, "size": len(m.blob)}

    def inspect_app(self, data: bytes) -> dict:
        """Read-only metadata for a user-supplied .nwa (ELF or flat) — the decoded icon, so a
        dropped file shows it in the plan immediately. Nothing is written or uploaded."""
        from ..formats.appicon import decode_app_icon
        return {"icon": decode_app_icon(data), "size": len(data)}

    def fetch_app(self, url: str) -> dict:
        """Download a catalogue app's .nwa server-side (the browser can't, CORS) for temporary
        in-memory staging. SSRF-guarded: only **https** URLs already listed in the catalogue are
        allowed, and the payload is size-capped. Nothing is written to disk."""
        import base64

        from ..catalog import auth as A
        from ..formats.appicon import decode_app_icon
        allowed = {e.url for e in self.store.entries if e.url}
        if url not in allowed or not url.startswith("https://"):
            raise ValueError("URL not allowed (not in catalog or not https)")
        # Reuse the catalogue transport: proper TLS (certifi) + follows the GitHub→CDN redirect.
        tr = self._transport or A.UrllibTransport()
        try:
            resp = tr.open("GET", url, headers={"User-Agent": "nwupdater"},
                           allow_redirects=True, timeout=30)
        except A.TransportError as exc:
            raise ValueError(str(exc)) from exc
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status} sur {url}")
        if len(resp.body) > 9 * 1024 * 1024:
            raise ValueError("file too large")
        return {"ok": True, "size": len(resp.body), "icon": decode_app_icon(resp.body),
                "data_b64": base64.b64encode(resp.body).decode("ascii")}

    def open_app_stream(self, url: str):
        """Open a catalogue app's URL for STREAMING to the browser (so it can show a real,
        byte-accurate progress bar). Returns ``(content_length_or_None, response)`` — the caller
        streams and closes. Same SSRF guard as :meth:`fetch_app` (catalogue allowlist, https)."""
        import urllib.request

        from ..catalog.auth import _ssl_context
        allowed = {e.url for e in self.store.entries if e.url}
        if url not in allowed or not url.startswith("https://"):
            raise ValueError("URL not allowed (not in catalog or not https)")
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))
        req = urllib.request.Request(url, headers={"User-Agent": "nwupdater"})
        resp = opener.open(req, timeout=30)  # noqa: S310 - https + catalogue allowlist
        cl = resp.headers.get("Content-Length")
        return (int(cl) if cl and cl.isdigit() else None), resp

    def add_store_app(self, name: str) -> dict:
        """Append a catalogue app to the region via minimal-rewrite (does NOT overwrite the
        others, unlike the legacy single-slot install_app)."""
        entry = self.store.get(name)
        if entry is None:
            raise ValueError(f"unknown app: {name}")
        # Synthesize at the catalogue's declared size so demo region usage is realistic (a real
        # .nwa carries its own app_size; here we pad the body to match — header is 0x20 bytes,
        # plus the NUL-terminated name and the real, decodable demo icon).
        from ..formats.appicon import demo_icon_lz4
        icon = demo_icon_lz4(entry.name)
        body = max(256, (entry.size or 65536) - 0x20 - len(entry.name) - 1 - len(icon))
        blob = build_nwa(entry.name, api_level=entry.api_level, code=b"\x00" * body, icon=icon)
        m = self._appmgr().push(blob)
        return {"ok": True, "name": m.name, "size": len(m.blob)}

    def uninstall_app(self, name: str) -> dict:
        self._appmgr().uninstall(name)
        return {"ok": True}

    def reorder_apps(self, order: list[str]) -> dict:
        self._appmgr().reorder(order)
        return {"ok": True}

    # -- Python scripts (SRAM storage) --
    def scripts(self) -> dict:
        from ..formats.storage import python_scripts
        from ..scripts import read_storage
        i = self._identity()
        if not self._capabilities(i).scripts:
            return {"has_scripts": False, "capacity": 0, "scripts": []}
        addr, size = i.storage_ram
        pys = python_scripts(read_storage(self.client, addr, size))
        return {"has_scripts": True, "capacity": size,
                "scripts": [{"name": r.fullname, "size": len(r.code),
                             "auto_import": r.auto_import, "code": r.code} for r in pys],
                "available": self._scripts_available()}

    @staticmethod
    def _scripts_available() -> list[dict]:
        """Illustrative catalogue of *available* Python scripts (cloud / local / remote).

        Sample metadata only — the real flow lists the user's own local files and the public
        scripts on my.numworks.com/python. Mirrors the illustrative app catalogue."""
        return [
            {"name": "devoir.py", "size": 640, "source": "local"},
            {"name": "hex.py", "size": 10240, "source": "my.numworks.com/python/…/hex.py"},
            {"name": "stats_bac.py", "size": 1433, "source": "NumWorks cloud"},
            {"name": "tri_fusion.py", "size": 820, "source": "NumWorks cloud"},
        ]

    def _write_scripts(self, keep_pred) -> dict:
        from ..scripts import read_storage, write_storage
        i = self._identity()
        if not i.storage_ram:
            raise ValueError("this model has no Python scripts (no storage)")
        addr, size = i.storage_ram
        recs, extra = read_storage(self.client, addr, size), []
        kept = keep_pred(recs, extra)
        n = write_storage(self.client, addr, kept + extra, capacity=size)
        return {"ok": True, "written": n, "capacity": size}

    def push_script(self, name: str, code: str, auto_import: bool = True) -> dict:
        from ..formats.storage import make_python
        full = name if name.endswith(".py") else name + ".py"
        return self._write_scripts(
            lambda recs, extra: extra.append(make_python(name, code, auto_import))
            or [r for r in recs if r.fullname != full])

    def delete_script(self, name: str) -> dict:
        full = name if name.endswith(".py") else name + ".py"
        return self._write_scripts(lambda recs, extra: [r for r in recs if r.fullname != full])

    def set_scripts(self, items: list[dict]) -> dict:
        """Rewrite the Python storage to exactly ``items`` (name, code, auto_import) in the given
        order — the workshop's atomic commit for scripts (add + erase + reorder in one write)."""
        from ..formats.storage import make_python
        from ..scripts import write_storage
        i = self._identity()
        if not i.storage_ram:
            raise ValueError("this model has no Python scripts (no storage)")
        addr, size = i.storage_ram
        recs = [make_python(str(it.get("name", "")).removesuffix(".py"), it.get("code", ""),
                            bool(it.get("auto_import", True))) for it in items]
        n = write_storage(self.client, addr, recs, capacity=size)
        return {"ok": True, "written": n, "capacity": size}

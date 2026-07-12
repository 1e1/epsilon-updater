"""Session layer: holds a connected calculator (virtual by default) and exposes the Lot
2/3/4 operations as plain dicts for the local HTTP API.

Virtual by default so the whole UI runs with zero hardware. ``real=True`` would use pyusb.
"""

from __future__ import annotations

from ..apps.installer import AppInstaller
from ..apps.store import AppStore
from ..cache.store import FirmwareCache
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
                 cache_dir=None):
        self.api_level = api_level
        self.installed_apps: list[dict] = []
        self._cache_dir = cache_dir
        self._cache = None
        self._last_boot_address = None  # set after a flash: address to jump to on "boot now"
        if real:
            from .. import cli
            self.device, self.bcd, _iface = cli._open_real_device()
            self.client = DfuClient(self.device, interface=_iface)
            self.virtual = False
        else:
            from ..testing.virtual_dfu import virtual_calculator
            self.device = virtual_calculator(model_name, os_version=os_version, commit=commit)
            self.bcd = self.device.bcdDevice
            self.client = DfuClient(self.device, sleep=lambda *_: None)
            self.virtual = True
        self.model = MODELS.get(self.bcd)
        self.catalog = FirmwareCatalog.bundled()
        self.store = AppStore.bundled()

    # -- reads ---------------------------------------------------------------------
    def _identity(self) -> CalculatorIdentity:
        return read_identity(self.client, self.bcd)

    def identity(self) -> dict:
        i = self._identity()
        region = i.external_apps_flash if (i.external_apps_flash and i.external_apps_flash != (0, 0)) else None
        return {
            "virtual": self.virtual,
            "bcd_device": f"0x{self.bcd:04x}",
            "model": i.model_name,
            "family": i.family,
            "mcu": self.model.mcu if self.model else None,
            "description": describe_bcd(self.bcd),
            "os_version": i.os_version,
            "kernel_version": i.kernel_version,
            "commit": i.commit,
            "has_external_apps": region is not None,
            "external_apps_flash": ([f"0x{region[0]:08x}", f"0x{region[1]:08x}"] if region else None),
            "slot_info_valid": i.slot_info_valid,
        }

    def catalog_updates(self) -> dict:
        i = self._identity()
        cur = i.os_version or "0.0.0"
        latest = self.catalog.latest()
        ups = self.catalog.updates_for(cur)
        return {
            "current": i.os_version,
            "latest": latest.version if latest else None,
            "up_to_date": self.catalog.is_up_to_date(cur),
            "count": len(self.catalog),
            "updates": [{"version": r.version, "patch_level": r.patch_level,
                         "latest": (latest is not None and r.version == latest.version)}
                        for r in ups],
        }

    def apps(self) -> dict:
        i = self._identity()
        has_region = bool(i.external_apps_flash and i.external_apps_flash != (0, 0))
        compat = self.store.compatible(family=i.family, device_api_level=self.api_level,
                                       has_external_apps=has_region)
        return {
            "has_external_apps": has_region,
            "api_level": self.api_level,
            "apps": [{"name": e.name, "version": e.version, "api_level": e.api_level,
                      "description": e.description, "source": e.source} for e in compat],
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
        """Enregistre un remember_user_token collé par l'utilisateur (façon Mi Unlock)."""
        from ..catalog import auth as A
        a = A.Auth((token or "").strip())
        if not a.remember_token:
            raise ValueError("jeton vide")
        A.save_auth(a)
        return self.auth_status()

    def login_password(self, email: str, password: str) -> dict:
        """Login Devise intégré ; on ne conserve que le jeton, jamais le mot de passe."""
        from ..catalog import auth as A
        a = A.login_with_password(email, password)
        A.save_auth(a)
        return self.auth_status()

    def logout(self) -> dict:
        from ..catalog import auth as A
        A.clear_auth()
        return {"authenticated": False, "expired": False, "expires_at": None}

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
        if self.model is None:
            raise ValueError(f"unknown model (bcd 0x{self.bcd:04x})")
        blob = FirmwareImage.synthetic(self.model, version=version).to_dfuse()
        self.cache.put(self.model.name, version, blob)
        return {"ok": True, **self.cache_status()}

    def cache_clear(self) -> dict:
        self.cache.clear()
        return {"ok": True, **self.cache_status()}

    # -- writes (against the virtual device) ---------------------------------------
    def install_firmware(self, to_version: str, *, from_cache: bool = False,
                         download: bool = False, channel: str = "stable") -> dict:
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
                raise ValueError("authentification requise — connectez-vous d'abord (login)")
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
            raise ValueError("aucun firmware fraîchement installé à démarrer")
        self.client.leave(addr)
        return {"ok": True, "jumped_to": f"0x{addr:08x}"}

    def install_app(self, name: str) -> dict:
        entry = self.store.get(name)
        if entry is None:
            raise ValueError(f"app inconnue: {name}")
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

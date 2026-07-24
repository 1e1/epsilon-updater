"""Session state + device lifecycle — the shared base every concern mixin builds on.

``Session`` (in :mod:`nwupdater.server.session`) combines this base with the per-concern mixins
(catalog / apps / auth / firmware / scripts). Splitting the former God-object this way keeps the
public method surface identical while grouping the code by responsibility.
"""

from __future__ import annotations

import threading

from ..apps.store import AppStore
from ..cache.store import FirmwareCache
from ..capabilities import Capabilities, Policy, resolve
from ..catalog.firmware import FirmwareCatalog
from ..dfu.identity import CalculatorIdentity, read_identity
from ..dfu.protocol import DfuClient
from ..models import MODELS, Model, describe_bcd


class SessionBase:
    def __init__(
        self,
        model_name: str = "n0110",
        os_version: str = "23.2.4",
        commit: str = "abc1234",
        *,
        api_level: int = 0,
        real: bool = False,
        cache_dir=None,
        connect: bool = True,
        live_catalog: bool = False,
    ):
        self.api_level = api_level
        self._cache_dir = cache_dir
        self._cache: FirmwareCache | None = None
        self._last_boot_address: int | None = None  # set after a flash: jump address for "boot now"
        self.channel = "stable"
        self.catalog = FirmwareCatalog.bundled()  # Graphing N01xx (2x.x)
        self.sci_catalog = FirmwareCatalog.bundled("firmwares-n0200")  # Scientific N0200 (3.x)
        self.store = AppStore.bundled()
        # Generic, self-hosted user sources: local .nwa files + a _urls.txt list under the user
        # apps dir, merged into the catalogue so "Available" shows real apps the user provides.
        try:
            from ..apps.sources import app_entries, user_apps_dir

            self.store.entries.extend(app_entries(user_apps_dir()))
        except OSError:
            pass
        # Live per-model catalogue: when signed in, the official manifest gives the *real*
        # latest for {model}/{channel}. OFF by default so tests never touch the network — the
        # `ui` server turns it on. Bundled snapshots stay the offline/anonymous fallback.
        self._live_catalog = live_catalog
        self._manifest_cache: dict = {}
        self._auth_override = None  # tests inject an Auth here; production reads the stored token
        self._transport = None  # tests inject a fake transport here
        # Device state. The shipped app starts DISCONNECTED and either attaches a real
        # calculator (hardware plugged in) or an explicit demo device — it never fakes a
        # detection silently. Tests keep the old ergonomics via connect=True (default).
        self._demo_defaults = (model_name, os_version, commit)
        self.device: object | None = None
        self.client: DfuClient | None = None
        self.model: Model | None = None
        self.bcd: int | None = None
        self.virtual = False
        self.connected = False
        # Serializes all device I/O so the background liveness poll (device_health) can never
        # race an in-flight operation (install/read) on the same USB handle.
        self._io_lock = threading.Lock()
        self.policy = Policy()  # UX overlay (e.g. classroom mode); feeds the capability resolver
        if connect:
            self.attach_real() if real else self.attach_demo(
                model_name, os_version=os_version, commit=commit
            )

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

    def attach_demo(
        self,
        model_name: str | None = None,
        *,
        os_version: str | None = None,
        commit: str | None = None,
    ) -> dict:
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
        assert self.bcd is not None
        self.model = MODELS.get(self.bcd)
        self.connected = True
        self._last_boot_address = None

    def detach(self) -> dict:
        self.device = self.client = self.model = self.bcd = None
        self.connected = self.virtual = False
        return self.identity()

    def device_alive(self) -> bool:
        """Cheap liveness check for the connected device. A virtual device is always alive; a
        real one is pinged with a benign DFU GETSTATE (read-only, valid in any state). Any USB
        error means the cable was pulled → ``False``. Callers hold ``_io_lock``."""
        if not self.connected:
            return False
        if self.virtual:
            return True
        try:
            self._conn()[0].get_state()
            return True
        except Exception:
            return False

    def device_health(self) -> dict:
        """Poll device liveness for the UI's hotplug watch, without ever racing an operation.

        If ``_io_lock`` is held (an install/read is running) the device is by definition present,
        so report it connected and skip the probe. Otherwise probe: a real device that has gone
        away is auto-detached so the UI can drop back to scanning for a re-plug."""
        if not self.connected:
            return {"connected": False, "virtual": False}
        if not self._io_lock.acquire(blocking=False):
            return {"connected": True, "virtual": self.virtual, "busy": True}
        try:
            alive = self.device_alive()
        finally:
            self._io_lock.release()
        if not alive:
            self.detach()
            return {"connected": False, "virtual": False, "lost": True}
        return {"connected": True, "virtual": self.virtual}

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
                self._manifest_cache[key] = D.fetch_manifest(
                    model, channel, a, transport=self._transport
                )
            except Exception:  # network/auth/parse error → fall back to the bundled snapshot
                self._manifest_cache[key] = None
        return self._manifest_cache[key]

    def _conn(self) -> tuple[DfuClient, int]:
        """The connected device's ``(client, bcd)``, narrowed. Callers guard on ``connected``."""
        assert self.client is not None and self.bcd is not None
        return self.client, self.bcd

    def _identity(self) -> CalculatorIdentity:
        if not self.connected:
            raise ValueError("no calculator connected")
        return read_identity(*self._conn())

    def _capabilities(self, identity: CalculatorIdentity) -> Capabilities:
        """Effective capabilities for the connected device (structural ∧ observed ∧ policy)."""
        return resolve(self.model, identity, self.policy)

    def identity(self) -> dict:
        if not self.connected:
            return {"connected": False, "virtual": False}
        i = self._identity()
        bcd = self._conn()[1]
        caps = self._capabilities(i)
        region = (
            i.external_apps_flash
            if (i.external_apps_flash and i.external_apps_flash != (0, 0))
            else None
        )
        return {
            "connected": True,
            "virtual": self.virtual,
            "bcd_device": f"0x{bcd:04x}",
            "model": i.model_name,
            "family": i.family,
            "mcu": self.model.mcu if self.model else None,
            "description": describe_bcd(bcd),
            "serial_number": i.serial_number,
            "os_version": i.os_version,
            "kernel_version": i.kernel_version,
            "commit": i.commit,
            "has_external_apps": caps.external_apps,
            "external_apps_flash": (
                [f"0x{region[0]:08x}", f"0x{region[1]:08x}"] if region else None
            ),
            "slot_info_valid": i.slot_info_valid,
            "capabilities": caps.to_dict(),
        }

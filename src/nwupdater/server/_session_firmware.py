"""Firmware install + the classroom-mode firmware cache for a session."""

from __future__ import annotations

from ..cache.store import FirmwareCache
from ..dfu import constants as C
from ..install.image import FirmwareImage
from ..install.installer import Installer
from ..models import MODELS
from ._session_base import SessionBase


class FirmwareMixin(SessionBase):
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
        self.cache.put(self.model.name, v, blob, real=real, channel=self.channel)
        return {"ok": True, "real": real, **self.cache_status()}

    def preload_all(self) -> dict:
        """Classroom: keep the latest firmware cached for EVERY known model (real ``.dfu`` when
        signed in, else a synthetic demo image) so a whole mixed fleet is ready offline.

        When a model already holds the latest for the current channel, its 30-day TTL is simply
        EXTENDED from now — no re-download. Only a genuinely newer (or missing) version is fetched."""
        refreshed = downloaded = 0
        for m in MODELS.values():
            # The version _fetch_or_synth will cache: the official manifest's when signed in.
            # Comparing against the family snapshot instead re-downloaded it on every run.
            target = self._latest_version(m, self.channel)
            cur = self.cache.entry_for_model(m.name)
            if (
                cur is not None
                and target is not None
                and cur.version == target
                and cur.channel == self.channel
                and self.cache.touch(m.name, target)
            ):
                refreshed += 1  # already the latest → extend the TTL, no download
                continue
            v, blob, real = self._fetch_or_synth(m, target or "0.0.0")
            self.cache.put(m.name, v, blob, real=real, channel=self.channel)
            downloaded += 1
        return {"ok": True, "refreshed": refreshed, "downloaded": downloaded, **self.cache_status()}

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
                    manifest, blob = D.fetch_firmware(
                        model.name, self.channel, a, transport=self._transport
                    )
                    D.record_download(
                        manifest, D.sha256_hex(blob), when=datetime.now(timezone.utc).isoformat()
                    )
                    return manifest.version, blob, True
                except Exception:  # offline / auth / integrity error → synthetic fallback
                    pass
        return (
            fallback_version,
            FirmwareImage.synthetic(model, version=fallback_version).to_dfuse(),
            False,
        )

    def cache_clear(self) -> dict:
        self.cache.clear()
        return {"ok": True, **self.cache_status()}

    def _active_slot(self) -> str:
        """Which A/B slot the device is currently running, from SlotInfo's userland pointer.
        ``"A"`` for single-slot models. The installer flashes the *other* (inactive) slot, the
        only one writable on a live device — so on an A/B model an unreadable SlotInfo is an
        error, never a guess: guessing "A" while B runs targets the running slot (errTARGET,
        DFU session left in dfuERROR)."""
        mem = self.model.memory if self.model else None
        if not mem or not mem.has_ab_slots or mem.external_flash_origin is None:
            return "A"
        from ..dfu import constants as C
        from ..formats.headers import SlotInfo

        try:
            si = SlotInfo.unpack(self._conn()[0].read(mem.sram_origin, C.SLOT_INFO_SIZE))
        except Exception:
            si = SlotInfo(0, 0, valid=False)
        if not si.valid:
            raise ValueError(
                "cannot tell which slot the calculator is running; nothing was written "
                "(unplug and replug it, then retry)"
            )
        slot_b = mem.external_flash_origin + mem.slot_size
        return "B" if slot_b <= si.userland_header_addr < slot_b + mem.slot_size else "A"

    # -- writes (against the virtual device) ---------------------------------------
    def install_firmware(
        self,
        to_version: str,
        *,
        from_cache: bool = False,
        download: bool = False,
        channel: str = "stable",
        progress=None,
        reboot: bool = True,
    ) -> dict:
        """Flash the inactive slot, verify it, then reboot the calculator onto it.

        ``progress`` is the optional callback ``(phase, done, total)``, phase ``"download"``
        (the official .dfu arriving), then the ``Installer``'s ``"erase"``, ``"write"`` and
        ``"verify"`` — the native UI binds it to a determinate progress bar; the HTTP layer
        leaves it unset (no streaming channel to report on).

        ``reboot`` ends the flash the way the official WebUSB flow does: a cold boot through the
        bootloader (see :meth:`boot`), so nobody has to press RESET. A caller that still has work
        to do on the same connection (the classroom batch) passes ``False`` and boots last.
        """
        if not self.connected:
            raise ValueError("no calculator connected")
        if self.model is None:
            raise ValueError(f"unknown model (bcd 0x{self.bcd:04x})")
        used_cache = used_download = False
        official = False  # the image is the official signed .dfu (downloaded, or cached as such)
        sha256 = None
        if download:
            # Vrai firmware officiel via my.numworks.com (nécessite un jeton).
            from datetime import datetime, timezone

            from ..catalog import auth as A
            from ..catalog import download as D

            a = A.load_auth()
            if a is None or a.is_expired():
                raise ValueError("authentication required — sign in first (login)")
            fetched = None
            if progress is not None:

                def fetched(done: int, total: int) -> None:
                    progress("download", done, total)

            manifest, blob = D.fetch_firmware(self.model.name, channel, a, progress=fetched)
            image = FirmwareImage.from_dfuse(blob)
            to_version = manifest.version
            # Provenance : empreinte du binaire officiel + journal local (preuve d'intégrité).
            sha256 = D.sha256_hex(blob)
            D.record_download(manifest, sha256, when=datetime.now(timezone.utc).isoformat())
            used_download = official = True
        else:
            cached = None
            if from_cache:
                # Classroom / offline: no account, no re-download. An explicit version is looked
                # up as-is; when omitted we flash whatever is cached for THIS model (one-click).
                if not to_version:
                    entry = self.cache.entry_for_model(self.model.name)
                    if entry is not None:
                        to_version = entry.version
                cached = self.cache.get(self.model.name, to_version) if to_version else None
            if cached is not None:
                image = FirmwareImage.from_dfuse(cached)
                used_cache = True
                entry = self.cache.entry_for_model(self.model.name)
                official = bool(entry and entry.version == to_version and entry.real)
            else:
                image = FirmwareImage.synthetic(self.model, version=to_version or "0.0.0")
        if not self.virtual and not official:
            # A synthetic image (or a cache filled while signed out, which holds one) is for the
            # demo device only. Never write it to a real calculator.
            raise ValueError(
                "only the official firmware can be flashed onto a real calculator: sign in to "
                "download it (a cache filled while signed out holds a demo image)"
            )
        serial = self._identity().serial_number
        inst = Installer(
            self._conn()[0],
            self.model,
            progress=progress,
            reconnect=lambda: self._reopen_after_reset(serial),
        )
        # Detect the running slot so the installer flashes the INACTIVE one (the active slot is
        # hardware-protected; writing it errTARGETs and wedges the DFU session on real hardware).
        plan = inst.install(image, active_slot=self._active_slot(), verify=True, boot=False)
        self._flashed = True  # enables "boot now"
        verified_version = inst.read_installed_version(plan)  # before the reboot drops the link
        rebooted = False
        if reboot:
            self.boot()
            rebooted = True
        return {
            "ok": True,
            "rebooted": rebooted,
            "to_version": to_version,
            "from_cache": used_cache,
            "downloaded": used_download,
            "full_image": plan.full_image,
            "target_slot": plan.target_slot,
            "boot_address": (f"0x{plan.boot_address:08x}" if plan.boot_address else None),
            "verified_version": verified_version,
            "bytes": plan.total_bytes,
            "sha256": sha256,
        }

    def _reopen_after_reset(self, serial: str | None):
        """Re-open the calculator after the installer rebooted it into its updater and hand the
        installer the new client. A virtual device switches mode in place."""
        from ..dfu.protocol import DfuClient

        if self.virtual:
            self.client = DfuClient(self._conn()[0].dev, sleep=lambda *_: None)
        else:
            from ..dfu import usbio

            self._release_usb()
            od = usbio.reopen_after_reset(serial)
            self.device, self.bcd = od.dev, od.bcd_device
            self.client = DfuClient(self.device, interface=od.interface)
        self.client.make_idle()
        return self.client

    def boot(self) -> dict:
        """Reboot through the bootloader so the calculator runs the freshly-flashed firmware.

        Sends a DFU leave to the internal-flash base (0x08000000 = the bootloader), NOT the
        flashed slot. A leave *into* a QSPI slot boots it unauthenticated → "UNOFFICIAL SOFTWARE";
        leaving to the bootloader triggers a cold boot that re-verifies the slot signature and
        keeps the device **official**, with no manual RESET — this mirrors the official WebUSB
        flow (see docs/reference/official-webusb-analysis.md), on every model. Requires a prior
        install in this session.

        A real calculator leaves the bus as it resets, so the session detaches: the UI's hotplug
        watch re-attaches it once it is back. A virtual device stays attached (demo continuity)."""
        if not self._flashed:
            raise ValueError("no freshly installed firmware to boot")
        self._conn()[0].leave(C.BOOTLOADER_RESET_ADDRESS)
        if not self.virtual:
            self.detach()
        return {"ok": True, "jumped_to": f"0x{C.BOOTLOADER_RESET_ADDRESS:08x}"}

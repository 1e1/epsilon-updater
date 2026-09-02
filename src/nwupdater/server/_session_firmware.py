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
            cat = self._catalog_for(m.family, self.channel)
            latest = cat.latest()
            target = latest.version if latest else None
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
        ``"A"`` for single-slot models or when it can't be read — the installer then flashes the
        *other* (inactive) slot, which is the only one writable on a live device."""
        mem = self.model.memory if self.model else None
        if not mem or not mem.has_ab_slots or mem.external_flash_origin is None:
            return "A"
        from ..dfu import constants as C
        from ..formats.headers import SlotInfo

        try:
            si = SlotInfo.unpack(self._conn()[0].read(mem.sram_origin, C.SLOT_INFO_SIZE))
        except Exception:
            return "A"
        slot_b = mem.external_flash_origin + mem.slot_size
        return (
            "B" if si.valid and slot_b <= si.userland_header_addr < slot_b + mem.slot_size else "A"
        )

    # -- writes (against the virtual device) ---------------------------------------
    def install_firmware(
        self,
        to_version: str,
        *,
        from_cache: bool = False,
        download: bool = False,
        channel: str = "stable",
        progress=None,
    ) -> dict:
        """Flash the inactive slot and verify it.

        ``progress`` is the optional ``Installer`` callback ``(phase, done, total)`` with
        phase ``"write"`` or ``"verify"`` — the native UI binds it to a determinate progress
        bar; the HTTP layer leaves it unset (no streaming channel to report on).
        """
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
            else:
                image = FirmwareImage.synthetic(self.model, version=to_version or "0.0.0")
        inst = Installer(self._conn()[0], self.model, progress=progress)
        # Detect the running slot so the installer flashes the INACTIVE one (the active slot is
        # hardware-protected; writing it errTARGETs and wedges the DFU session on real hardware).
        plan = inst.install(image, active_slot=self._active_slot(), verify=True, boot=False)
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
        """Reboot through the bootloader so the calculator runs the freshly-flashed firmware.

        Sends a DFU leave to the internal-flash base (0x08000000 = the bootloader), NOT the
        flashed slot. A leave *into* a QSPI slot boots it unauthenticated → "UNOFFICIAL SOFTWARE";
        leaving to the bootloader triggers a cold boot that re-verifies the slot signature and
        keeps the device **official**, with no manual RESET — this mirrors the official WebUSB
        flow (see docs/reference/official-webusb-analysis.md). The USB handle drops as the device
        resets; callers re-enumerate. Requires a prior install in this session."""
        if not self._last_boot_address:
            raise ValueError("no freshly installed firmware to boot")
        self._conn()[0].leave(C.BOOTLOADER_RESET_ADDRESS)
        return {"ok": True, "jumped_to": f"0x{C.BOOTLOADER_RESET_ADDRESS:08x}"}

"""Firmware install + the classroom-mode firmware cache for a session."""

from __future__ import annotations

from ..cache.store import FirmwareCache
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
        """Classroom: cache the latest firmware for EVERY known model (real ``.dfu`` when
        signed in, else a synthetic demo image) so a whole mixed fleet is ready offline."""
        for m in MODELS.values():
            cat = self._catalog_for(m.family, self.channel)
            latest = cat.latest()
            fallback = latest.version if latest else "0.0.0"
            v, blob, real = self._fetch_or_synth(m, fallback)
            self.cache.put(m.name, v, blob, real=real, channel=self.channel)
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

    # -- writes (against the virtual device) ---------------------------------------
    def install_firmware(
        self,
        to_version: str,
        *,
        from_cache: bool = False,
        download: bool = False,
        channel: str = "stable",
    ) -> dict:
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
        inst = Installer(self._conn()[0], self.model)
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
        self._conn()[0].leave(addr)
        return {"ok": True, "jumped_to": f"0x{addr:08x}"}

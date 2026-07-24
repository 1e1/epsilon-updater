"""Firmware-catalogue views for a session (available updates, channel, demo versions)."""

from __future__ import annotations

from ._session_base import SessionBase


class CatalogMixin(SessionBase):
    def set_channel(self, channel: str) -> dict:
        from ..catalog import download as D

        if channel not in D.CHANNELS:
            raise ValueError(f"unknown channel: {channel!r}")
        self.channel = channel
        return {"channel": self.channel, "channels": list(D.CHANNELS)}

    # -- reads ---------------------------------------------------------------------
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
            return {
                **base,
                "source": "official",
                "latest": man.version,
                "up_to_date": not newer,
                "count": 1,
                "updates": (
                    [{"version": man.version, "patch_level": man.patch_level, "latest": True}]
                    if newer
                    else []
                ),
            }
        # Offline / anonymous fallback: the bundled snapshot for this device's family + channel.
        cat = self._catalog_for(i.family, self.channel)
        latest = cat.latest()
        ups = cat.updates_for(cur)
        return {
            **base,
            "source": "sample",
            "latest": latest.version if latest else None,
            "up_to_date": cat.is_up_to_date(cur),
            "count": len(cat),
            "updates": [
                {
                    "version": r.version,
                    "patch_level": r.patch_level,
                    "latest": (latest is not None and r.version == latest.version),
                }
                for r in ups
            ],
        }

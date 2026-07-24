"""Firmware update catalog.

Source of truth: the PUBLIC endpoint ``GET https://my.numworks.com/firmwares.json`` (no
auth), a flat array of ``{version, patch_level}`` newest-first. It carries NO model field
and NO binary URLs (see docs/02-update-catalog/web-api.md) — model/version compatibility is
resolved client-side against the identity we read over DFU (Lot 1).

The catalog loads offline from a bundled snapshot by default so nothing here needs the
network; ``fetch()`` refreshes it live on demand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import version as V

CATALOG_URL = "https://my.numworks.com/firmwares.json"


@dataclass(frozen=True)
class FirmwareRelease:
    version: str
    patch_level: str  # short git commit hash

    @property
    def parsed(self) -> tuple[int, ...]:
        return V.parse_version(self.version)

    def __str__(self) -> str:
        return f"{self.version} ({self.patch_level})"


class FirmwareCatalog:
    def __init__(self, releases: list[FirmwareRelease]):
        # keep newest-first, deduped by version
        seen: set[str] = set()
        uniq: list[FirmwareRelease] = []
        for r in sorted(releases, key=lambda r: r.parsed, reverse=True):
            if r.version not in seen:
                seen.add(r.version)
                uniq.append(r)
        self.releases = uniq

    # -- constructors --------------------------------------------------------------
    @classmethod
    def from_json(cls, data) -> FirmwareCatalog:
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        return cls([FirmwareRelease(d["version"], d.get("patch_level", "")) for d in data])

    @classmethod
    def load(cls, path: str | Path) -> FirmwareCatalog:
        return cls.from_json(Path(path).read_text())

    @classmethod
    def bundled(cls, name: str = "firmwares") -> FirmwareCatalog:
        """A snapshot shipped with the package (offline default).

        ``name`` selects the track: ``firmwares`` = the public Graphing catalog (N01xx),
        ``firmwares-n0200`` = the Scientific (N0200) 3.x line — they use unrelated version
        numbers, so the session picks the right one per detected family."""
        rel = f"data/{name}.json"
        try:
            raw = resources.files("nwupdater.catalog").joinpath(rel).read_text()
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            raw = (Path(__file__).parent / "data" / f"{name}.json").read_text()
        return cls.from_json(raw)

    @classmethod
    def fetch(cls, url: str = CATALOG_URL, *, timeout: float = 10.0) -> FirmwareCatalog:
        """Live fetch. Only place in Lot 2 that touches the network; never used in tests."""
        import urllib.request

        if not url.startswith(("http://", "https://")):  # never file:/ or custom schemes
            raise ValueError(f"URL de catalogue invalide : {url!r}")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - schéma http(s) validé ci-dessus
            return cls.from_json(resp.read())

    # -- queries -------------------------------------------------------------------
    def latest(self) -> FirmwareRelease | None:
        return self.releases[0] if self.releases else None

    def updates_for(self, current_version: str) -> list[FirmwareRelease]:
        """Releases strictly newer than ``current_version``, newest-first."""
        return [r for r in self.releases if V.is_newer(r.version, current_version)]

    def is_up_to_date(self, current_version: str) -> bool:
        latest = self.latest()
        return latest is None or not V.is_newer(latest.version, current_version)

    def get(self, version: str) -> FirmwareRelease | None:
        return next((r for r in self.releases if r.version == version), None)

    def __len__(self) -> int:
        return len(self.releases)

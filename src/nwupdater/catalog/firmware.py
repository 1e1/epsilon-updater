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

# Family -> its own bundled snapshot, for a family the public list cannot be trusted for. The
# public ``firmwares.json`` has no model field and mixes the families (the Scientific 2.1.0 /
# 3.0.0 / 4.1.0 sit among the Graphing releases), so a family listed here keeps its own track and
# the others read the public list minus every release one of these snapshots claims. Data only:
# a new family with its own numbering adds one line here and one ``data/firmwares-<family>.json``.
FAMILY_SNAPSHOTS = {"scientifique": "firmwares-scientifique"}


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

        ``name`` selects the file: ``firmwares`` = the public list as published (all families
        mixed), ``firmwares-<family>`` = a family's own track (see ``FAMILY_SNAPSHOTS``). Use
        ``for_family`` to get the releases of one family."""
        rel = f"data/{name}.json"
        try:
            raw = resources.files("nwupdater.catalog").joinpath(rel).read_text()
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            raw = (Path(__file__).parent / "data" / f"{name}.json").read_text()
        return cls.from_json(raw)

    @classmethod
    def for_family(cls, family: str, *, public: FirmwareCatalog | None = None) -> FirmwareCatalog:
        """The releases of one family: its own snapshot when ``FAMILY_SNAPSHOTS`` names one,
        else ``public`` (default: the bundled public snapshot) minus every release another
        family's snapshot claims."""
        own = FAMILY_SNAPSHOTS.get(family)
        if own is not None:
            return cls.bundled(own)
        claimed = {
            r.version
            for other, name in FAMILY_SNAPSHOTS.items()
            if other != family
            for r in cls.bundled(name).releases
        }
        base = public if public is not None else cls.bundled()
        return cls([r for r in base.releases if r.version not in claimed])

    @classmethod
    def fetch(
        cls, url: str = CATALOG_URL, *, timeout: float = 10.0, transport=None
    ) -> FirmwareCatalog:
        """Live fetch of the public catalogue (no auth). Tests inject ``transport``."""
        from .auth import UrllibTransport

        if not url.startswith(("http://", "https://")):  # never file:/ or custom schemes
            raise ValueError(f"URL de catalogue invalide : {url!r}")
        tr = transport or UrllibTransport()
        resp = tr.open(
            "GET",
            url,
            headers={"Accept": "application/json"},
            timeout=timeout,
            allow_redirects=True,
        )
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status} sur {url}")
        return cls.from_json(resp.body)

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

"""Firmware cache — pre-download an OS once, flash a whole classroom offline.

Policy (per the classroom use case):
  * **One entry per model (its latest).** Caching a firmware for a model that is already
    present replaces just that model's entry; other models are kept. A fleet can therefore
    hold the latest of *every* hardware at once — including different families/version lines
    (e.g. n0110 @ 25.2.0 **and** n0200 @ 3.0.0).
  * **Auto-expire after 30 days.** Entries older than the TTL are pruned on every access.

Stores raw bytes the caller already downloaded; this module never touches the network.
Time is injectable (``now``) so expiry is testable without waiting.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_TTL_DAYS = 30


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "nwupdater" / "firmware"


@dataclass
class CacheEntry:
    model: str
    version: str
    filename: str
    size: int
    sha256: str
    downloaded_at: float  # epoch seconds
    real: bool = False  # True = official .dfu downloaded; False = synthetic demo image

    def key(self) -> str:
        return f"{self.model}/{self.version}"


class FirmwareCache:
    def __init__(self, root: Path | None = None, *, ttl_days: int = DEFAULT_TTL_DAYS, now=time.time):
        self.root = Path(root) if root else default_cache_dir()
        self.ttl = ttl_days * 86400
        self._now = now
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"

    # -- index io ------------------------------------------------------------------
    def _load(self) -> dict[str, CacheEntry]:
        if not self._index_path.exists():
            return {}
        try:
            raw = json.loads(self._index_path.read_text())
            return {k: CacheEntry(**v) for k, v in raw.items()}
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            # Corrupt or schema-incompatible index → treat as empty; the next write rebuilds it.
            return {}

    def _atomic_write(self, path: Path, data: bytes) -> None:
        """Write ``data`` to ``path`` atomically (temp file in the same dir + ``os.replace``), so
        a crash or a concurrent classroom launch can never leave a half-written file behind."""
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _save(self, entries: dict[str, CacheEntry]) -> None:
        payload = json.dumps({k: asdict(v) for k, v in entries.items()}, indent=2)
        self._atomic_write(self._index_path, payload.encode("utf-8"))

    # -- expiry --------------------------------------------------------------------
    def _prune(self, entries: dict[str, CacheEntry]) -> list[CacheEntry]:
        removed = []
        now = self._now()
        for key in list(entries):
            if now - entries[key].downloaded_at > self.ttl:
                removed.append(entries.pop(key))
        for e in removed:
            self._unlink(e)
        return removed

    def _unlink(self, entry: CacheEntry) -> None:
        try:
            (self.root / entry.filename).unlink()
        except OSError:
            pass

    def prune(self) -> list[CacheEntry]:
        entries = self._load()
        removed = self._prune(entries)
        if removed:
            self._save(entries)
        return removed

    # -- writes --------------------------------------------------------------------
    def put(self, model: str, version: str, data: bytes, *, real: bool = False) -> CacheEntry:
        entries = self._load()
        self._prune(entries)
        # One entry per model: drop any previous version of THIS model, keep the other models.
        for k in [k for k, e in entries.items() if e.model == model]:
            self._unlink(entries.pop(k))
        filename = f"{model}-{version}.bin".replace("/", "_").replace(" ", "_")
        self._atomic_write(self.root / filename, data)
        entry = CacheEntry(model, version, filename, len(data),
                           hashlib.sha256(data).hexdigest(), self._now(), real)
        entries[entry.key()] = entry
        self._save(entries)
        return entry

    def clear(self) -> None:
        entries = self._load()
        for e in entries.values():
            self._unlink(e)
        self._save({})

    # -- reads ---------------------------------------------------------------------
    def get(self, model: str, version: str) -> bytes | None:
        entries = self._load()
        if self._prune(entries):  # only rewrite the index when expiry actually changed it
            self._save(entries)
        e = entries.get(f"{model}/{version}")
        if e is None:
            return None
        path = self.root / e.filename
        return path.read_bytes() if path.exists() else None

    def has(self, model: str, version: str) -> bool:
        entries = self._load()
        if self._prune(entries):
            self._save(entries)
        return f"{model}/{version}" in entries

    def cached_version(self, entries: dict[str, CacheEntry] | None = None) -> str | None:
        """The single common version across the fleet, or None. Empty cache -> None; one shared
        version -> that version; a mixed fleet (models at different versions) -> None."""
        entries = entries if entries is not None else self._load()
        versions = {e.version for e in entries.values()}
        return next(iter(versions)) if len(versions) == 1 else None

    def entries(self) -> list[CacheEntry]:
        entries = self._load()
        if self._prune(entries):
            self._save(entries)
        return list(entries.values())

    def status(self) -> dict:
        entries = self.entries()
        if not entries:
            return {"version": None, "models": [], "total_size": 0, "expires_at": None}
        oldest = min(e.downloaded_at for e in entries)
        return {
            "version": self.cached_version(dict((e.key(), e) for e in entries)),
            "models": sorted(e.model for e in entries),
            "entries": [{"model": e.model, "version": e.version, "size": e.size, "real": e.real}
                        for e in sorted(entries, key=lambda e: e.model)],
            "total_size": sum(e.size for e in entries),
            "expires_at": oldest + self.ttl,
            "ttl_days": self.ttl // 86400,
        }

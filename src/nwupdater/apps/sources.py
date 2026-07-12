"""Aggregate *available* apps/scripts from local files and user-listed remote URLs.

Two generic, self-hosted sources (no bundled third-party catalog):

* **Local files** — a directory scanned for a configured extension (``.nwa`` for apps,
  ``.py`` for scripts).
* **Remote URLs** — one URL per line in a ``_urls.txt`` sitting in that directory. The URLs
  are supplied by the user; nothing is hard-coded. Fetching goes through an injected
  ``fetcher`` (so this is fully offline-testable) and is cached on disk by URL.

Compatibility (API level / model) is still decided client-side by the caller, as the website
does — this module only enumerates candidates and downloads bytes on demand.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class SourceItem:
    name: str                    # display name, e.g. "game.nwa"
    origin: str                  # "local" | "remote"
    path: Path | None = None     # local file (origin == "local")
    url: str | None = None       # remote URL (origin == "remote")
    size: int | None = None      # bytes, when known


def _matches(name: str, exts: list[str]) -> bool:
    return any(name.lower().endswith(e.lower()) for e in exts)


def scan_local(directory: Path, exts: list[str]) -> list[SourceItem]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and _matches(p.name, exts):
            out.append(SourceItem(p.name, "local", path=p, size=p.stat().st_size))
    return out


def read_url_list(urls_file: Path) -> list[str]:
    """One URL per line; blank lines and ``#`` comments ignored."""
    urls_file = Path(urls_file)
    if not urls_file.is_file():
        return []
    urls = []
    for line in urls_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def remote_items(urls: list[str], exts: list[str]) -> list[SourceItem]:
    out = []
    for u in urls:
        name = Path(urlparse(u).path).name or u
        if exts and not _matches(name, exts):
            continue
        out.append(SourceItem(name, "remote", url=u))
    return out


def aggregate(subdir: Path, exts: list[str]) -> list[SourceItem]:
    """Local files + remote URLs (from ``<subdir>/_urls.txt``), de-duplicated by name."""
    subdir = Path(subdir)
    items = scan_local(subdir, exts)
    seen = {i.name for i in items}
    for it in remote_items(read_url_list(subdir / "_urls.txt"), exts):
        if it.name not in seen:
            items.append(it)
            seen.add(it.name)
    return items


class RemoteCache:
    """On-disk cache of fetched remote files, keyed by URL (classroom-friendly: fetch once)."""

    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        return self.dir / (hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
                           + "_" + (Path(urlparse(url).path).name or "blob"))

    def get(self, url: str, fetcher) -> bytes:
        """Return the cached bytes for ``url``, fetching via ``fetcher(url) -> bytes`` once."""
        p = self._path(url)
        if p.exists():
            return p.read_bytes()
        data = fetcher(url)
        p.write_bytes(data)
        return data

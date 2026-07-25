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

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .store import AppEntry


@dataclass
class SourceItem:
    name: str  # display name, e.g. "game.nwa"
    origin: str  # "local" | "remote"
    path: Path | None = None  # local file (origin == "local")
    url: str | None = None  # remote URL (origin == "remote")
    size: int | None = None  # bytes, when known


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


def user_apps_dir() -> Path:
    """Where the user drops their own apps: ``$NWUPDATER_APPS_DIR`` or ``<config>/nwupdater/apps``
    (mirrors the credentials path). Nothing is created here; a missing dir just yields no sources."""
    override = os.environ.get("NWUPDATER_APPS_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "nwupdater" / "apps"


def user_scripts_dir() -> Path:
    """Local library where exported Python scripts land: ``$NWUPDATER_SCRIPTS_DIR`` or
    ``<config>/nwupdater/scripts`` (mirrors :func:`user_apps_dir`). Starts empty; the server
    creates it on launch. A missing dir just yields no local matches."""
    override = os.environ.get("NWUPDATER_SCRIPTS_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "nwupdater" / "scripts"


def app_entries(directory: Path) -> list[AppEntry]:
    """Build catalogue entries from a user directory — the generic, self-hosted source behind the
    UI's "Available" list. Local ``.nwa`` files are parsed for their real name + API level (so
    compatibility is honoured and the real bytes are installed); one URL per line in ``_urls.txt``
    adds a downloadable entry (fetched through the SSRF-guarded proxy, which allowlists it because
    it is now in the store). Nothing is hard-coded."""
    from ..formats.nwa import AppInfo
    from .store import AppEntry

    directory = Path(directory)
    out: list[AppEntry] = []
    for it in scan_local(directory, [".nwa"]):
        assert it.path is not None
        try:
            info = AppInfo.parse(it.path.read_bytes())
        except OSError:
            continue
        out.append(
            AppEntry(
                name=(info.name if info.valid and info.name else it.path.stem),
                version="?",
                api_level=info.api_level if info.valid else 0,
                family="any",
                source="local file",
                url="",
                size=it.size or 0,
                local_path=str(it.path),
            )
        )
    for url in read_url_list(directory / "_urls.txt"):
        p = urlparse(url)
        name = Path(p.path).name or url
        if not name.lower().endswith(".nwa"):
            continue
        out.append(
            AppEntry(
                name=name,
                version="?",
                api_level=0,  # unknown until fetched; the device check runs again at install time
                family="any",
                source=p.hostname or "remote",
                url=url,
                size=0,
            )
        )
    return out

"""Third-party app catalog (Lot 4).

There is NO official public app-catalog API — the official flow is "user uploads a .nwa on
my.numworks.com/apps" (docs/04-third-party-apps/app-store-and-nwa.md). So the store here
models the aggregation of *community* catalogs from a local sources JSON. Compatibility is
resolved client-side, exactly like the website: model family + external-apps space + API
level vs the app's embedded AppInfo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

# Third-party apps are NOT official: community-provided .nwa files, neither hosted nor modified
# by this tool. Surfaced to the user before any install (CLI prompt + web UI banner).
THIRD_PARTY_WARNING = (
    "Unofficial third-party apps: community .nwa files, neither hosted nor modified by this "
    "tool — install at your own risk."
)


@dataclass(frozen=True)
class AppEntry:
    name: str
    version: str
    api_level: int
    family: str  # "graphique" | "scientifique" | "any"
    description: str = ""
    source: str = ""
    url: str = ""
    size: int = 0  # bytes; from the catalogue (a real .nwa carries app_size in its header)

    def compatible_with(self, *, family: str, device_api_level: int,
                        has_external_apps: bool) -> bool:
        if not has_external_apps:
            return False
        if self.family not in (family, "any"):
            return False
        return self.api_level == device_api_level


class AppStore:
    def __init__(self, entries: list[AppEntry]):
        self.entries = entries

    @classmethod
    def from_json(cls, data) -> "AppStore":
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        apps = data["apps"] if isinstance(data, dict) else data
        return cls([AppEntry(
            name=a["name"], version=str(a.get("version", "?")),
            api_level=int(a.get("api_level", 0)), family=a.get("family", "any"),
            description=a.get("description", ""), source=a.get("source", ""),
            url=a.get("url", ""), size=int(a.get("size", 0))) for a in apps])

    @classmethod
    def bundled(cls) -> "AppStore":
        try:
            raw = resources.files("nwupdater.apps").joinpath("data/community-apps.json").read_text()
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            raw = (Path(__file__).parent / "data" / "community-apps.json").read_text()
        return cls.from_json(raw)

    @classmethod
    def load(cls, path: str | Path) -> "AppStore":
        return cls.from_json(Path(path).read_text())

    def compatible(self, *, family: str, device_api_level: int,
                   has_external_apps: bool) -> list[AppEntry]:
        return [e for e in self.entries
                if e.compatible_with(family=family, device_api_level=device_api_level,
                                     has_external_apps=has_external_apps)]

    def get(self, name: str) -> AppEntry | None:
        return next((e for e in self.entries if e.name.lower() == name.lower()), None)

    def __len__(self) -> int:
        return len(self.entries)

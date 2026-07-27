"""Third-party (.nwa) app operations for a session."""

from __future__ import annotations

from .. import ensure_suffix
from ..formats.nwa import build_nwa
from ._session_base import SessionBase


def _nwa_app_name(data: bytes) -> str:
    """The real app name of a ``.nwa``, whether flat (AppInfo) or a relocatable ELF (the
    ``.rodata.eadk_app_name`` string). Empty string if it can't be determined."""
    from ..apps.link import is_relocatable_nwa

    if is_relocatable_nwa(data):
        from ..formats.nwa_link import Elf32

        try:
            sec = Elf32.parse(data).section(".rodata.eadk_app_name")
        except Exception:
            return ""
        return sec.data.split(b"\x00", 1)[0].decode("ascii", "replace") if sec and sec.data else ""
    from ..formats.nwa import AppInfo

    return AppInfo.parse(data).name


class AppsMixin(SessionBase):
    def apps(self) -> dict:
        from ..apps.link import nwlink_available

        i = self._identity()
        caps = self._capabilities(i)
        compat = self.store.compatible(
            family=i.family, device_api_level=self.api_level, has_external_apps=caps.external_apps
        )
        return {
            "has_external_apps": caps.external_apps,
            "api_level": self.api_level,
            # Distributed .nwa are relocatable ELFs relinked at install via nwlink (Node). Surface
            # whether it's discoverable so the UI can warn BEFORE an install fails mid-way.
            "nwlink": nwlink_available(),
            "apps": [
                {
                    "name": e.name,
                    "version": e.version,
                    "api_level": e.api_level,
                    "description": e.description,
                    "source": e.source,
                    "url": e.url,
                    "size": e.size,
                }
                for e in compat
            ],
        }

    # -- install (append via the device-truth minimal rewrite, never overwrite) ----
    def install_app(self, name: str) -> dict:
        """Install a catalogue app (synthesised .nwa), appended to the region. Kept for the
        ``/api/install/app`` route and the CLI; delegates to :meth:`add_store_app`."""
        return self.add_store_app(name)

    def install_local_app(self, filename: str, data: bytes) -> dict:
        """Install a user-supplied .nwa blob, appended to the region (does not overwrite the
        existing apps) — same minimal-rewrite path as :meth:`push_app`."""
        return self.push_app(filename, data)

    # -- device-truth app management (reads the region, minimal-rewrite; see apps/manage.py) --
    def _appmgr(self):
        from ..apps.manage import AppManager

        i = self._identity()
        return AppManager(
            self._conn()[0],
            i.external_apps_flash,
            device_api_level=self.api_level,
            external_apps_ram=i.external_apps_ram,
            userland_header_addr=i.userland_header_addr,
        )

    @staticmethod
    def _local_apps_index() -> dict[str, int]:
        """``{name: size}`` for the ``.nwa`` files in the user apps library — used to flag an
        installed app as already present on the computer (same name AND same byte size). Keyed by
        filename stem, which is exactly what :meth:`export_app` writes (``<name>.nwa``)."""
        from ..apps.sources import scan_local, user_apps_dir

        idx: dict[str, int] = {}
        for it in scan_local(user_apps_dir(), [".nwa"]):
            if it.path is not None and it.size is not None:
                idx[it.path.stem] = it.size
        return idx

    def installed_apps_on_device(self) -> dict:
        from ..apps.manage import SECTOR
        from ..formats.appicon import decode_app_icon

        mgr = self._appmgr()
        apps = mgr.installed()
        local = self._local_apps_index()
        used = sum(m.sectors * SECTOR for m in apps)  # sector-aligned: matches what actually fits
        return {
            "installed": [
                {
                    "name": m.name,
                    "api_level": m.api_level,
                    "size": len(m.blob),
                    "icon": decode_app_icon(m.blob),
                    # True when a same-name, same-size .nwa already sits in the local library.
                    "local": local.get(m.name) == len(m.blob),
                }
                for m in apps
            ],
            # region occupation in the sector-aligned unit the device really uses (see manage.usage)
            "capacity": mgr.capacity,
            "used": used,
            "free": max(0, mgr.capacity - used),
        }

    def export_app(self, name: str) -> dict:
        """Read an installed app's bytes off the device and save them into the local apps library
        (``<apps_dir>/<name>.nwa``, created on demand), returning the blob (base64) so the browser
        downloads it too. After this the app matches the library, so the UI flips to "already on
        the computer"."""
        import base64
        from pathlib import Path

        from ..apps.sources import user_apps_dir

        m = next((a for a in self._appmgr().installed() if a.name == name), None)
        if m is None:
            raise ValueError(f"app not installed: {name}")
        filename = Path(ensure_suffix(name, ".nwa")).name
        dest = user_apps_dir()
        dest.mkdir(parents=True, exist_ok=True)
        (dest / filename).write_bytes(m.blob)
        return {
            "ok": True,
            "filename": filename,
            "size": len(m.blob),
            "data_b64": base64.b64encode(m.blob).decode("ascii"),
        }

    def push_app(self, filename: str, data: bytes) -> dict:
        m = self._appmgr().push(data)
        return {"ok": True, "name": m.name, "size": len(m.blob)}

    def inspect_app(self, data: bytes) -> dict:
        """Read-only metadata for a user-supplied .nwa (ELF or flat) — the decoded icon AND the
        real app name, so a dropped file shows its icon and its true on-device name in the plan
        immediately (the filename stem often differs in case/spelling, which used to let a
        same-named app be staged twice). Nothing is written or uploaded."""
        from ..formats.appicon import decode_app_icon

        return {"icon": decode_app_icon(data), "size": len(data), "name": _nwa_app_name(data)}

    def fetch_app(self, url: str) -> dict:
        """Download a catalogue app's .nwa server-side (the browser can't, CORS) for temporary
        in-memory staging. SSRF-guarded + size-capped; see :mod:`nwupdater.apps.proxy`."""
        from ..apps import proxy

        return proxy.fetch(self.store, url, transport=self._transport)

    def open_app_stream(self, url: str):
        """Open a catalogue app's URL for STREAMING to the browser (byte-accurate progress bar).
        Returns ``(content_length_or_None, response)``; see :mod:`nwupdater.apps.proxy`."""
        from ..apps import proxy

        return proxy.open_stream(self.store, url)

    def add_store_app(self, name: str) -> dict:
        """Append a catalogue app to the region via minimal-rewrite (does NOT overwrite the
        others, unlike the legacy single-slot install_app)."""
        entry = self.store.get(name)
        if entry is None:
            raise ValueError(f"unknown app: {name}")
        if entry.local_path:
            # A user-provided local .nwa: install its REAL bytes verbatim (validated + verified by
            # AppManager.push), not a synthesized demo image.
            from pathlib import Path

            m = self._appmgr().push(Path(entry.local_path).read_bytes())
            return {"ok": True, "name": m.name, "size": len(m.blob)}
        if entry.url and "example.invalid" not in entry.url:
            # A real catalogue entry: download the actual .nwa server-side through the SSRF-guarded
            # proxy (the URL is allowlisted because it is in the store) and install its REAL bytes.
            # AppManager.push links a relocatable ELF as needed and runs validate_nwa — nothing is
            # synthesized. Only genuine placeholders (example.invalid) fall through to the demo.
            import base64

            fetched = self.fetch_app(entry.url)
            m = self._appmgr().push(base64.b64decode(fetched["data_b64"]))
            return {"ok": True, "name": m.name, "size": len(m.blob)}
        # Synthesize at the catalogue's declared size so demo region usage is realistic (a real
        # .nwa carries its own app_size; here we pad the body to match — header is 0x20 bytes,
        # plus the NUL-terminated name and the real, decodable demo icon).
        from ..formats.appicon import demo_icon_lz4

        icon = demo_icon_lz4(entry.name)
        body = max(256, (entry.size or 65536) - 0x20 - len(entry.name) - 1 - len(icon))
        blob = build_nwa(entry.name, api_level=entry.api_level, code=b"\x00" * body, icon=icon)
        m = self._appmgr().push(blob)
        return {"ok": True, "name": m.name, "size": len(m.blob)}

    def uninstall_app(self, name: str) -> dict:
        self._appmgr().uninstall(name)
        return {"ok": True}

    def uninstall_apps(self, names: list[str]) -> dict:
        """Remove several apps in one region rewrite (batched delete from the workshop)."""
        self._appmgr().uninstall_many(list(names))
        return {"ok": True, "removed": list(names)}

    def reorder_apps(self, order: list[str]) -> dict:
        self._appmgr().reorder(order)
        return {"ok": True}

    # -- Python scripts (SRAM storage) --

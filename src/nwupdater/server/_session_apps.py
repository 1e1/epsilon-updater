"""Third-party (.nwa) app operations for a session."""

from __future__ import annotations

from ..formats.nwa import build_nwa
from ._session_base import SessionBase


class AppsMixin(SessionBase):
    def apps(self) -> dict:
        i = self._identity()
        caps = self._capabilities(i)
        compat = self.store.compatible(
            family=i.family, device_api_level=self.api_level, has_external_apps=caps.external_apps
        )
        return {
            "has_external_apps": caps.external_apps,
            "api_level": self.api_level,
            "apps": [
                {
                    "name": e.name,
                    "version": e.version,
                    "api_level": e.api_level,
                    "description": e.description,
                    "source": e.source,
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
        from ..formats.appicon import decode_app_icon

        apps = self._appmgr().installed()
        local = self._local_apps_index()
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
            ]
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
        filename = Path(name if name.endswith(".nwa") else name + ".nwa").name
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
        """Read-only metadata for a user-supplied .nwa (ELF or flat) — the decoded icon, so a
        dropped file shows it in the plan immediately. Nothing is written or uploaded."""
        from ..formats.appicon import decode_app_icon

        return {"icon": decode_app_icon(data), "size": len(data)}

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

    def reorder_apps(self, order: list[str]) -> dict:
        self._appmgr().reorder(order)
        return {"ok": True}

    # -- Python scripts (SRAM storage) --

"""Python-scripts (SRAM storage) operations for a session."""

from __future__ import annotations

from .. import ensure_suffix
from ._session_base import SessionBase


class ScriptsMixin(SessionBase):
    def scripts(self) -> dict:
        from ..formats.storage import python_scripts
        from ..scripts import read_storage

        i = self._identity()
        if not self._capabilities(i).scripts:
            return {"has_scripts": False, "capacity": 0, "scripts": []}
        assert i.storage_ram is not None  # capabilities.scripts implies storage is present
        addr, size = i.storage_ram
        pys = python_scripts(read_storage(self.client, addr, size))
        local = self._local_scripts_index()
        return {
            "has_scripts": True,
            "capacity": size,
            "scripts": [
                {
                    "name": r.fullname,
                    "size": len(r.code),
                    "auto_import": r.auto_import,
                    "code": r.code,
                    # True when a same-name, same-length .py already sits in the local library.
                    "local": local.get(r.fullname) == len(r.code),
                }
                for r in pys
            ],
            "available": self._scripts_available(),
        }

    @staticmethod
    def _local_scripts_index() -> dict[str, int]:
        """``{filename: char_length}`` for the ``.py`` files in the user scripts library — used to
        flag an installed script as already on the computer (same name AND same size). Length is
        measured in characters to match the installed ``size`` (``len(code)``), so the comparison
        is encoding-independent."""
        from ..apps.sources import scan_local, user_scripts_dir

        idx: dict[str, int] = {}
        for it in scan_local(user_scripts_dir(), [".py"]):
            if it.path is None:
                continue
            try:
                idx[it.name] = len(it.path.read_text(encoding="utf-8"))
            except OSError:
                continue
        return idx

    def export_script(self, name: str) -> dict:
        """Read an installed script off the device and save it into the local scripts library
        (``<scripts_dir>/<name>.py``, created on demand), returning its code so the browser
        downloads it too. After this the script matches the library, so the UI flips to "already
        on the computer"."""
        from pathlib import Path

        from ..apps.sources import user_scripts_dir
        from ..formats.storage import python_scripts
        from ..scripts import read_storage

        i = self._identity()
        if not i.storage_ram:
            raise ValueError("this model has no Python scripts (no storage)")
        addr, size = i.storage_ram
        full = ensure_suffix(name, ".py")
        rec = next(
            (
                r
                for r in python_scripts(read_storage(self.client, addr, size))
                if r.fullname == full
            ),
            None,
        )
        if rec is None:
            raise ValueError(f"script not installed: {name}")
        dest = user_scripts_dir()
        dest.mkdir(parents=True, exist_ok=True)
        (dest / Path(full).name).write_text(rec.code, encoding="utf-8")
        return {"ok": True, "filename": full, "code": rec.code}

    @staticmethod
    def _scripts_available() -> list[dict]:
        """Catalogue of *available* Python scripts: the bundled community catalogue merged with the
        user's own generic sources (local ``.py`` files + a ``_urls.txt`` list under the user
        scripts dir). Mirrors the app catalogue; an EMPTY bundled list is expected."""
        from urllib.parse import urlparse

        from ..apps.sources import aggregate, user_scripts_dir
        from ..scripts import bundled_scripts

        out: list[dict] = list(bundled_scripts())
        seen = {s.get("name") for s in out}
        for it in aggregate(user_scripts_dir(), [".py"]):
            if it.name in seen:
                continue
            seen.add(it.name)
            entry: dict = {
                "name": it.name,
                "size": it.size or 0,
                "source": (
                    "local file"
                    if it.origin == "local"
                    else (urlparse(it.url).hostname or "remote")
                ),
            }
            if it.url:
                entry["url"] = it.url
            out.append(entry)
        return out

    def sources(self) -> dict:
        """Resolved sources feeding the "Available" apps & scripts lists, for the UI's Sources
        popover: the app/script source URLs plus the two local user directories. Each entry is
        tagged ``kind`` (``online`` | ``cloud`` | ``local``) so the client can hide personal
        (cloud) sources in classroom mode. No device I/O — reads the catalogue + configured dirs."""
        from urllib.parse import urlparse

        from ..apps.sources import user_apps_dir, user_scripts_dir

        def kind_of(source: str, url: str, local_path: str = "") -> str:
            if local_path or not url:
                return "local"
            host = (urlparse(url).hostname or "").lower()
            if "numworks" in host or "cloud" in (source or "").lower():
                return "cloud"
            return "online"

        apps: list[dict] = []
        seen_a: set[str] = set()
        for e in self.store.entries:
            key = e.url or e.local_path or e.source or e.name
            if key in seen_a:
                continue
            seen_a.add(key)
            apps.append(
                {
                    "label": e.name,
                    "source": e.source,
                    "url": e.url,
                    "kind": kind_of(e.source, e.url, e.local_path),
                }
            )
        scripts: list[dict] = []
        seen_s: set[str] = set()
        for s in self._scripts_available():
            url = str(s.get("url", "") or "")
            src = str(s.get("source", "") or "")
            key = url or src or str(s.get("name", ""))
            if key in seen_s:
                continue
            seen_s.add(key)
            scripts.append(
                {"label": s.get("name", ""), "source": src, "url": url, "kind": kind_of(src, url)}
            )
        return {
            "apps": apps,
            "scripts": scripts,
            "dirs": {"apps": str(user_apps_dir()), "scripts": str(user_scripts_dir())},
        }

    def reveal_folder(self, which: str) -> dict:
        """Open the local apps/scripts library folder in the OS file manager (so the teacher can
        purge files by hand). Whitelisted to the two managed directories — the client sends only
        the key ``"apps"``/``"scripts"``, so no arbitrary path ever reaches the shell, and the
        command is a fixed argv (never ``shell=True``)."""
        import subprocess
        import sys

        from ..apps.sources import user_apps_dir, user_scripts_dir

        dirs = {"apps": user_apps_dir, "scripts": user_scripts_dir}
        resolve = dirs.get(which)
        if resolve is None:
            raise ValueError("unknown folder")
        path = resolve()
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            argv = ["open", str(path)]
        elif sys.platform.startswith("win"):
            argv = ["explorer", str(path)]
        else:
            argv = ["xdg-open", str(path)]
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError) as exc:  # no file manager / bad launcher — surfaced to the UI
            raise RuntimeError(f"could not open the folder: {exc}") from exc
        return {"ok": True, "which": which, "path": str(path)}

    def _write_scripts(self, keep_pred) -> dict:
        from ..scripts import read_storage, write_storage

        i = self._identity()
        if not i.storage_ram:
            raise ValueError("this model has no Python scripts (no storage)")
        addr, size = i.storage_ram
        recs = read_storage(self.client, addr, size)
        extra: list = []
        kept = keep_pred(recs, extra)
        n = write_storage(self.client, addr, kept + extra, capacity=size)
        return {"ok": True, "written": n, "capacity": size}

    def push_script(self, name: str, code: str, auto_import: bool = True) -> dict:
        from ..formats.storage import make_python

        full = ensure_suffix(name, ".py")
        return self._write_scripts(
            lambda recs, extra: (
                extra.append(make_python(name, code, auto_import))
                or [r for r in recs if r.fullname != full]
            )
        )

    def delete_script(self, name: str) -> dict:
        full = ensure_suffix(name, ".py")
        return self._write_scripts(lambda recs, extra: [r for r in recs if r.fullname != full])

    def set_scripts(self, items: list[dict]) -> dict:
        """Rewrite the Python storage to exactly ``items`` (name, code, auto_import) in the given
        order — the workshop's atomic commit for scripts (add + erase + reorder in one write)."""
        from ..formats.storage import make_python
        from ..scripts import write_storage

        i = self._identity()
        if not i.storage_ram:
            raise ValueError("this model has no Python scripts (no storage)")
        addr, size = i.storage_ram
        recs = [
            make_python(
                str(it.get("name", "")).removesuffix(".py"),
                it.get("code", ""),
                bool(it.get("auto_import", True)),
            )
            for it in items
        ]
        n = write_storage(self.client, addr, recs, capacity=size)
        return {"ok": True, "written": n, "capacity": size}

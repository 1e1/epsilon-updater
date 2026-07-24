"""Python-scripts (SRAM storage) operations for a session."""

from __future__ import annotations

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
        full = name if name.endswith(".py") else name + ".py"
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
        """Illustrative catalogue of *available* Python scripts (cloud / local / remote).

        Sample metadata only — the real flow lists the user's own local files and the public
        scripts on my.numworks.com/python. Mirrors the illustrative app catalogue."""
        return [
            {"name": "devoir.py", "size": 640, "source": "local"},
            {"name": "hex.py", "size": 10240, "source": "my.numworks.com/python/…/hex.py"},
            {"name": "stats_bac.py", "size": 1433, "source": "NumWorks cloud"},
            {"name": "tri_fusion.py", "size": 820, "source": "NumWorks cloud"},
        ]

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

        full = name if name.endswith(".py") else name + ".py"
        return self._write_scripts(
            lambda recs, extra: (
                extra.append(make_python(name, code, auto_import))
                or [r for r in recs if r.fullname != full]
            )
        )

    def delete_script(self, name: str) -> dict:
        full = name if name.endswith(".py") else name + ".py"
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

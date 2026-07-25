"""Session layer: holds a connected calculator (virtual by default) and exposes the Lot 2/3/4
operations as plain dicts for the local HTTP API.

The implementation is split by responsibility across a shared base and concern mixins; ``Session``
composes them so the public method surface is one flat, stable API.
"""

from __future__ import annotations

from ._session_apps import AppsMixin
from ._session_auth import AuthMixin
from ._session_base import SessionBase
from ._session_catalog import CatalogMixin
from ._session_firmware import FirmwareMixin
from ._session_names import NamesMixin
from ._session_roster import RosterMixin
from ._session_scripts import ScriptsMixin


class Session(
    CatalogMixin,
    AppsMixin,
    AuthMixin,
    FirmwareMixin,
    ScriptsMixin,
    NamesMixin,
    RosterMixin,
    SessionBase,
):
    """The updater session: device lifecycle + catalogue + apps + auth + firmware + scripts +
    local calculator naming + the classroom roster (local fleet register)."""

    # -- classroom batch (kiosk): one per-device pass composing the atomic operations --------------
    def batch_run(self, class_name: str) -> dict:
        """Run a class's distribution chain against the CURRENTLY connected calculator — the batch
        kiosk's per-device pass. Composes the existing atomic operations (roster filing · firmware
        flash from cache · app/script push), records the per-action outcome and returns a journal
        entry. Each action is independent: a failure marks that action ``error`` without aborting the
        pass — except an ``ignore`` recensement of a calculator already filed elsewhere, which stops
        (we never touch a calculator ranged in another class)."""
        from .. import classroom_roster as R
        from .. import device_names

        cls = (class_name or "").strip()
        if not cls:
            raise ValueError("no class")
        i = self._identity()
        serial = (i.serial_number or "").strip()
        if not serial:
            raise ValueError("no serial")
        key = device_names._key(i.model_name or "", serial)
        R.upsert_on_scan(i.model_name or "", serial, firmware=i.os_version, family=i.family)
        cfg = R.distribution(cls)
        acts = cfg["actions"]
        dist: dict[str, str] = {}
        if acts.get("census"):
            entry = next((e for e in R.all_entries() if e["key"] == key), None)
            cur = entry["class"] if entry else None
            if cur and cur != cls:
                if (
                    cfg["onboarding"] == "ignore"
                ):  # already ranged elsewhere → refuse, stop the chain
                    dist["recensement"] = "error"
                    R.set_last_dist(key, dist)
                    return self._batch_journal(key, i, dist)
                R.move([key], cls)
                dist["recensement"] = "change"  # moved from another class
            else:
                R.move([key], cls)
                dist["recensement"] = "ok"  # newly filed / already in this class
        if acts.get("firmware"):
            dist["firmware"] = self._batch_firmware()
        if acts.get("apps"):
            dist["apps"] = self._batch_apps(cfg.get("apps") or [])
        if acts.get("scripts"):
            dist["scripts"] = self._batch_scripts(cfg.get("scripts") or [])
        R.set_last_dist(key, dist)
        return self._batch_journal(key, i, dist)

    def _batch_journal(self, key: str, i, dist: dict) -> dict:
        """A journal row for the batch UI. ``key`` (``model:serial``) is an OPAQUE id for the client
        to detect re-plugs of the same calculator; it holds the serial and is NEVER rendered."""
        from .. import device_names

        model, _, serial = key.partition(":")
        return {
            "key": key,
            "name": device_names.get_name(model, serial),
            "default": f"calc {(i.model_name or '').upper()}",
            "model": i.model_name,
            "family": i.family,
            "firmware": i.os_version,
            "dist": dist,
        }

    def _batch_firmware(self) -> str:
        """Flash the latest firmware from the cache when the connected calculator is behind; ``ok``
        if already up to date, ``error`` on any failure (e.g. the image isn't cached)."""
        from ..catalog import version as V

        try:
            i = self._identity()
            latest = self._catalog_for(i.family, self.channel).latest()
            if latest is None or not i.os_version:
                return "ok"
            if not V.is_newer(latest.version, i.os_version):
                return "ok"
            self.install_firmware(latest.version, from_cache=True, channel=self.channel)
            return "change"
        except Exception:
            return "error"

    def _batch_apps(self, names: list[str]) -> str:
        """Install the class's app set that's missing from the device; ``change`` if any was added,
        ``ok`` if none were needed, ``error`` on failure (e.g. nwlink absent for a distributed .nwa)."""
        try:
            installed = {
                a.get("name") for a in self.installed_apps_on_device().get("installed", [])
            }
            changed = False
            for n in names:
                if n in installed:
                    continue
                self.add_store_app(n)
                changed = True
            return "change" if changed else "ok"
        except Exception:
            return "error"

    def _batch_scripts(self, names: list[str]) -> str:
        """Push the class's script set that's missing from the device, reading each from the local
        scripts library. ``change`` if any was added, ``ok`` if none were needed, ``error`` if a
        requested script isn't in the local library (or a push fails)."""
        from ..apps.sources import user_scripts_dir

        try:
            on_device = {s.get("name") for s in self.scripts().get("scripts", [])}
            d = user_scripts_dir()
            changed = False
            for n in names:
                base = n if n.endswith(".py") else n + ".py"
                if base in on_device or n in on_device:
                    continue
                f = d / base
                if not f.is_file():
                    return "error"
                self.push_script(base, f.read_text(encoding="utf-8"), True)
                changed = True
            return "change" if changed else "ok"
        except Exception:
            return "error"

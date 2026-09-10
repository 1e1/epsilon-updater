"""The single QObject the QML scene talks to.

Layering, deliberately: everything that can be decided without a window lives in a plain module
(:mod:`plan`, :mod:`workshop`, :mod:`roster`, :mod:`format`) and is unit-tested there. This class
is only the Qt adapter — properties, slots, signals — plus the rule that no device call ever runs
on the GUI thread (:mod:`jobs`). It holds no business rule of its own, which is why it stays
readable at a glance and why the write-plan can be tested without Qt at all.

That threading rule covers *reads* too, not just writes: :meth:`refresh` reads the whole
inventory in a worker and hands back one snapshot, which the GUI thread then assigns. Doing it
inline — as the first cut did — stalled the window for the duration of every hot-plug poll.

There is no HTTP in between: the native UI drives :class:`~nwupdater.server.session.Session`
in-process, so the loopback server, its CSRF guard, the single-instance file and the idle timeout
are all simply absent from this path.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from ..server.session import Session
from . import roster as R
from .format import fmt_bytes
from .jobs import JobRunner
from .models import RowsModel
from .workshop import ROW_FIELDS, Workshop

HOTPLUG_INTERVAL_MS = 4000
KINDS = ("apps", "scripts")


class Backend(QObject):
    """QML-facing façade over one :class:`Session`."""

    identityChanged = Signal()
    catalogChanged = Signal()
    workshopChanged = Signal()
    rosterChanged = Signal()
    authChanged = Signal()
    distChanged = Signal()
    batchChanged = Signal()
    modeChanged = Signal()
    busyChanged = Signal()
    progressChanged = Signal()
    # (i18n key, placeholder values, isError) — never a rendered sentence. The status bar calls
    # i18n.t(key, params), so a message follows a language switch and is never shown raw.
    toast = Signal(str, dict, bool)

    def __init__(self, session: Session, parent: QObject | None = None):
        super().__init__(parent)
        self._s = session
        self._jobs = JobRunner(self)

        self._busy = ""
        self._progress = -1.0
        self._progress_label = ""
        self._identity: dict = {}
        self._catalog: dict = {}
        self._cache: dict = {}
        self._device_name: dict = {}
        self._roster: dict = {}
        self._auth: dict = {}
        self._parc_class = R.CLASS_ALL
        self._parc_filter = ""
        self._batch: dict[str, Any] = {
            "armed": False,
            "className": "",
            "journal": [],
            "running": False,
        }
        self._shops: dict[str, Workshop | None] = {k: None for k in KINDS}
        self._demo_models = [m["name"] for m in session.demo_models()]
        self._refreshing = False
        self._refresh_again = False
        self._stopped = False

        self.appsDevice = RowsModel(ROW_FIELDS)
        self.appsAvail = RowsModel(ROW_FIELDS)
        self.scriptsDevice = RowsModel(ROW_FIELDS)
        self.scriptsAvail = RowsModel(ROW_FIELDS)
        self.rosterModel = RowsModel(R.ROSTER_FIELDS, key="key")
        self.classesModel = RowsModel(R.CLASS_FIELDS, key="classId")

        # Hot-plug watch: the web UI's 4 s fetch loop is just a timer here.
        self._timer = QTimer(self)
        self._timer.setInterval(HOTPLUG_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        # The first read is a job like any other: the window paints its disconnected state
        # immediately and fills in when the worker returns, instead of appearing only once the
        # whole calculator has been read.
        QTimer.singleShot(0, self.refresh)

    # -- plumbing ---------------------------------------------------------------------
    def _run(self, key: str, fn, then=None, ok_key: str | None = None, ok_params=None) -> None:
        """Submit a blocking call; report back on the GUI thread. One at a time, by design:
        the device is a single serial resource and the UI mirrors that honestly."""
        if self._busy:
            # Controls bind to `busy`, but a keyboard shortcut can still get here. Say so
            # rather than dropping the gesture in silence.
            self.toast.emit("busy_wait", {}, True)
            return
        self._set_busy(key)

        def done(result: Any) -> None:
            self._set_busy("")
            self._set_progress(-1.0, "")
            if then:
                then(result)
            if ok_key:
                self.toast.emit(ok_key, dict(ok_params or {}), False)

        def failed(message: str) -> None:
            self._set_busy("")
            self._set_progress(-1.0, "")
            self._fail(message)

        self._jobs.submit(fn, done, failed)

    def _fail(self, message: str) -> None:
        """Surface a raw exception message the way the web UI does: wrapped in `fail`, so the
        sentence around it is translated even though the cause is not."""
        self.toast.emit("fail", {"msg": message}, True)

    def _set_busy(self, key: str) -> None:
        if key != self._busy:
            self._busy = key
            self.busyChanged.emit()

    def _set_progress(self, value: float, label: str) -> None:
        self._progress, self._progress_label = value, label
        self.progressChanged.emit()

    def _guard(self, fn) -> None:
        """A cheap local mutation (register only, no device): run it, surface the error, and
        re-read the register. No worker — this is a small JSON file, not the USB bus."""
        try:
            fn()
        except Exception as exc:
            self._fail(str(exc))
            return
        self._reload_roster()

    # -- constants shared with the pure layer -----------------------------------------
    # The rail's two synthetic buckets. QML compared against hard-coded "__all__" strings in
    # eight places before these existed; roster.py stays the single source of truth.
    @Property(str, constant=True)
    def classAll(self) -> str:
        return R.CLASS_ALL

    @Property(str, constant=True)
    def classUnfiled(self) -> str:
        return R.CLASS_UNFILED

    # -- state properties -------------------------------------------------------------
    @Property(dict, notify=identityChanged)
    def identity(self) -> dict:
        return self._identity

    @Property(dict, notify=identityChanged)
    def deviceName(self) -> dict:
        return self._device_name

    def is_connected(self) -> bool:
        return bool(self._identity.get("connected"))

    @Property(bool, notify=identityChanged)
    def connected(self) -> bool:
        return self.is_connected()

    @Property(dict, notify=catalogChanged)
    def catalog(self) -> dict:
        return self._catalog

    @Property(dict, notify=catalogChanged)
    def cacheStatus(self) -> dict:
        return {"entries": [], **self._cache}

    @Property(dict, notify=rosterChanged)
    def roster(self) -> dict:
        return self._roster

    @Property(dict, notify=authChanged)
    def auth(self) -> dict:
        return self._auth

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return "classroom" if self._s.policy.classroom else "individual"

    @Property(str, notify=busyChanged)
    def busy(self) -> str:
        return self._busy

    @Property(float, notify=progressChanged)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=progressChanged)
    def progressLabel(self) -> str:
        return self._progress_label

    @Property(list, constant=True)
    def demoModels(self) -> list:
        return self._demo_models

    @Property(QObject, constant=True)
    def appsDeviceModel(self):
        return self.appsDevice

    @Property(QObject, constant=True)
    def appsAvailModel(self):
        return self.appsAvail

    @Property(QObject, constant=True)
    def scriptsDeviceModel(self):
        return self.scriptsDevice

    @Property(QObject, constant=True)
    def scriptsAvailModel(self):
        return self.scriptsAvail

    @Property(QObject, constant=True)
    def rosterRows(self):
        return self.rosterModel

    @Property(QObject, constant=True)
    def classes(self):
        return self.classesModel

    @Property(dict, notify=workshopChanged)
    def appsPlan(self) -> dict:
        return self._plan_view("apps")

    @Property(dict, notify=workshopChanged)
    def scriptsPlan(self) -> dict:
        return self._plan_view("scripts")

    def _plan_view(self, kind: str) -> dict:
        shop = self._shops.get(kind)
        return shop.plan_view() if shop else {"enabled": False}

    # -- refresh ----------------------------------------------------------------------
    # One job reads everything; the GUI thread only assigns. Two guards: a refresh never runs
    # while a user operation holds the device (that operation triggers one when it finishes),
    # and a request arriving mid-refresh is coalesced into a single follow-up.
    @Slot()
    def refresh(self) -> None:
        if self._stopped or self._busy:
            return
        if self._refreshing:
            self._refresh_again = True
            return
        self._refreshing = True
        self._jobs.submit(self._read_snapshot, self._apply_snapshot, self._refresh_failed)

    def _refresh_failed(self, message: str) -> None:
        self._refreshing = False
        self._fail(message)
        self._drain_refresh()

    def _drain_refresh(self) -> None:
        if self._refresh_again:
            self._refresh_again = False
            self.refresh()

    def _read_snapshot(self) -> dict:
        """Read the whole inventory in the worker. Device reads share ONE hold of the session
        lock (a consistent view, and the liveness poll waits once instead of six times); the
        register and the token store are local files and stay outside it."""
        snap: dict[str, Any] = {}
        with self._s.io():
            snap["identity"] = self._s.identity()
            try:
                snap["catalog"] = self._s.catalog_updates()
            except Exception:
                snap["catalog"] = {}
            if snap["identity"].get("connected"):
                shops: dict[str, Workshop | None] = {}
                for kind in KINDS:
                    try:
                        shops[kind] = self._read_workshop(kind, snap["identity"])
                    except Exception:
                        shops[kind] = Workshop(kind, [], [], 0, enabled=False)
                snap["shops"] = shops
            else:
                snap["shops"] = {k: None for k in KINDS}
        for field, read in (
            ("device_name", self._s.device_name),
            ("cache", self._s.cache_status),
            ("roster", self._s.roster),
        ):
            try:
                snap[field] = read()
            except Exception:
                snap[field] = {}
        try:
            snap["auth"] = self._s.auth_status()
        except Exception:
            snap["auth"] = {"authenticated": False, "expired": False, "expires_at": None}
        return snap

    def _apply_snapshot(self, snap: dict) -> None:
        """GUI thread: assign and notify. No I/O here, by construction."""
        self._refreshing = False
        if self._stopped:
            return
        self._identity = snap["identity"]
        self._device_name = snap["device_name"]
        self._catalog = snap["catalog"]
        self._cache = snap["cache"]
        self._auth = snap["auth"]
        self._roster = snap["roster"]
        self._shops = snap["shops"]
        self.identityChanged.emit()
        self.catalogChanged.emit()
        self.authChanged.emit()
        self._publish_workshops()
        self._project_roster()
        self.rosterChanged.emit()
        self.distChanged.emit()
        self._drain_refresh()

    def _read_workshop(self, kind: str, identity: dict) -> Workshop:
        """Read one workshop off the device. The caller holds the session lock.

        Only the fields the UI draws are kept — notably NOT the decoded app icons, which are
        large and unused by the native rows."""
        if kind == "apps":
            info = self._s.apps()
            installed = self._s.installed_apps_on_device()
            device = [
                {
                    "name": a["name"],
                    "size": a.get("size") or 0,
                    "apiLevel": a.get("api_level"),
                    "local": a.get("local"),
                }
                for a in installed.get("installed", [])
            ]
            available = [
                {
                    "name": a["name"],
                    "size": a.get("size") or 0,
                    "apiLevel": a.get("api_level"),
                    "source": a.get("source") or "",
                }
                for a in info.get("apps", [])
            ]
            return Workshop(
                kind,
                device,
                available,
                self._apps_capacity(identity),
                enabled=bool(info.get("has_external_apps")),
                device_api=int(info.get("api_level") or 0),
            )
        info = self._s.scripts()
        device = [
            {
                "name": s["name"],
                "size": s.get("size") or 0,
                "local": s.get("local"),
                "autoImport": s.get("auto_import"),
                "code": s.get("code", ""),
            }
            for s in info.get("scripts", [])
        ]
        available = [
            {
                "name": s["name"],
                "size": s.get("size") or 0,
                "source": s.get("source") or "",
                "autoImport": s.get("auto_import"),
                "code": s.get("code", ""),
            }
            for s in info.get("available", [])
        ]
        return Workshop(
            kind,
            device,
            available,
            info.get("capacity") or 0,
            enabled=bool(info.get("has_scripts")),
        )

    @staticmethod
    def _apps_capacity(identity: dict) -> int:
        flash = identity.get("external_apps_flash") or []
        if len(flash) == 2:
            try:
                return int(flash[1], 16) - int(flash[0], 16)
            except (TypeError, ValueError):
                pass
        return 0

    def _publish_workshops(self) -> None:
        for kind, device_model, avail_model in (
            ("apps", self.appsDevice, self.appsAvail),
            ("scripts", self.scriptsDevice, self.scriptsAvail),
        ):
            shop = self._shops[kind]
            device_model.set_rows(shop.device_rows() if shop else [])
            avail_model.set_rows(shop.available_rows() if shop else [])
        self.workshopChanged.emit()

    def _project_roster(self) -> None:
        """Re-slice the register already in memory. The filter path runs ONLY this: re-reading
        the register on every keystroke cost ~30 ms a character on a class set of any size."""
        self.rosterModel.set_rows(R.roster_rows(self._roster, self._parc_class, self._parc_filter))
        self.classesModel.set_rows(R.class_buckets(self._roster))

    def _reload_roster(self) -> None:
        """Re-read the register (a local JSON file) and re-project. Cheap enough to stay
        synchronous — device I/O is what must never touch this thread."""
        try:
            self._roster = self._s.roster()
        except Exception:
            self._roster = {}
        self._project_roster()
        self.rosterChanged.emit()

    # -- hot plug ---------------------------------------------------------------------
    def _tick(self) -> None:
        """Watch for a calculator being plugged in, or the cable being pulled. The probe itself
        is USB traffic, so it runs in a worker like everything else."""
        if self._stopped or self._busy or self._refreshing:
            return
        if not self.is_connected():
            self._jobs.submit(self._probe_attach, self._probed_attach, lambda _m: None)
        elif not self._identity.get("virtual"):
            self._jobs.submit(self._probe_health, self._probed_health, lambda _m: None)

    def _probe_attach(self) -> bool:
        try:
            with self._s.io():
                return bool(self._s.attach_real().get("connected"))
        except Exception:
            return False

    def _probed_attach(self, attached: bool) -> None:
        if attached and not self._stopped:
            self.refresh()
            self.toast.emit("real_connected", {}, False)

    def _probe_health(self) -> bool:
        """True when the cable is gone. Detaching is part of the probe so the session is never
        left holding a handle to a calculator that has left."""
        try:
            if self._s.device_health().get("connected") is False:
                self._s.detach()
                return True
        except Exception:
            pass
        return False

    def _probed_health(self, lost: bool) -> None:
        if lost and not self._stopped:
            self.refresh()
            self.toast.emit("device_lost", {}, True)

    # -- device -----------------------------------------------------------------------
    def _reloaded(self, _: object) -> None:
        self.refresh()

    def _installed(self, result: dict) -> None:
        self.refresh()
        # Same key as the web UI. `slot` and `cache` are its optional tails, empty here.
        self.toast.emit(
            "fw_done", {"v": result.get("to_version", ""), "slot": "", "cache": ""}, False
        )

    def _caches_updated(self, _: object) -> None:
        self.refresh()
        self.toast.emit("caches_updated", {}, False)

    def _signed_in(self, _: object) -> None:
        self.refresh_auth()
        self.toast.emit("auth_saved", {}, False)

    def _demo_attached_for_batch(self, _: object) -> None:
        self.refresh()
        self.batchRunOnce()

    @Slot()
    def rescan(self):
        self._run("device", self._probe_attach_strict, self._reloaded)

    def _probe_attach_strict(self) -> dict:
        with self._s.io():
            return self._s.attach_real()

    @Slot(str)
    def exploreDemo(self, model: str):
        def work():
            with self._s.io():
                return self._s.attach_demo(model)

        self._run("device", work, self._reloaded)

    @Slot()
    def detach(self):
        self._s.detach()
        self.refresh()
        self.toast.emit("disconnected_toast", {}, False)

    @Slot(str)
    def setMode(self, mode: str):
        self._s.set_mode(mode)
        self.modeChanged.emit()
        self._reload_roster()
        self.distChanged.emit()

    @Slot(str)
    def setDeviceName(self, name: str):
        try:
            self._s.set_device_name(name)
            self._device_name = self._s.device_name()
        except Exception as exc:
            self._fail(str(exc))
            return
        self.identityChanged.emit()
        self._reload_roster()

    # -- firmware ---------------------------------------------------------------------
    @Slot(str)
    def setChannel(self, channel: str):
        def work():
            # Assigned inside the job, not before it: `_run` refuses while another operation
            # holds the device, and a channel switched without its catalogue re-read leaves the
            # session pointing at one channel and the pane showing another.
            self._s.channel = channel
            with self._s.io():
                return self._s.catalog_updates()

        self._run("catalog", work, self._catalog_read)

    def _catalog_read(self, catalog: dict) -> None:
        self._catalog = catalog or {}
        self.catalogChanged.emit()

    @Slot(str, bool, bool)
    def installFirmware(self, version: str, from_cache: bool, download: bool):
        def progress(phase: str, done: int, total: int) -> None:
            # Emitted from the worker thread; Qt queues the change onto the GUI thread.
            self._set_progress(done / total if total else -1.0, phase)

        def work():
            with self._s.io():
                return self._s.install_firmware(
                    version,
                    from_cache=from_cache,
                    download=download,
                    channel=self._s.channel,
                    progress=progress,
                )

        self._run("firmware", work, self._installed)

    @Slot()
    def updateCaches(self):
        def work():
            with self._s.io():
                return self._s.preload_all()

        self._run("cache", work, self._caches_updated)

    # -- account ----------------------------------------------------------------------
    def refresh_auth(self) -> None:
        try:
            self._auth = self._s.auth_status()
        except Exception:
            self._auth = {"authenticated": False, "expired": False, "expires_at": None}
        self.authChanged.emit()

    @Slot(str)
    def loginToken(self, token: str):
        self._run("auth", lambda: self._s.login_token(token), self._signed_in)

    @Slot(str, str)
    def loginPassword(self, email: str, password: str):
        # The password buys a token once and is never stored (Session's contract).
        self._run("auth", lambda: self._s.login_password(email, password), self._signed_in)

    @Slot()
    def logout(self):
        try:
            self._s.logout()
        except Exception as exc:
            self._fail(str(exc))
            return
        self.refresh_auth()
        self.toast.emit("auth_gone", {}, False)

    # -- workshops --------------------------------------------------------------------
    @Slot(str, str)
    def stageAdd(self, kind: str, name: str):
        shop = self._shops.get(kind)
        entry = shop.entry(name) if shop else None
        if shop is None or entry is None:
            return
        if not shop.stage.add(name, entry.get("size") or 0, entry):
            self.toast.emit("already_staged", {"name": name}, True)
            return
        self._publish_workshops()

    @Slot(str, str)
    def stageRemove(self, kind: str, name: str):
        self._edit_stage(kind, lambda shop: shop.stage.remove(name))

    @Slot(str, str)
    def stageRestore(self, kind: str, name: str):
        self._edit_stage(kind, lambda shop: shop.stage.restore(name))

    @Slot(str, str, int)
    def stageMove(self, kind: str, name: str, direction: int):
        self._edit_stage(kind, lambda shop: shop.stage.move(name, direction))

    @Slot(str)
    def stageUndo(self, kind: str):
        self._edit_stage(kind, lambda shop: shop.stage.undo())

    @Slot(str)
    def stageReset(self, kind: str):
        self._edit_stage(kind, lambda shop: shop.stage.reset())

    def _edit_stage(self, kind: str, mutate) -> None:
        shop = self._shops.get(kind)
        if shop is None:
            return
        mutate(shop)
        self._publish_workshops()

    @Slot(str, QUrl)
    def addLocalFile(self, kind: str, url: QUrl):
        """Take a file dropped from the desktop (or picked in the native dialog) into the plan."""
        path = Path(url.toLocalFile())
        shop = self._shops.get(kind)
        if shop is None or not path.is_file():
            return
        wanted = ".nwa" if kind == "apps" else ".py"
        if path.suffix.lower() != wanted:
            self.toast.emit("wrong_ext", {"ext": wanted}, True)
            return
        data = path.read_bytes()
        entry: dict[str, Any] = {"source": "local", "path": str(path)}
        if kind == "apps":
            entry["data"] = base64.b64encode(data).decode()
            name = path.stem
        else:
            entry["code"] = data.decode("utf-8", "replace")
            entry["autoImport"] = True
            name = path.name
        if shop.stage.add(name, len(data), entry):
            self._publish_workshops()
        else:
            self.toast.emit("already_staged", {"name": name}, True)

    @Slot(str)
    def commit(self, kind: str):
        """Write the plan. Apps: erase what left, install what arrived, then set the order.
        Scripts: rewrite storage to exactly the kept records, in the staged order."""
        shop = self._shops.get(kind)
        if shop is None or not shop.stage.plan().dirty:
            return
        kept = shop.kept_slots()
        names = [s.name for s in kept]
        on_device = {s.name for s in shop.stage.slots if s.on_device}

        def work():
            with self._s.io():
                if kind == "apps":
                    for gone in on_device - set(names):
                        self._s.uninstall_app(gone)
                    for slot in kept:
                        if slot.name in on_device:
                            continue
                        blob = slot.extra.get("data")
                        if blob:  # a .nwa the user supplied, not a catalogue entry
                            self._s.install_local_app(f"{slot.name}.nwa", base64.b64decode(blob))
                        else:
                            self._s.install_app(slot.name)
                    self._s.reorder_apps(names)
                else:
                    self._s.set_scripts(
                        [
                            {
                                "name": s.name,
                                "code": s.extra.get("code", ""),
                                "auto_import": bool(s.extra.get("autoImport", True)),
                            }
                            for s in kept
                        ]
                    )
            return {"count": len(names)}

        self._run(f"write:{kind}", work, self._written)

    def _written(self, result: dict) -> None:
        self.refresh()
        self.toast.emit("written_ok", {"n": result.get("count", 0)}, False)

    @Slot(str, str, QUrl)
    def exportItem(self, kind: str, name: str, folder: QUrl):
        target = Path(folder.toLocalFile()) if folder.isValid() else Path.home() / "Downloads"

        def work():
            with self._s.io():
                result = self._s.export_app(name) if kind == "apps" else self._s.export_script(name)
            if "data_b64" in result:
                raw = base64.b64decode(result["data_b64"])
            else:
                raw = (result.get("code") or "").encode("utf-8")
            suffix = ".nwa" if kind == "apps" else ".py"
            out = target / (result.get("filename") or f"{name}{suffix}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(raw)
            return {"name": out.name}

        self._run("export", work, self._exported)

    def _exported(self, result: dict) -> None:
        self.toast.emit("exported", {"name": result.get("name", "")}, False)

    # -- roster -----------------------------------------------------------------------
    @Property(str, notify=rosterChanged)
    def parcClass(self) -> str:
        return self._parc_class

    @Property(str, notify=rosterChanged)
    def parcFilter(self) -> str:
        return self._parc_filter

    @Property(list, notify=rosterChanged)
    def rosterKeys(self) -> list:
        """Every calculator in the register, class and filter ignored. The table only ever sees
        the filtered rows, so this is what a selection is pruned against — dropping the keys of
        deleted calculators without forgetting the ones a filter is merely hiding."""
        return [str(c.get("key") or "") for c in (self._roster.get("calculators") or [])]

    def class_names(self) -> list[str]:
        return [str(c) for c in (self._roster.get("classes") or [])]

    @Property(list, notify=rosterChanged)
    def classNames(self) -> list:
        return self.class_names()

    @Property(int, notify=rosterChanged)
    def selectedClassCount(self) -> int:
        """Population of the selected class — the delete confirmation names it."""
        if self._parc_class in (R.CLASS_ALL, R.CLASS_UNFILED):
            return 0
        return int((self._roster.get("counts") or {}).get(self._parc_class, 0))

    @Slot(str)
    def selectClass(self, class_id: str):
        self._parc_class = class_id
        self._project_roster()
        self.rosterChanged.emit()
        self.distChanged.emit()

    @Slot(str)
    def setFilter(self, text: str):
        if text != self._parc_filter:
            self._parc_filter = text
            self._project_roster()
            self.rosterChanged.emit()

    @Slot(str, str)
    def rosterRename(self, key: str, name: str):
        self._guard(lambda: self._s.roster_rename(key, name))

    @Slot("QVariantList", str)
    def rosterMove(self, keys: list, class_name: str):
        self._guard(lambda: self._s.roster_move(list(keys), class_name or None))

    @Slot("QVariantList")
    def rosterDelete(self, keys: list):
        self._guard(lambda: self._s.roster_delete(list(keys)))

    @Slot(str)
    def classCreate(self, name: str):
        self._guard(lambda: self._s.roster_class_create(name))

    @Slot(str, str)
    def classRename(self, old: str, new: str):
        self._guard(lambda: self._s.roster_class_rename(old, new))

    @Slot(str, str)
    def classDelete(self, name: str, mode: str):
        self._guard(lambda: self._s.roster_class_delete(name, mode or None))
        if self._parc_class == name:
            self._parc_class = R.CLASS_ALL
            self._project_roster()
            self.rosterChanged.emit()
            self.distChanged.emit()

    # -- distribution -----------------------------------------------------------------
    def distribution_view(self) -> dict:
        return R.distribution_view(self._roster, self._parc_class)

    @Property(dict, notify=distChanged)
    def distribution(self) -> dict:
        return self.distribution_view()

    @Property(list, notify=distChanged)
    def batchSteps(self) -> list:
        return R.enabled_steps(self.distribution_view())

    @Slot(str, bool)
    def distSetAction(self, action: str, on: bool):
        view = self.distribution_view()
        if view["editable"]:
            actions = {**view["actions"], action: on}
            self._write_distribution({**self._dist_payload(view), "actions": actions})

    @Slot(str)
    def distSetOnboarding(self, mode: str):
        view = self.distribution_view()
        if view["editable"]:
            self._write_distribution({**self._dist_payload(view), "onboarding": mode})

    @Slot(str, str, bool)
    def distToggleItem(self, kind: str, name: str, on: bool):
        view = self.distribution_view()
        if not view["editable"]:
            return
        items = [n for n in view[kind] if n != name] + ([name] if on else [])
        self._write_distribution({**self._dist_payload(view), kind: items})

    @staticmethod
    def _dist_payload(view: dict) -> dict:
        return {
            "actions": view["actions"],
            "onboarding": view["onboarding"],
            "apps": view["apps"],
            "scripts": view["scripts"],
        }

    def _write_distribution(self, config: dict) -> None:
        try:
            self._s.roster_dist_set(self._parc_class, config)
        except Exception as exc:
            self._fail(str(exc))
            return
        self._reload_roster()
        self.distChanged.emit()

    # -- batch kiosk ------------------------------------------------------------------
    @Property(dict, notify=batchChanged)
    def batch(self) -> dict:
        return self._batch

    @Slot(result=bool)
    def armBatch(self) -> bool:
        """Arm the kiosk for the selected class, falling back to the first real class."""
        class_id = self._parc_class
        if class_id in (R.CLASS_ALL, R.CLASS_UNFILED):
            names = self.class_names()
            if not names:
                self.toast.emit("batch_need_class", {}, True)
                return False
            class_id = names[0]
            self._parc_class = class_id
            self._project_roster()
            self.rosterChanged.emit()
            self.distChanged.emit()
        self._batch = {"armed": True, "className": class_id, "journal": [], "running": False}
        self.batchChanged.emit()
        return True

    @Slot()
    def disarmBatch(self):
        self._batch = {"armed": False, "className": "", "journal": [], "running": False}
        self.batchChanged.emit()

    @Slot()
    def batchRunOnce(self):
        """Run the armed class's chain against the calculator currently plugged in."""
        if not (self._batch["armed"] and self.is_connected()) or self._batch["running"]:
            return
        class_id = self._batch["className"]
        self._batch = {**self._batch, "running": True}
        self.batchChanged.emit()

        def finish(entry: dict | None, error: str | None) -> None:
            previous: list = list(self._batch["journal"])
            journal = previous if entry is None else [entry, *previous]
            self._batch = {**self._batch, "running": False, "journal": journal}
            self._set_busy("")
            self.batchChanged.emit()
            if error:
                self._fail(error)
            else:
                self._reload_roster()

        def work():
            with self._s.io():
                return self._s.batch_run(class_id)

        self._set_busy("batch")
        self._jobs.submit(
            work,
            lambda entry: finish(entry, None),
            lambda message: finish(None, message),
        )

    @Slot(str)
    def batchSimulate(self, model: str):
        """Attach a demo device and run the SAME chain — testable without hardware."""
        if not self._batch["armed"]:
            return

        def work():
            with self._s.io():
                return self._s.attach_demo(model)

        self._run("device", work, self._demo_attached_for_batch)

    # -- app --------------------------------------------------------------------------
    def shutdown(self) -> None:
        """Stop watching the USB port, let in-flight workers finish, and release the device.

        Without this a backend outlives its window: the hot-plug timer keeps firing against a
        session that is on its way out, which is harmless in production but crashes as soon as
        two backends exist in one process (tests do exactly that). ``_stopped`` also makes every
        queued completion a no-op, so a worker that returns during teardown touches nothing.
        """
        self._stopped = True
        self._timer.stop()
        self._jobs.wait()
        try:
            self._s.detach()
        except Exception:
            pass


__all__ = ["Backend", "fmt_bytes"]

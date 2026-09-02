"""The single QObject the QML scene talks to.

Layering, deliberately: everything that can be decided without a window lives in a plain module
(:mod:`plan`, :mod:`workshop`, :mod:`roster`, :mod:`format`) and is unit-tested there. This class
is only the Qt adapter — properties, slots, signals — plus the rule that no device call ever runs
on the GUI thread (:mod:`jobs`). It holds no business rule of its own, which is why it stays
readable at a glance and why the write-plan can be tested without Qt at all.

There is no HTTP in between: the native UI drives :class:`~nwupdater.server.session.Session`
in-process, so the loopback server, its CSRF guard, the single-instance file and the idle timeout
are all simply absent from this path.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
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
    toast = Signal(str, bool)  # message, isError
    quitRequested = Signal()

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
        self.refresh_all()

    # -- plumbing ---------------------------------------------------------------------
    def _locked(self, fn: Callable, *a, **kw) -> Any:
        """Run a device call under the session's I/O lock (the same lock the health poll uses)."""
        with self._s._io_lock:
            return fn(*a, **kw)

    def _run(self, key: str, fn, then=None, ok_msg: str | None = None) -> None:
        """Submit a blocking call; report back on the GUI thread. One at a time, by design:
        the device is a single serial resource and the UI mirrors that honestly."""
        if self._busy:
            return
        self._set_busy(key)

        def done(result: Any) -> None:
            self._set_busy("")
            self._set_progress(-1.0, "")
            if then:
                then(result)
            if ok_msg:
                self.toast.emit(ok_msg, False)

        def failed(message: str) -> None:
            self._set_busy("")
            self._set_progress(-1.0, "")
            self.toast.emit(message, True)

        self._jobs.submit(fn, done, failed)

    def _set_busy(self, key: str) -> None:
        if key != self._busy:
            self._busy = key
            self.busyChanged.emit()

    def _set_progress(self, value: float, label: str) -> None:
        self._progress, self._progress_label = value, label
        self.progressChanged.emit()

    def _guard(self, fn) -> None:
        """A cheap local mutation: run it, surface the error, refresh the roster."""
        try:
            fn()
        except Exception as exc:
            self.toast.emit(str(exc), True)
            return
        self._refresh_roster()

    # -- state properties -------------------------------------------------------------
    @Property("QVariantMap", notify=identityChanged)  # type: ignore[arg-type]
    def identity(self) -> dict:
        return self._identity

    @Property("QVariantMap", notify=identityChanged)  # type: ignore[arg-type]
    def deviceName(self) -> dict:
        return self._device_name

    def is_connected(self) -> bool:
        return bool(self._identity.get("connected"))

    @Property(bool, notify=identityChanged)
    def connected(self) -> bool:
        return self.is_connected()

    @Property("QVariantMap", notify=catalogChanged)  # type: ignore[arg-type]
    def catalog(self) -> dict:
        return self._catalog

    @Property("QVariantMap", notify=catalogChanged)  # type: ignore[arg-type]
    def cacheStatus(self) -> dict:
        return {"entries": [], **self._cache}

    @Property("QVariantMap", notify=rosterChanged)  # type: ignore[arg-type]
    def roster(self) -> dict:
        return self._roster

    @Property("QVariantMap", notify=authChanged)  # type: ignore[arg-type]
    def auth(self) -> dict:
        return self._auth

    def current_mode(self) -> str:
        return "classroom" if self._s.policy.classroom else "individual"

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self.current_mode()

    @Property(str, notify=busyChanged)
    def busy(self) -> str:
        return self._busy

    @Property(float, notify=progressChanged)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=progressChanged)
    def progressLabel(self) -> str:
        return self._progress_label

    @Property("QVariantList", constant=True)  # type: ignore[arg-type]
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

    @Property("QVariantMap", notify=workshopChanged)  # type: ignore[arg-type]
    def appsPlan(self) -> dict:
        return self._plan_view("apps")

    @Property("QVariantMap", notify=workshopChanged)  # type: ignore[arg-type]
    def scriptsPlan(self) -> dict:
        return self._plan_view("scripts")

    def _plan_view(self, kind: str) -> dict:
        shop = self._shops.get(kind)
        return shop.plan_view() if shop else {"enabled": False}

    # -- refresh ----------------------------------------------------------------------
    def refresh_all(self) -> None:
        self._identity = self._locked(self._s.identity)
        try:
            self._device_name = self._s.device_name()
        except Exception:
            self._device_name = {}
        self.identityChanged.emit()
        self._refresh_catalog()
        self._refresh_workshops()
        self._refresh_roster()
        self.refresh_auth()

    def _refresh_catalog(self) -> None:
        try:
            self._catalog = self._locked(self._s.catalog_updates)
        except Exception:
            self._catalog = {}
        try:
            self._cache = self._s.cache_status()
        except Exception:
            self._cache = {}
        self.catalogChanged.emit()

    def refresh_auth(self) -> None:
        try:
            self._auth = self._s.auth_status()
        except Exception:
            self._auth = {"authenticated": False, "expired": False, "expires_at": None}
        self.authChanged.emit()

    def _refresh_workshops(self) -> None:
        if not self.is_connected():
            self._shops = {k: None for k in KINDS}
            for model in (self.appsDevice, self.appsAvail, self.scriptsDevice, self.scriptsAvail):
                model.set_rows([])
            self.workshopChanged.emit()
            return
        for kind in KINDS:
            try:
                self._shops[kind] = self._read_workshop(kind)
            except Exception:
                self._shops[kind] = Workshop(kind, [], [], 0, enabled=False)
        self._publish_workshops()

    def _read_workshop(self, kind: str) -> Workshop:
        """Read one workshop off the device. Only the fields the UI draws are kept — notably
        NOT the decoded app icons, which are large and unused by the native rows."""
        if kind == "apps":
            info = self._locked(self._s.apps)
            installed = self._locked(self._s.installed_apps_on_device)
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
                    "origin": a.get("origin") or "",
                }
                for a in info.get("apps", [])
            ]
            return Workshop(
                kind,
                device,
                available,
                self._apps_capacity(),
                enabled=bool(info.get("has_external_apps")),
            )
        info = self._locked(self._s.scripts)
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

    def _apps_capacity(self) -> int:
        flash = self._identity.get("external_apps_flash") or []
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
            if shop is None:
                continue
            device_model.set_rows(shop.device_rows())
            avail_model.set_rows(shop.available_rows())
        self.workshopChanged.emit()

    def _refresh_roster(self) -> None:
        try:
            self._roster = self._s.roster()
        except Exception:
            self._roster = {}
        self.rosterModel.set_rows(R.roster_rows(self._roster, self._parc_class, self._parc_filter))
        self.classesModel.set_rows(R.class_buckets(self._roster))
        self.rosterChanged.emit()

    # -- hot plug ---------------------------------------------------------------------
    def _tick(self) -> None:
        """Watch for a calculator being plugged in, or the cable being pulled."""
        if self._busy:
            return
        if not self.is_connected():
            try:
                if self._locked(self._s.attach_real).get("connected"):
                    self.refresh_all()
                    self.toast.emit("real_connected", False)
            except Exception:
                pass
        elif not self._identity.get("virtual"):
            try:
                if self._s.device_health().get("connected") is False:
                    self._s.detach()
                    self.refresh_all()
                    self.toast.emit("device_lost", True)
            except Exception:
                pass

    # -- device -----------------------------------------------------------------------
    def _reloaded(self, _: object) -> None:
        self.refresh_all()

    def _installed(self, result: dict) -> None:
        self.refresh_all()
        self.toast.emit(f"install_ok::{result.get('to_version', '')}", False)

    def _caches_updated(self, _: object) -> None:
        self._refresh_catalog()
        self.toast.emit("caches_updated", False)

    def _signed_in(self, _: object) -> None:
        self.refresh_auth()
        self.toast.emit("auth_saved", False)

    def _written(self, _: object) -> None:
        self._refresh_workshops()
        self.toast.emit("write_done", False)

    def _demo_attached_for_batch(self, _: object) -> None:
        self.refresh_all()
        self.batchRunOnce()

    @Slot()
    def rescan(self):
        self._run("device", lambda: self._locked(self._s.attach_real), self._reloaded)

    @Slot(str)
    def exploreDemo(self, model: str):
        self._run(
            "device", lambda: self._locked(self._s.attach_demo, model), lambda _: self.refresh_all()
        )

    @Slot(str)
    def switchDemo(self, model: str):
        self.exploreDemo(model)

    @Slot()
    def detach(self):
        self._s.detach()
        self.refresh_all()

    @Slot(str)
    def setMode(self, mode: str):
        self._s.set_mode(mode)
        self.modeChanged.emit()
        self._refresh_roster()
        self._refresh_workshops()
        self.distChanged.emit()

    @Slot(str)
    def setDeviceName(self, name: str):
        try:
            self._s.set_device_name(name)
            self._device_name = self._s.device_name()
        except Exception as exc:
            self.toast.emit(str(exc), True)
            return
        self.identityChanged.emit()
        self._refresh_roster()

    # -- firmware ---------------------------------------------------------------------
    @Slot(str)
    def setChannel(self, channel: str):
        self._s.channel = channel
        self._refresh_catalog()

    @Slot(str, bool, bool)
    def installFirmware(self, version: str, from_cache: bool, download: bool):
        def progress(phase: str, done: int, total: int) -> None:
            # Emitted from the worker thread; Qt queues the change onto the GUI thread.
            self._set_progress(done / total if total else -1.0, phase)

        self._run(
            "firmware",
            lambda: self._locked(
                self._s.install_firmware,
                version,
                from_cache=from_cache,
                download=download,
                channel=self._s.channel,
                progress=progress,
            ),
            self._installed,
        )

    @Slot()
    def updateCaches(self):
        self._run(
            "cache",
            lambda: self._locked(self._s.preload_all),
            self._caches_updated,
        )

    # -- account ----------------------------------------------------------------------
    @Slot(str)
    def loginToken(self, token: str):
        self._run(
            "auth",
            lambda: self._s.login_token(token),
            self._signed_in,
        )

    @Slot(str, str)
    def loginPassword(self, email: str, password: str):
        # The password buys a token once and is never stored (Session's contract).
        self._run(
            "auth",
            lambda: self._s.login_password(email, password),
            self._signed_in,
        )

    @Slot()
    def logout(self):
        try:
            self._s.logout()
        except Exception as exc:
            self.toast.emit(str(exc), True)
            return
        self.refresh_auth()
        self.toast.emit("auth_gone", False)

    # -- workshops --------------------------------------------------------------------
    @Slot(str, str)
    def stageAdd(self, kind: str, name: str):
        shop = self._shops.get(kind)
        entry = shop.entry(name) if shop else None
        if shop is None or entry is None:
            return
        if not shop.stage.add(name, entry.get("size") or 0, entry):
            self.toast.emit("already_staged", True)
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

    @Slot(str)
    def stageMinimize(self, kind: str):
        self._edit_stage(kind, lambda shop: shop.stage.minimize())

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
            self.toast.emit(f"bad_ext::{wanted}", True)
            return
        data = path.read_bytes()
        entry: dict[str, Any] = {"source": "local", "origin": "local", "path": str(path)}
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
            self.toast.emit("already_staged", True)

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
            with self._s._io_lock:
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

        self._run(
            f"write:{kind}",
            work,
            self._written,
        )

    @Slot(str, str, QUrl)
    def exportItem(self, kind: str, name: str, folder: QUrl):
        target = Path(folder.toLocalFile()) if folder.isValid() else Path.home() / "Downloads"

        def work():
            with self._s._io_lock:
                result = self._s.export_app(name) if kind == "apps" else self._s.export_script(name)
            if "data_b64" in result:
                raw = base64.b64decode(result["data_b64"])
            else:
                raw = (result.get("code") or "").encode("utf-8")
            suffix = ".nwa" if kind == "apps" else ".py"
            out = target / (result.get("filename") or f"{name}{suffix}")
            out.write_bytes(raw)
            return {"path": str(out)}

        self._run("export", work, lambda r: self.toast.emit(f"export_ok::{r['path']}", False))

    # -- roster -----------------------------------------------------------------------
    @Property(str, notify=rosterChanged)
    def parcClass(self) -> str:
        return self._parc_class

    @Property(str, notify=rosterChanged)
    def parcFilter(self) -> str:
        return self._parc_filter

    def class_names(self) -> list[str]:
        return [str(c) for c in (self._roster.get("classes") or [])]

    @Property("QVariantList", notify=rosterChanged)  # type: ignore[arg-type]
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
        self._refresh_roster()
        self.distChanged.emit()

    @Slot(str)
    def setFilter(self, text: str):
        if text != self._parc_filter:
            self._parc_filter = text
            self._refresh_roster()

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
            self._refresh_roster()
            self.distChanged.emit()

    # -- distribution -----------------------------------------------------------------
    def distribution_view(self) -> dict:
        return R.distribution_view(self._roster, self._parc_class)

    @Property("QVariantMap", notify=distChanged)  # type: ignore[arg-type]
    def distribution(self) -> dict:
        return self.distribution_view()

    @Property("QVariantList", notify=distChanged)  # type: ignore[arg-type]
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
            self.toast.emit(str(exc), True)
            return
        self._refresh_roster()
        self.distChanged.emit()

    # -- batch kiosk ------------------------------------------------------------------
    @Property("QVariantMap", notify=batchChanged)  # type: ignore[arg-type]
    def batch(self) -> dict:
        return self._batch

    @Slot(result=bool)
    def armBatch(self) -> bool:
        """Arm the kiosk for the selected class, falling back to the first real class."""
        class_id = self._parc_class
        if class_id in (R.CLASS_ALL, R.CLASS_UNFILED):
            names = self.class_names()
            if not names:
                self.toast.emit("batch_need_class", True)
                return False
            class_id = names[0]
            self._parc_class = class_id
            self._refresh_roster()
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
                self.toast.emit(error, True)
            else:
                self._refresh_roster()

        self._set_busy("batch")
        self._jobs.submit(
            lambda: self._locked(self._s.batch_run, class_id),
            lambda entry: finish(entry, None),
            lambda message: finish(None, message),
        )

    @Slot(str)
    def batchSimulate(self, model: str):
        """Attach a demo device and run the SAME chain — testable without hardware."""
        if self._batch["armed"]:
            self._run(
                "device",
                lambda: self._locked(self._s.attach_demo, model),
                self._demo_attached_for_batch,
            )

    # -- app --------------------------------------------------------------------------
    @Slot()
    def quit(self):
        self.quitRequested.emit()

    def shutdown(self) -> None:
        """Stop watching the USB port and release the device.

        Without this a backend outlives its window: the hot-plug timer keeps firing against a
        session that is on its way out, which is harmless in production but crashes as soon as
        two backends exist in one process (tests do exactly that).
        """
        self._timer.stop()
        try:
            self._s.detach()
        except Exception:
            pass


__all__ = ["Backend", "fmt_bytes"]

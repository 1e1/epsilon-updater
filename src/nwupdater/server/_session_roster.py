"""Classroom roster (local fleet register) for a session — read view + upsert-on-scan.

Extends the name-store foundation (see :mod:`nwupdater.classroom_roster`): the roster keys on the
same ``model:serial`` and joins the display name at read time. Enrolment is a SIDE EFFECT of a
successful scan, not a public endpoint — :meth:`roster_upsert_current` runs from the attach path
(``SessionBase._after_scan``) whenever the classroom policy is active.
"""

from __future__ import annotations

from ._session_base import SessionBase


class RosterMixin(SessionBase):
    # -- upsert-on-scan (side effect of attach_real / attach_demo) ------------------
    def _after_scan(self) -> None:
        """Post-attach hook (overrides the SessionBase no-op): enrol the scanned calculator in the
        local roster under classroom policy. Best-effort — a roster hiccup never breaks attach."""
        try:
            self.roster_upsert_current()
        except Exception:
            pass

    def roster_upsert_current(self) -> bool:
        """Enrol/refresh the connected calculator in the roster (classroom policy only). Returns
        ``True`` iff the store was written. Idempotent, so demo/virtual re-attaches and the health
        poll never thrash ``last_scan``."""
        if not self.policy.classroom:
            return False
        try:
            i = self._identity()
        except Exception:
            return False
        serial = (i.serial_number or "").strip()
        if not serial:
            return False  # no serial exposed → nothing to enrol
        from ..classroom_roster import upsert_on_scan

        return upsert_on_scan(i.model_name or "", serial, firmware=i.os_version, family=i.family)

    # -- UX mode → capability policy (POST /api/mode) ------------------------------
    def set_mode(self, mode: str) -> dict:
        """Set the session's UX policy from the UI mode toggle (``"classroom"`` vs anything else).

        The roster only enrols under classroom policy, so this is what makes a UI scan populate the
        Parc. Switching INTO classroom also enrols the currently-connected calculator right away
        (idempotent) — the Parc then reflects the plugged-in device without waiting for a re-scan."""
        from ..capabilities import Policy

        classroom = mode == "classroom"
        self.policy = Policy(classroom=classroom)
        if classroom and self.connected:
            try:
                self.roster_upsert_current()
            except Exception:
                pass  # best-effort: a roster hiccup never breaks the mode toggle
        return {"ok": True, "classroom": classroom}

    # -- read view (GET /api/roster) -----------------------------------------------
    def roster(self) -> dict:
        """The whole roster grouped for the UI: the sorted class list (+ counts and a synthetic
        "unfiled" bucket count), and every calculator joined with its name and an "up to date at
        last scan" flag. The serial stays inside the internal ``key`` and is never a display
        field — the UI must not render it."""
        from .. import classroom_roster as R

        entries = R.all_entries()
        calculators: list[dict] = []
        counts: dict[str, int] = {}
        unfiled = 0
        for e in entries:
            raw = e["class"]
            cls = str(raw) if raw else None
            if cls:
                counts[cls] = counts.get(cls, 0) + 1
            else:
                unfiled += 1
            calculators.append(
                {
                    # internal id (model:serial) — kept for later phases (actions), NEVER shown
                    "key": e["key"],
                    "name": e["name"],
                    "default": e["default"],
                    "model": e["known_model"],
                    "family": e["known_family"],
                    "class": cls,
                    "known_firmware": e["known_firmware"],
                    "up_to_date": self._roster_up_to_date(e["known_family"], e["known_firmware"]),
                    "last_scan": e["last_scan"],
                    # Per-action outcome of the last distribution pass (None until a batch runs).
                    "last_dist": e.get("last_dist"),
                }
            )
        referenced = {str(e["class"]) for e in entries if e["class"]}
        classes = sorted(set(R.all_classes()) | referenced, key=lambda s: s.lower())
        for c in classes:
            counts.setdefault(c, 0)
        calculators.sort(key=lambda c: (c["name"] or c["default"] or "").lower())
        # Per-class distribution config (every class defaulted) + the device-independent name pools
        # the Distribution panels pick from (app/script catalogue), so the UI works with no device.
        # ONE read for the whole map: a per-class R.distribution() call re-parses the register
        # every time, which the native UI's roster refresh pays on the keystroke path.
        stored = R.all_distributions()
        distributions = {c: stored.get(c) or R.default_distribution() for c in classes}
        return {
            "schema": R.SCHEMA,
            "classes": classes,
            "counts": counts,
            "unfiled_count": unfiled,
            "total": len(calculators),
            "calculators": calculators,
            "distributions": distributions,
            "dist_apps": self._dist_app_names(),
            "dist_scripts": self._dist_script_names(),
        }

    def _dist_app_names(self) -> list[str]:
        """Distinct app names available to a class distribution (catalogue + local), device-free."""
        return sorted({e.name for e in self.store.entries if e.name})

    def _dist_script_names(self) -> list[str]:
        """Distinct script names available to a class distribution, device-free. ``_scripts_available``
        lives on the sibling ScriptsMixin (composed into the full Session)."""
        avail = getattr(self, "_scripts_available", None)
        if not callable(avail):
            return []
        try:
            return sorted({str(s.get("name", "")) for s in avail() if s.get("name")})
        except Exception:
            return []

    def roster_dist_set(self, class_name: str, config: dict) -> dict:
        """Persist a class's distribution config (action chain, onboarding rule, app/script sets)."""
        from .. import classroom_roster as R

        return {
            "ok": True,
            "class": class_name,
            "distribution": R.set_distribution(class_name, config),
        }

    # -- mutations (POST /api/roster/*) --------------------------------------------
    def roster_rename(self, key: str, name: str) -> dict:
        """Rename a calculator by its ``model:serial`` key. Delegates to the SHARED name store
        (:func:`device_names.set_name`) so the new name follows the calculator in both modes; an
        empty name clears the override (display falls back to the default)."""
        from .. import device_names

        model, _, serial = (key or "").partition(":")
        stored = device_names.set_name(model, serial, name)
        return {"ok": True, "key": key, "name": stored}

    def roster_move(self, keys: list[str], class_name: str | None) -> dict:
        """File one or more calculators into ``class_name`` (``None`` → "Sans classe")."""
        from .. import classroom_roster as R

        return {"ok": True, "moved": R.move(keys or [], class_name)}

    def roster_delete(self, keys: list[str]) -> dict:
        """Remove one or more calculator records (a re-scan re-creates them)."""
        from .. import classroom_roster as R

        return {"ok": True, "deleted": R.delete(keys or [])}

    def roster_class_create(self, name: str) -> dict:
        """Create a class (an empty class may exist)."""
        from .. import classroom_roster as R

        return {"ok": True, "classes": R.create_class(name)}

    def roster_class_rename(self, old: str, new: str) -> dict:
        """Rename a class and re-file its members (merges into an existing target)."""
        from .. import classroom_roster as R

        return {"ok": True, "classes": R.rename_class(old, new)}

    def roster_class_delete(self, name: str, mode: str | None = None) -> dict:
        """Delete a class. A non-empty class needs an explicit ``mode`` (``"move"`` → its members
        fall back to "Sans classe"; ``"purge"`` → its members are deleted); without one it returns
        ``{needs_confirm, count}`` so the UI can offer the two choices."""
        from .. import classroom_roster as R

        return R.delete_class(name, mode=mode)

    def _roster_up_to_date(self, family: str | None, firmware: str | None) -> bool | None:
        """``True``/``False`` if ``firmware`` matches / is behind the latest for its family (the
        bundled snapshot), ``None`` when either is unknown. Labelled "up to date at last scan" in
        the UI — it compares the firmware SEEN at the last scan, not a live device state."""
        if not firmware or not family:
            return None
        from ..catalog import version as V

        latest = self._catalog_for(family).latest()
        if latest is None:
            return None
        return not V.is_newer(latest.version, firmware)

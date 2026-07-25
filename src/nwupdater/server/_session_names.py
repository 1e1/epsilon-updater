"""User-assigned calculator names (local store, keyed by model + serial) for a session."""

from __future__ import annotations

from ._session_base import SessionBase


class NamesMixin(SessionBase):
    def _name_identity(self) -> tuple[str, str, str]:
        """``(model, serial, default_display)`` for the connected device."""
        i = self._identity()
        model = i.model_name or ""
        serial = i.serial_number or ""
        default = f"calc {model.upper()}" if model else "calc"
        return model, serial, default

    def device_name(self) -> dict:
        """The stored name (or ``None``) for the connected calculator + the default display."""
        from ..device_names import get_name

        model, serial, default = self._name_identity()
        return {
            "model": model,
            "serial": serial,
            "name": get_name(model, serial),
            "default": default,
        }

    def set_device_name(self, name: str) -> dict:
        """Persist a user name for the connected calculator (empty clears it). Keyed locally by
        model + serial. Cloud sync to the NumWorks account is DEFERRED — local naming stands on
        its own."""
        from ..device_names import set_name

        model, serial, default = self._name_identity()
        # TODO(cloud-sync): when signed in (Individual mode), also register/rename this calculator
        # on the NumWorks account so the name follows it across machines. Deferred: the naming API
        # is not reverse-engineered here, and local naming must (and does) work without it.
        saved = set_name(model, serial, name)
        return {"ok": True, "model": model, "serial": serial, "name": saved, "default": default}

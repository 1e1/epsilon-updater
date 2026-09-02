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
        """The stored name (or ``None``) for the connected calculator + the default display.

        A disconnected calculator is a normal state, not a server error: this mirrors
        :meth:`SessionBase.identity`, which reports ``connected: False`` rather than raising.
        Without that symmetry the UI's own reads race any detach — a read still in flight when
        the device goes away came back as a 500 in the page's console.
        """
        from ..device_names import get_name

        if not self.connected:
            return {"model": "", "serial": "", "name": None, "default": "calc"}
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
        # TODO(cloud-sync): when signed in (Individual mode), also mirror this name to the NumWorks
        # account so it follows the calculator across machines. DEFERRED by product decision — the
        # flow IS reverse-engineered now (Rails form + CSRF; serial_cloud = hex(base64decode(serial));
        # POST /devices/names create vs POST /devices/names/<slug> edit) and documented in
        # docs/01-specs/scripts-and-device-pairing.md. Local naming stands on its own meanwhile.
        saved = set_name(model, serial, name)
        return {"ok": True, "model": model, "serial": serial, "name": saved, "default": default}

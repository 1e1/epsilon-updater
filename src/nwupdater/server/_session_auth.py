"""my.numworks.com authentication + the read-only capture harness for a session."""

from __future__ import annotations

from ._session_base import SessionBase


class AuthMixin(SessionBase):
    def auth_status(self) -> dict:
        from ..catalog import auth as A

        a = A.load_auth()
        if a is None:
            return {"authenticated": False, "expired": False, "expires_at": None}
        return {
            "authenticated": not a.is_expired(),
            "expired": a.is_expired(),
            "expires_at": (a.expires_at.date().isoformat() if a.expires_at else None),
        }

    def login_token(self, token: str) -> dict:
        """Store a remember_user_token pasted by the user (Mi Unlock style)."""
        from ..catalog import auth as A

        a = A.Auth((token or "").strip())
        if not a.remember_token:
            raise ValueError("empty token")
        A.save_auth(a)
        return self.auth_status()

    def login_password(self, email: str, password: str) -> dict:
        """Built-in Devise login; only the token is kept, never the password."""
        from ..catalog import auth as A

        a = A.login_with_password(email, password)
        A.save_auth(a)
        return self.auth_status()

    def logout(self) -> dict:
        from ..catalog import auth as A

        A.clear_auth()
        return {"authenticated": False, "expired": False, "expires_at": None}

    def _serial(self) -> str | None:
        """Serial number via a standard string-descriptor read (works virtual + real)."""
        from ..dfu import constants as C

        return self._conn()[0].get_string_descriptor(C.SERIAL_STRING_INDEX)

    def capture_sequence(
        self, *, timestamp: str, transport=None, model: str | None = None, channel: str = "stable"
    ) -> dict:
        """Bespoke capture: USB + WEB dialogue for the scenario, WITHOUT flashing.

        Requires a signed-in account. The web side always hits the real server (that is what
        we want to capture); ``transport`` is injectable for tests only."""
        import time as _t

        from ..capture_session import run_capture
        from ..catalog import auth as A

        a = A.load_auth()
        if a is None or a.is_expired():
            raise ValueError("authentication required — sign in first")
        tr = transport if transport is not None else A.UrllibTransport()
        return run_capture(
            self.device,
            auth=a,
            transport=tr,
            interface=getattr(self.client, "interface", 0),
            bcd_device=self.bcd,
            model=model or (self.model.name if self.model else "n0200"),
            channel=channel,
            sleep=(lambda *_: None) if self.virtual else _t.sleep,
            timestamp=timestamp,
            serial=self._serial(),
        )

    # -- firmware cache (classroom mode) -------------------------------------------

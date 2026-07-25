"""Authentication against ``my.numworks.com`` to download firmwares.

The official binaries (``/firmwares/{model}/{stable|beta}.dfu``) are behind authentication:
anonymously the server replies **401**. The portal uses Devise (Rails); there is NO OAuth. So we
reproduce a **bring-your-own-token** model: the user authenticates once and we keep ONLY the
``remember_user_token`` cookie (a signed Rails token, valid ~3 years) — never the password.

Two ways to obtain that token:
  - ``login_with_password(email, password)``: replay the Devise login and read back the
    ``remember_user_token`` returned in ``Set-Cookie`` (the password is never stored).
  - ``Auth(token)``: the user pastes the value of the ``remember_user_token`` cookie themselves
    (copied from the browser DevTools; it is an ``HttpOnly`` cookie).

No USB access here — only HTTP networking, injected through a ``Transport`` so this stays
testable offline.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://my.numworks.com"
SIGNIN_URL = f"{BASE}/users/sign_in"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REMEMBER_COOKIE = "remember_user_token"
REMEMBER_PURPOSE = "cookie.remember_user_token"


class AuthError(Exception):
    """Login refused (invalid credentials) or a token that is missing/unreadable."""


class TransportError(Exception):
    """Network/TLS failure (DNS, connection, certificate…)."""


# -- transport (injectable for tests) --------------------------------------------------
@dataclass
class Response:
    status: int
    headers: list[tuple[str, str]]  # multi-values preserved (Set-Cookie)
    body: bytes

    def header(self, name: str) -> str | None:
        low = name.lower()
        return next((v for k, v in self.headers if k.lower() == low), None)

    def set_cookies(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in self.headers:
            if k.lower() == "set-cookie":
                kv = v.split(";", 1)[0].strip()
                if "=" in kv:
                    name, _, val = kv.partition("=")
                    out[name.strip()] = val.strip()
        return out


def _ssl_context():
    """Verifying TLS context. Uses the ``certifi`` bundle when present (useful on Python builds
    without system CAs, e.g. python.org on macOS)."""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # do not follow: we want to read the Set-Cookie headers
        return None


class _StripCrossHostAuth(urllib.request.HTTPRedirectHandler):
    """Redirect handler that DROPS the ``Cookie``/``Authorization`` headers when a redirect
    crosses to a different host.

    urllib forwards request headers verbatim to the redirect target, so the default behaviour
    would hand our bring-your-own-token secret to whatever host ``Location`` points at. We keep
    the headers on a same-host redirect (e.g. my.numworks.com -> my.numworks.com) but strip them
    the moment the hostname changes (e.g. a CDN or an attacker-controlled ``Location``)."""

    _SENSITIVE = ("cookie", "authorization")

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _hostname(req.full_url) != _hostname(newurl):
            for key in [k for k in new.headers if k.lower() in self._SENSITIVE]:
                del new.headers[key]
        return new


def _hostname(url: str) -> str | None:
    return urllib.parse.urlsplit(url).hostname


class UrllibTransport:
    """Real network transport. Never used in the tests."""

    def open(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        data=None,
        timeout: float = 20.0,
        allow_redirects: bool = False,
    ) -> Response:
        import urllib.error

        https = urllib.request.HTTPSHandler(context=_ssl_context())
        handlers = [https, _StripCrossHostAuth()] if allow_redirects else [https, _NoRedirect()]
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            r = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:  # 3xx (no-redirect), 401, 4xx… stay usable
            r = e
        except urllib.error.URLError as e:  # DNS, connection, TLS…
            reason = getattr(e, "reason", e)
            raise TransportError(f"cannot connect to {url}: {reason}") from e
        status = getattr(r, "status", None) or r.getcode()
        return Response(status, list(r.headers.items()), r.read())


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


# -- extraction / decoding (pure, testable) --------------------------------------------
def extract_csrf(html: str) -> str | None:
    """The Rails anti-CSRF token, from the form's hidden field (or the <meta> tag)."""
    for pat in (
        r'name="authenticity_token"[^>]*\svalue="([^"]+)"',
        r'value="([^"]+)"[^>]*\sname="authenticity_token"',
        r'name="csrf-token"[^>]*\scontent="([^"]+)"',
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def decode_remember_token(token: str) -> dict:
    """Decode the (unverified) payload of the Rails token: ``exp`` and ``purpose``."""
    raw = urllib.parse.unquote(token)
    payload_b64 = raw.split("--", 1)[0]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        outer = json.loads(base64.b64decode(payload_b64))
        rails = outer.get("_rails", {})
    except Exception as exc:  # malformed token
        raise AuthError(f"unreadable token: {exc}") from exc
    exp = rails.get("exp")
    expires_at = None
    if isinstance(exp, str):
        try:
            expires_at = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        except ValueError:
            expires_at = None
    return {
        "purpose": rails.get("pur"),
        "expires_at": expires_at,
        "looks_valid": rails.get("pur") == REMEMBER_PURPOSE,
    }


# -- the auth object -------------------------------------------------------------------
@dataclass
class Auth:
    remember_token: str

    def cookie_header(self) -> str:
        return f"{REMEMBER_COOKIE}={self.remember_token}"

    def info(self) -> dict:
        return decode_remember_token(self.remember_token)

    @property
    def expires_at(self) -> datetime | None:
        return self.info().get("expires_at")

    def is_expired(self, *, now: datetime | None = None) -> bool:
        exp = self.expires_at
        if exp is None:
            return False  # no readable exp → let the server decide (401)
        now = now or datetime.now(timezone.utc)
        return now >= exp

    def summary(self) -> str:
        exp = self.expires_at
        when = exp.date().isoformat() if exp else "?"
        state = "EXPIRED" if self.is_expired() else f"expires on {when}"
        return f"remember_user_token ({state})"


# -- Devise login ----------------------------------------------------------------------
def login_with_password(email: str, password: str, *, transport=None) -> Auth:
    """Replay the Devise login and return an ``Auth`` (the password is never kept)."""
    tr = transport or UrllibTransport()
    # 1. GET the login page: CSRF token + session cookie (both required to validate the POST).
    get = tr.open("GET", SIGNIN_URL, headers={"User-Agent": UA})
    csrf = extract_csrf(get.body.decode("utf-8", "replace"))
    if not csrf:
        raise AuthError("CSRF token not found on the sign-in page")
    cookies = get.set_cookies()
    # 2. POST the credentials (with "remember me" to obtain the long-lived token).
    form = urllib.parse.urlencode(
        {
            "utf8": "✓",
            "authenticity_token": csrf,
            "user[email]": email,
            "user[password]": password,
            "user[remember_me]": "1",
            "commit": "Log in",
        }
    ).encode("utf-8")
    post = tr.open(
        "POST",
        SIGNIN_URL,
        data=form,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": _cookie_header(cookies),
        },
    )
    token = post.set_cookies().get(REMEMBER_COOKIE)
    if not token:
        # Devise re-renders the page (200/422) without a token when the credentials are wrong.
        raise AuthError("credentials rejected (no token returned) — check email/password")
    return Auth(token)


# -- local token storage (treated as a secret) -----------------------------------------
def config_path() -> Path:
    base = (
        os.environ.get("NWUPDATER_CONFIG_DIR")
        or os.environ.get("XDG_CONFIG_HOME")
        or os.path.join(os.path.expanduser("~"), ".config")
    )
    return Path(base) / "nwupdater" / "credentials.json"


def save_auth(auth: Auth, *, path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    info = auth.info()
    exp = info.get("expires_at")
    data = {
        "remember_user_token": auth.remember_token,
        "expires_at": exp.isoformat() if exp else None,
    }
    # Create/truncate directly at 0600: the secret is never readable by others, not even for the
    # duration of a write_text() (which would go through the umask, then chmod).
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(p, 0o600)  # tighten if the file pre-existed with wider permissions
    except OSError:
        pass
    return p


def load_auth(*, path: Path | None = None) -> Auth | None:
    p = path or config_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    token = data.get("remember_user_token")
    return Auth(token) if token else None


def clear_auth(*, path: Path | None = None) -> bool:
    p = path or config_path()
    if p.is_file():
        p.unlink()
        return True
    return False

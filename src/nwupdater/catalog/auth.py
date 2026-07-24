"""Authentification auprès de ``my.numworks.com`` pour télécharger les firmwares.

Les binaires officiels (``/firmwares/{model}/{stable|beta}.dfu``) sont derrière une
authentification : en anonyme le serveur répond **401**. Le portail utilise Devise (Rails),
il n'y a PAS d'OAuth. On reproduit donc, façon « Mi Unlock », un modèle **bring-your-own-
token** : l'utilisateur s'authentifie une fois et on ne conserve QUE le cookie
``remember_user_token`` (jeton signé Rails, valable ~3 ans) — jamais le mot de passe.

Deux façons d'obtenir ce jeton :
  - ``login_with_password(email, password)`` : on joue le login Devise et on récupère le
    ``remember_user_token`` renvoyé en ``Set-Cookie`` (le mot de passe n'est jamais stocké).
  - ``Auth(token)`` : l'utilisateur colle lui-même la valeur du cookie
    ``remember_user_token`` (copiée depuis les DevTools du navigateur, cookie ``HttpOnly``).

Aucun accès USB ici — uniquement du réseau HTTP, injecté via un ``Transport`` pour rester
testable hors-ligne.
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
    """Login refusé (identifiants invalides) ou jeton absent/illisible."""


class TransportError(Exception):
    """Échec réseau/TLS (DNS, connexion, certificat…)."""


# -- transport (injectable pour les tests) ---------------------------------------------
@dataclass
class Response:
    status: int
    headers: list[tuple[str, str]]  # multi-valeurs préservées (Set-Cookie)
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
    """Contexte TLS avec vérification. Utilise le bundle ``certifi`` s'il est présent
    (utile sur les builds Python sans CA système, ex. python.org sur macOS)."""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # ne pas suivre : on veut lire les Set-Cookie
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
    """Transport réseau réel. N'est jamais utilisé dans les tests."""

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
        except urllib.error.HTTPError as e:  # 3xx (no-redirect), 401, 4xx… restent exploitables
            r = e
        except urllib.error.URLError as e:  # DNS, connexion, TLS…
            reason = getattr(e, "reason", e)
            raise TransportError(f"cannot connect to {url}: {reason}") from e
        status = getattr(r, "status", None) or r.getcode()
        return Response(status, list(r.headers.items()), r.read())


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


# -- extraction / décodage (pur, testable) ---------------------------------------------
def extract_csrf(html: str) -> str | None:
    """Le jeton anti-CSRF Rails, depuis le champ caché du formulaire (ou le <meta>)."""
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
    """Décode la charge utile (non vérifiée) du jeton Rails : ``exp`` et ``purpose``."""
    raw = urllib.parse.unquote(token)
    payload_b64 = raw.split("--", 1)[0]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        outer = json.loads(base64.b64decode(payload_b64))
        rails = outer.get("_rails", {})
    except Exception as exc:  # jeton malformé
        raise AuthError(f"jeton illisible : {exc}") from exc
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


# -- l'objet d'auth --------------------------------------------------------------------
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
            return False  # pas d'exp lisible → on laisse le serveur trancher (401)
        now = now or datetime.now(timezone.utc)
        return now >= exp

    def summary(self) -> str:
        exp = self.expires_at
        when = exp.date().isoformat() if exp else "?"
        state = "EXPIRED" if self.is_expired() else f"expires on {when}"
        return f"remember_user_token ({state})"


# -- login Devise ----------------------------------------------------------------------
def login_with_password(email: str, password: str, *, transport=None) -> Auth:
    """Joue le login Devise et renvoie un ``Auth`` (le mot de passe n'est jamais conservé)."""
    tr = transport or UrllibTransport()
    # 1. GET la page de login : jeton CSRF + cookie de session (requis pour valider le POST).
    get = tr.open("GET", SIGNIN_URL, headers={"User-Agent": UA})
    csrf = extract_csrf(get.body.decode("utf-8", "replace"))
    if not csrf:
        raise AuthError("jeton CSRF introuvable sur la page de connexion")
    cookies = get.set_cookies()
    # 2. POST des identifiants (avec « se souvenir de moi » pour obtenir le jeton longue durée).
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
        # Devise ré-affiche la page (200/422) sans jeton quand les identifiants sont mauvais.
        raise AuthError("credentials rejected (no token returned) — check email/password")
    return Auth(token)


# -- stockage local du jeton (traité comme un secret) ----------------------------------
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
    # Créer/tronquer directement en 0600 : le secret n'est jamais lisible par autrui, même
    # pas le temps d'un write_text() (qui passerait par le umask puis chmod).
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(p, 0o600)  # resserre si le fichier préexistait avec des droits plus larges
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

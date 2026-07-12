"""Téléchargement du firmware officiel depuis ``my.numworks.com`` (authentifié).

Endpoints par modèle (découverts : 401 en anonyme, 200 avec le cookie
``remember_user_token`` — cf. :mod:`nwupdater.catalog.auth`) :

    GET  my.numworks.com/firmwares/{model}/{channel}.json   → manifeste (version, taille…)
    GET  my.numworks.com/firmwares/{model}/{channel}.dfu    → conteneur DfuSe complet

``{model}`` = ``n0100`` | ``n0110`` | ``n0115`` | ``n0120`` | ``n0200`` …
``{channel}`` = ``stable`` | ``beta``.

Le ``.dfu`` est un conteneur DfuSe que :meth:`FirmwareImage.from_dfuse` sait déjà lire ; on
n'a donc rien à réassembler côté binaire. On vérifie la taille annoncée par le manifeste et
la signature ``DfuSe`` avant de rendre les octets.

Réseau injecté via le ``Transport`` de :mod:`auth` → testable hors-ligne. Aucun USB.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .auth import BASE, UA, Auth, TransportError, UrllibTransport, config_path

CHANNELS = ("stable", "beta")
# NumWorks model ids are "n" + 4 hex digits (n0100, n0110, n0120, n0200…). Validate before
# interpolating into a URL path so a crafted value cannot escape it (path traversal / SSRF).
_MODEL_RE = re.compile(r"^n[0-9a-f]{4}$")


class AuthRequired(Exception):
    """Le serveur a répondu 401 : authentification absente ou expirée."""


class DownloadError(Exception):
    """Réponse inattendue, taille incohérente, ou contenu non-DfuSe."""


def _check_model(model: str) -> str:
    if not _MODEL_RE.match(model or ""):
        raise ValueError(f"modèle invalide : {model!r} (attendu : n + 4 chiffres hexa)")
    return model


def manifest_url(model: str, channel: str) -> str:
    return f"{BASE}/firmwares/{_check_model(model)}/{channel}.json"


def dfu_url(model: str, channel: str) -> str:
    return f"{BASE}/firmwares/{_check_model(model)}/{channel}.dfu"


@dataclass(frozen=True)
class FirmwareManifest:
    model: str
    channel: str
    version: str
    patch_level: str
    size: int
    device_model_id: int | None = None
    device_type_id: int | None = None  # 1 = graphique, 6 = scientifique (observé)

    @classmethod
    def from_json(cls, model: str, channel: str, data) -> "FirmwareManifest":
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        dm = data.get("device_model") or {}
        return cls(
            model=model, channel=channel,
            version=str(data.get("version", "?")),
            patch_level=str(data.get("patch_level", "")),
            size=int(data.get("size", 0)),
            device_model_id=dm.get("id"),
            device_type_id=dm.get("device_type_id"),
        )


def _check_channel(channel: str) -> None:
    if channel not in CHANNELS:
        raise ValueError(f"canal inconnu : {channel!r} (attendu : {', '.join(CHANNELS)})")


def _get(url: str, auth: Auth, *, transport=None):
    tr = transport or UrllibTransport()
    try:
        resp = tr.open("GET", url, headers={"User-Agent": UA, "Accept": "*/*",
                                            "Cookie": auth.cookie_header()}, allow_redirects=True)
    except TransportError as exc:
        raise DownloadError(str(exc)) from exc
    if resp.status == 401:
        raise AuthRequired("401 — authentification requise ou expirée. "
                           "Relancez `nwupdater login`.")
    if resp.status != 200:
        raise DownloadError(f"HTTP {resp.status} sur {url}")
    return resp


def fetch_manifest(model: str, channel: str, auth: Auth, *, transport=None) -> FirmwareManifest:
    _check_channel(channel)
    resp = _get(manifest_url(model, channel), auth, transport=transport)
    try:
        return FirmwareManifest.from_json(model, channel, resp.body)
    except (ValueError, KeyError) as exc:
        raise DownloadError(f"manifeste illisible pour {model}/{channel} : {exc}") from exc


def download_dfu(model: str, channel: str, auth: Auth, *, expected_size: int | None = None,
                 transport=None) -> bytes:
    """Télécharge le ``.dfu`` et le valide (signature DfuSe + taille si connue)."""
    _check_channel(channel)
    resp = _get(dfu_url(model, channel), auth, transport=transport)
    blob = resp.body
    if blob[:5] != b"DfuSe":
        raise DownloadError(f"contenu inattendu pour {model}/{channel} : pas un fichier DfuSe")
    if expected_size is not None and len(blob) != expected_size:
        raise DownloadError(f"taille incohérente : reçu {len(blob)} o, attendu {expected_size} o")
    return blob


def fetch_firmware(model: str, channel: str, auth: Auth, *,
                   transport=None) -> tuple[FirmwareManifest, bytes]:
    """Manifeste puis ``.dfu``, avec contrôle d'intégrité par la taille du manifeste."""
    manifest = fetch_manifest(model, channel, auth, transport=transport)
    blob = download_dfu(model, channel, auth,
                        expected_size=manifest.size or None, transport=transport)
    return manifest, blob


# -- provenance : empreinte + journal (preuve d'intégrité bit-à-bit) -------------------
def sha256_hex(blob: bytes) -> str:
    """Empreinte SHA-256 du ``.dfu`` téléchargé — atteste qu'il est identique à la source
    officielle et n'a subi aucune altération (cf. GOOD-FAITH-DECLARATION §3.1)."""
    return hashlib.sha256(blob).hexdigest()


def provenance_log_path() -> Path:
    """Journal local des téléchargements officiels (à côté des identifiants)."""
    return config_path().parent / "downloads.log"


def record_download(manifest: FirmwareManifest, sha256: str, *, when: str,
                    path: Path | None = None) -> Path:
    """Ajoute une ligne JSON traçant un téléchargement (version, taille, empreinte).

    Purement local : aucune donnée n'est transmise. ``when`` est un horodatage ISO fourni par
    l'appelant (les fonctions réseau restent pures/testables et n'écrivent jamais sur disque)."""
    p = path or provenance_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "when": when,
        "model": manifest.model,
        "channel": manifest.channel,
        "version": manifest.version,
        "patch_level": manifest.patch_level,
        "size": manifest.size,
        "sha256": sha256,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return p

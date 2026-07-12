"""Rejoue les fixtures RÉELLES capturées depuis my.numworks.com (voir tests/fixtures/).

Valide que le parsing (CSRF, manifeste) fonctionne sur des payloads authentiques — sans
réseau ni compte. Aucun secret ni firmware n'est versionné (cf. tests/fixtures/README.md).
"""

import base64
import json
from pathlib import Path

from nwupdater.catalog import auth as A
from nwupdater.catalog import download as D
from nwupdater.catalog.auth import Auth, Response

FIX = Path(__file__).parent / "fixtures"


def _auth():
    payload = {"_rails": {"exp": "2099-01-01T00:00:00Z", "pur": A.REMEMBER_PURPOSE}}
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    return Auth(f"{b64}--sig")


class _Replay:
    """Transport rejouant une réponse enregistrée pour une URL donnée."""
    def __init__(self, url, body, status=200):
        self._url, self._body, self._status = url, body, status

    def open(self, method, url, *, headers=None, data=None, timeout=20.0, allow_redirects=False):
        assert url == self._url, f"URL inattendue : {url}"
        return Response(self._status, [], self._body)


# -- CSRF sur la vraie structure de formulaire -----------------------------------------
def test_extract_csrf_from_real_signin_form():
    html = (FIX / "signin_form.html").read_text(encoding="utf-8")
    assert "authenticity_token" in html
    assert A.extract_csrf(html) == "REDACTED_CSRF_TOKEN"


# -- manifestes réels : parsing + valeurs attendues ------------------------------------
def test_real_manifest_n0110_graphing():
    raw = (FIX / "manifest_n0110_stable.json").read_bytes()
    m = D.FirmwareManifest.from_json("n0110", "stable", raw)
    assert m.version == "25.2.0"
    assert m.patch_level == "43f67db"
    assert m.size == 3191133
    assert m.device_type_id == 1  # 1 = graphique


def test_real_manifest_n0200_scientific():
    raw = (FIX / "manifest_n0200_stable.json").read_bytes()
    m = D.FirmwareManifest.from_json("n0200", "stable", raw)
    assert m.version == "3.0.0"          # Scientifique « Version 3 »
    assert m.size == 237606
    assert m.device_type_id == 6         # 6 = scientifique


def test_fetch_manifest_over_replayed_transport():
    raw = (FIX / "manifest_n0110_stable.json").read_bytes()
    tr = _Replay(D.manifest_url("n0110", "stable"), raw)
    m = D.fetch_manifest("n0110", "stable", _auth(), transport=tr)
    assert m.version == "25.2.0" and m.size == 3191133


def test_device_type_ids_are_distinct_per_family():
    g = D.FirmwareManifest.from_json("n0110", "stable",
                                     (FIX / "manifest_n0110_stable.json").read_bytes())
    s = D.FirmwareManifest.from_json("n0200", "stable",
                                     (FIX / "manifest_n0200_stable.json").read_bytes())
    assert g.device_type_id != s.device_type_id

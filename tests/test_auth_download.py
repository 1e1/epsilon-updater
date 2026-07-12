"""Lot 6 — authentification my.numworks.com + téléchargement du .dfu officiel.

Entièrement hors-ligne : le réseau est injecté via un ``FakeTransport``. Aucun USB, aucun
appel réseau réel.
"""

import base64
import json

import pytest

from nwupdater.catalog import auth as A
from nwupdater.catalog import download as D
from nwupdater.catalog.auth import Auth, Response
from nwupdater.install.image import FirmwareImage
from nwupdater.models import MODELS


# -- helpers ---------------------------------------------------------------------------
def make_token(exp_iso="2099-01-01T00:00:00.000Z", purpose=A.REMEMBER_PURPOSE):
    payload = {"_rails": {"message": "W1td", "exp": exp_iso, "pur": purpose}}
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"{b64}--deadbeefsignature"


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes  # {(method, url): Response}
        self.calls = []

    def open(self, method, url, *, headers=None, data=None, timeout=20.0, allow_redirects=False):
        self.calls.append((method, url, headers, data))
        assert (method, url) in self.routes, f"unexpected request {(method, url)}"
        return self.routes[(method, url)]


def dfuse_blob():
    return FirmwareImage.synthetic(MODELS[0x0110], version="25.2.0").to_dfuse()


# -- token decode / Auth ----------------------------------------------------------------
def test_decode_remember_token():
    info = A.decode_remember_token(make_token("2028-07-12T11:12:37.608Z"))
    assert info["purpose"] == A.REMEMBER_PURPOSE
    assert info["looks_valid"] is True
    assert info["expires_at"].year == 2028


def test_auth_expiry_and_cookie_header():
    fresh = Auth(make_token("2099-01-01T00:00:00Z"))
    stale = Auth(make_token("2000-01-01T00:00:00Z"))
    assert fresh.is_expired() is False
    assert stale.is_expired() is True
    assert fresh.cookie_header() == f"remember_user_token={fresh.remember_token}"


def test_decode_bad_token_raises():
    with pytest.raises(A.AuthError):
        A.decode_remember_token("not-base64--sig")


# -- csrf extraction --------------------------------------------------------------------
def test_extract_csrf_from_form_and_meta():
    html = '<form><input type="hidden" name="authenticity_token" value="TOK123" autocomplete="off"></form>'
    assert A.extract_csrf(html) == "TOK123"
    meta = '<meta name="csrf-token" content="METATOK">'
    assert A.extract_csrf(meta) == "METATOK"
    assert A.extract_csrf("<html>nothing</html>") is None


# -- storage ----------------------------------------------------------------------------
def test_save_load_clear_roundtrip(tmp_path):
    p = tmp_path / "creds.json"
    A.save_auth(Auth(make_token()), path=p)
    assert p.is_file()
    assert (p.stat().st_mode & 0o777) == 0o600
    loaded = A.load_auth(path=p)
    assert loaded is not None and loaded.info()["looks_valid"]
    assert A.clear_auth(path=p) is True
    assert A.load_auth(path=p) is None


# -- login Devise (fake transport) -----------------------------------------------------
def test_login_with_password_success():
    token = make_token()
    html = '<input name="authenticity_token" value="CSRF">'.encode()
    routes = {
        ("GET", A.SIGNIN_URL): Response(200, [("Set-Cookie", "_workshop_session=s3ss; path=/; httponly")], html),
        ("POST", A.SIGNIN_URL): Response(302, [("Location", "https://my.numworks.com/"),
                                               ("Set-Cookie", f"remember_user_token={token}; path=/; httponly")], b""),
    }
    tr = FakeTransport(routes)
    auth = A.login_with_password("me@example.com", "pw", transport=tr)
    assert auth.remember_token == token
    # the POST must carry the session cookie captured from the GET
    post_headers = tr.calls[1][2]
    assert "_workshop_session=s3ss" in post_headers["Cookie"]


def test_login_with_password_bad_credentials():
    html = '<input name="authenticity_token" value="CSRF">'.encode()
    routes = {
        ("GET", A.SIGNIN_URL): Response(200, [("Set-Cookie", "_workshop_session=s; path=/")], html),
        ("POST", A.SIGNIN_URL): Response(200, [], b"<html>invalid</html>"),  # no remember token
    }
    with pytest.raises(A.AuthError):
        A.login_with_password("me@example.com", "wrong", transport=FakeTransport(routes))


# -- manifest + download ---------------------------------------------------------------
MANIFEST_JSON = json.dumps({
    "id": 314, "version": "25.2.0", "patch_level": "43f67db",
    "device_model": {"id": 2, "name": "N0110", "device_type_id": 1}, "size": None,
}).encode()


def _auth():
    return Auth(make_token())


def test_fetch_manifest():
    blob = dfuse_blob()
    manifest_json = json.dumps({
        "id": 314, "version": "25.2.0", "patch_level": "43f67db",
        "device_model": {"id": 2, "name": "N0110", "device_type_id": 1}, "size": len(blob),
    }).encode()
    routes = {("GET", D.manifest_url("n0110", "stable")): Response(200, [], manifest_json)}
    m = D.fetch_manifest("n0110", "stable", _auth(), transport=FakeTransport(routes))
    assert m.version == "25.2.0" and m.patch_level == "43f67db"
    assert m.device_type_id == 1 and m.size == len(blob)


def test_download_dfu_ok_and_size_check():
    blob = dfuse_blob()
    routes = {("GET", D.dfu_url("n0110", "stable")): Response(200, [], blob)}
    got = D.download_dfu("n0110", "stable", _auth(), expected_size=len(blob),
                         transport=FakeTransport(routes))
    assert got[:5] == b"DfuSe"
    # wrong expected size -> error
    with pytest.raises(D.DownloadError):
        D.download_dfu("n0110", "stable", _auth(), expected_size=len(blob) + 1,
                       transport=FakeTransport(routes))


def test_download_dfu_rejects_non_dfuse():
    routes = {("GET", D.dfu_url("n0110", "stable")): Response(200, [], b"<html>login</html>")}
    with pytest.raises(D.DownloadError):
        D.download_dfu("n0110", "stable", _auth(), transport=FakeTransport(routes))


def test_download_401_raises_auth_required():
    routes = {("GET", D.dfu_url("n0200", "stable")): Response(401, [], b"Unauthorized")}
    with pytest.raises(D.AuthRequired):
        D.download_dfu("n0200", "stable", _auth(), transport=FakeTransport(routes))


def test_fetch_firmware_end_to_end():
    blob = dfuse_blob()
    manifest_json = json.dumps({
        "version": "25.2.0", "patch_level": "43f67db",
        "device_model": {"id": 2, "device_type_id": 1}, "size": len(blob),
    }).encode()
    routes = {
        ("GET", D.manifest_url("n0110", "stable")): Response(200, [], manifest_json),
        ("GET", D.dfu_url("n0110", "stable")): Response(200, [], blob),
    }
    m, got = D.fetch_firmware("n0110", "stable", _auth(), transport=FakeTransport(routes))
    assert m.version == "25.2.0"
    img = FirmwareImage.from_dfuse(got)
    assert img.total_size > 0


def test_bad_channel_rejected():
    with pytest.raises(ValueError):
        D.fetch_manifest("n0110", "nightly", _auth(), transport=FakeTransport({}))


# -- provenance : empreinte SHA-256 + journal ------------------------------------------
def test_sha256_hex_matches_hashlib():
    import hashlib
    blob = dfuse_blob()
    assert D.sha256_hex(blob) == hashlib.sha256(blob).hexdigest()
    # déterministe : mêmes octets → même empreinte
    assert D.sha256_hex(blob) == D.sha256_hex(bytes(blob))


def test_record_download_appends_jsonl(tmp_path):
    p = tmp_path / "downloads.log"
    m = D.FirmwareManifest(model="n0110", channel="stable", version="25.2.0",
                           patch_level="43f67db", size=3191133)
    D.record_download(m, "abc123", when="2026-07-12T10:00:00+00:00", path=p)
    D.record_download(m, "def456", when="2026-07-12T11:00:00+00:00", path=p)
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # append, pas écrasement
    first = json.loads(lines[0])
    assert first == {"when": "2026-07-12T10:00:00+00:00", "model": "n0110",
                     "channel": "stable", "version": "25.2.0", "patch_level": "43f67db",
                     "size": 3191133, "sha256": "abc123"}


def test_register_device_posts_expected_body():
    from nwupdater.catalog import device as DV
    routes = {("POST", DV.device_url("SER123")):
              Response(200, [], b'{"id":"SER123","serial_number":"SER123","software_version":"3.0.0"}')}
    tr = FakeTransport(routes)
    out = DV.register_device(Auth(make_token()), "SER123", device_model="N0200",
                             software_version="3.0.0", software_patch_level="8059a46", transport=tr)
    assert out["status"] == 200 and "3.0.0" in out["body"]
    sent = json.loads(tr.calls[0][3].decode())          # the POST body
    assert sent["device"]["device_model"] == "N0200"
    assert sent["firmware"]["software_version"] == "3.0.0"
    assert sent["firmware"]["software_patch_level"] == "8059a46"


class _FakeClient:
    """DfuClient stand-in for pairing: serves a serial descriptor + a memory read."""
    def __init__(self, serial, header_at):
        self._serial = serial
        self._mem = header_at  # {addr: bytes}

    def get_string_descriptor(self, index, langid=0x0409):
        return self._serial

    def read(self, address, length):
        return (self._mem.get(address) or b"\x00" * length)[:length]


def test_pair_device_reads_n0200_identity_and_posts():
    from nwupdater.catalog import device as DV
    from nwupdater.formats import platform_info as PI
    from nwupdater.models import MODELS

    header = PI.pack("3.0.0", "8059a46")                 # @0x080040C0 FirmwareHeader block
    client = _FakeClient("SER-XYZ-123", {PI.N0200_FIRMWARE_HEADER_ADDR: header})
    routes = {("POST", DV.device_url("SER-XYZ-123")): Response(200, [], b'{"id":"SER-XYZ-123"}')}
    tr = FakeTransport(routes)

    res = DV.pair_device(client, MODELS[0x0200], Auth(make_token()), transport=tr)
    assert res["serial"] == "SER-XYZ-123"
    assert res["software_version"] == "3.0.0" and res["software_patch_level"] == "8059a46"
    assert res["register"]["status"] == 200
    sent = json.loads(tr.calls[0][3].decode())
    assert sent["device"]["device_model"] == "N0200"
    assert sent["firmware"]["software_version"] == "3.0.0"


def test_pair_device_requires_serial():
    from nwupdater.catalog import device as DV
    from nwupdater.models import MODELS
    client = _FakeClient(None, {})                        # no iSerialNumber
    with pytest.raises(ValueError):
        DV.pair_device(client, MODELS[0x0200], Auth(make_token()), transport=FakeTransport({}))


def test_official_dfuse_generic_bcd_is_compatible():
    """Les .dfu officiels portent bcdDevice=0x0000 : l'installer ne doit PAS rejeter."""
    from nwupdater.dfu.protocol import DfuClient
    from nwupdater.install.installer import Installer
    from nwupdater.testing.virtual_dfu import virtual_calculator

    # DfuSe avec suffixe générique 0x0000 (comme NumWorks), device réel = n0110
    blob = FirmwareImage.synthetic(MODELS[0x0110], version="25.2.0").to_dfuse(bcd_device=0x0000)
    image = FirmwareImage.from_dfuse(blob)
    assert image.bcd_device == 0x0000
    dev = virtual_calculator("n0110", os_version="23.2.4")
    inst = Installer(DfuClient(dev, sleep=lambda *_: None), MODELS[0x0110])
    inst.check_compatibility(image)  # ne lève pas
    plan = inst.install(image, active_slot="A", verify=True)
    assert plan.target_slot == "B"


def test_full_multislot_image_verbatim_and_version_readback():
    """Reproduit la disposition réelle : image complète (slots A ET B) → flash verbatim,
    et la relecture de version doit retrouver l'en-tête userland à slot+0x10000."""
    from nwupdater.dfu.protocol import DfuClient
    from nwupdater.formats import headers
    from nwupdater.install.image import FirmwareSegment
    from nwupdater.install.installer import Installer, plan_install
    from nwupdater.testing.virtual_dfu import virtual_calculator

    model = MODELS[0x0110]
    slot_a = model.memory.external_flash_origin
    slot_b = slot_a + model.memory.slot_size

    def slot_bytes():
        buf = bytearray(b"\x00" * (0x10000 + 48))
        buf[8:8 + 24] = headers.pack_kernel_header("25.2.0", "43f67db")
        buf[0x10000:0x10000 + 48] = headers.pack_userland_header(
            "25.2.0", storage_addr_ram=model.memory.sram_origin + 0x1000,
            storage_size_ram=0x1000, external_apps_flash=(0, 0))
        return bytes(buf)

    segs = [FirmwareSegment(0x08000000, b"\x00" * 1024),
            FirmwareSegment(slot_a, slot_bytes()),   # slot A
            FirmwareSegment(slot_b, slot_bytes())]   # slot B (both pre-populated)
    image = FirmwareImage(segs, version="25.2.0", bcd_device=0x0000)

    plan = plan_install(model, image, active_slot="A")
    assert plan.full_image is True and plan.target_slot == "A+B"
    assert plan.boot_address == slot_a + 0x10000  # slot A userland, not a persistent region

    dev = virtual_calculator("n0110", os_version="23.2.4")
    inst = Installer(DfuClient(dev, sleep=lambda *_: None), model)
    done = inst.install(image, active_slot="A", verify=True)
    assert inst.read_installed_version(done) == "25.2.0"

"""Capture-session tests — USB + WEB, fully offline (virtual device + fake transport)."""

import base64
import json

from nwupdater.capture_session import run_capture
from nwupdater.catalog import auth as A
from nwupdater.catalog import download as D
from nwupdater.catalog.auth import Auth, Response
from nwupdater.install.image import FirmwareImage
from nwupdater.models import MODELS
from nwupdater.net_capture import RecordingTransport
from nwupdater.testing.virtual_dfu import virtual_calculator


def _auth():
    payload = {"_rails": {"exp": "2099-01-01T00:00:00Z", "pur": A.REMEMBER_PURPOSE}}
    return Auth(base64.b64encode(json.dumps(payload).encode()).decode() + "--sig")


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes

    def open(self, method, url, *, headers=None, data=None, timeout=20.0, allow_redirects=False):
        return self.routes[(method, url)]


def _dfu_blob():
    return FirmwareImage.synthetic(MODELS[0x0200], version="3.0.0").to_dfuse()


def _routes_ok():
    blob = _dfu_blob()
    manifest = json.dumps({"version": "3.0.0", "patch_level": "8059a46",
                           "device_model": {"id": 9, "device_type_id": 6},
                           "size": len(blob)}).encode()
    return {
        ("GET", D.manifest_url("n0200", "stable")):
            Response(200, [("Content-Type", "application/json")], manifest),
        ("GET", D.dfu_url("n0200", "stable")):
            Response(200, [("Content-Type", "application/octet-stream")], blob),
    }, blob


def _dev():
    return virtual_calculator("n0200", os_version="1.0.0")


# -- net capture redaction --------------------------------------------------------------
def test_recording_transport_redacts_secrets():
    inner = FakeTransport({("POST", A.SIGNIN_URL): Response(302, [
        ("Set-Cookie", "remember_user_token=SECRET; HttpOnly")], b"")})
    rt = RecordingTransport(inner)
    rt.open("POST", A.SIGNIN_URL,
            headers={"Cookie": "remember_user_token=SECRET"},
            data=b"user%5Bemail%5D=a%40b.c&user%5Bpassword%5D=hunter2&authenticity_token=CSRF")
    rec = rt.transfers[0]
    assert rec["request"]["headers"]["Cookie"] == "[REDACTED]"
    assert rec["request"]["body"]["form"]["user[password]"] == "[REDACTED]"
    assert rec["request"]["body"]["form"]["authenticity_token"] == "[REDACTED]"
    assert rec["response"]["headers"]["Set-Cookie"] == "[REDACTED]"
    # no secret leaked anywhere in the serialized record
    assert "SECRET" not in json.dumps(rec) and "hunter2" not in json.dumps(rec)


def test_firmware_binary_never_stored():
    routes, blob = _routes_ok()
    dump = run_capture(_dev(), auth=_auth(), transport=FakeTransport(routes),
                       model="n0200", channel="stable", sleep=lambda *_: None, timestamp="t")
    dfu_tr = [x for x in dump["web"]["transfers"] if x["request"]["url"].endswith(".dfu")][0]
    body = dfu_tr["response"]["body"]
    assert body.get("binary") is True and "text" not in body
    assert body["size"] == len(blob) and len(body["sha256"]) == 64


# -- full scenario --------------------------------------------------------------------
def test_capture_download_ok_no_flash():
    routes, blob = _routes_ok()
    dev = _dev()
    dump = run_capture(dev, auth=_auth(), transport=FakeTransport(routes),
                       model="n0200", channel="stable", sleep=lambda *_: None,
                       timestamp="2026-07-12T00:00:00+00:00", serial="SN-TEST-0001")
    assert dump["flashed"] is False
    assert dump["scenario"].startswith("scientific")
    assert dump["calculator_serial"] == "SN-TEST-0001"
    # USB side captured, read-only
    assert dump["usb"]["model"] == "n0200" and dump["usb"]["read_only"] is True
    assert dump["usb"]["transfer_count"] > 0
    # WEB side captured
    assert dump["web"]["outcome"] == "downloaded"
    assert dump["web"]["firmware"]["version"] == "3.0.0"
    assert dump["web"]["firmware"]["size"] == len(blob)
    assert len(dump["web"]["transfers"]) == 2  # manifest + dfu
    # the flash never happened: device slot B still empty of a v3 userland header
    assert dev.left is False


def test_capture_server_refuses_unregistered_calculator():
    """First boot: server may refuse (e.g. 403). It's a captured outcome, not a crash."""
    routes = {("GET", D.manifest_url("n0200", "stable")): Response(403, [], b"Forbidden")}
    dump = run_capture(_dev(), auth=_auth(), transport=FakeTransport(routes),
                       model="n0200", channel="stable", sleep=lambda *_: None, timestamp="t")
    assert dump["web"]["outcome"] == "refused_or_error"
    assert dump["web"]["transfers"][0]["response"]["status"] == 403
    assert dump["flashed"] is False


def test_capture_auth_required():
    routes = {("GET", D.manifest_url("n0200", "stable")): Response(401, [], b"Unauthorized")}
    dump = run_capture(_dev(), auth=_auth(), transport=FakeTransport(routes),
                       model="n0200", channel="stable", sleep=lambda *_: None, timestamp="t")
    assert dump["web"]["outcome"] == "auth_required"


# -- HTML form inspection (device-enrollment endpoint discovery) ----------------------
from nwupdater.capture_session import ENROLL_PORTAL_URL, inspect_enrollment  # noqa: E402
from nwupdater.net_capture import inspect_forms  # noqa: E402

# Synthetic portal markup — ONLY exercises the parser; NOT the real NumWorks form (whose
# exact shape a volunteer's capture will reveal).
_ENROLL_HTML = (
    '<html><body><form action="/devices" method="POST">'
    '<input type="hidden" name="authenticity_token" value="TOK">'
    '<input type="text" name="device[serial_number]">'
    '<input type="text" name="device[name]">'
    '<input type="submit" value="Enregistrer"></form></body></html>'
)


def test_inspect_forms_extracts_action_method_fields():
    forms = inspect_forms(_ENROLL_HTML)
    assert len(forms) == 1
    f = forms[0]
    assert f["action"] == "/devices" and f["method"] == "POST"
    assert f["fields"] == ["authenticity_token", "device[name]", "device[serial_number]"]
    assert f["captcha"] is False and f["file_input"] is False


def test_inspect_forms_flags_captcha():
    html = '<form action="/x"><div class="g-recaptcha" data-sitekey="k"></div></form>'
    assert inspect_forms(html)[0]["captcha"] is True


def test_capture_inspects_enrollment_portal_read_only():
    routes, _ = _routes_ok()
    routes[("GET", ENROLL_PORTAL_URL)] = Response(
        200, [("Content-Type", "text/html")], _ENROLL_HTML.encode())
    dump = run_capture(_dev(), auth=_auth(), transport=FakeTransport(routes),
                       model="n0200", channel="stable", sleep=lambda *_: None,
                       timestamp="t", serial="SN-TEST-0001")
    enr = dump["enrollment"]
    assert dump["enrolled"] is False and enr["read_only"] is True
    assert enr["status"] == 200 and enr["serial_available"] is True
    assert enr["forms"][0]["action"] == "/devices"
    # STRICTLY read-only: the probe only ever GETs — it never submits the enrollment form.
    assert enr["transfers"] and all(t["request"]["method"] == "GET" for t in enr["transfers"])
    # the auth cookie is redacted in the recorded probe
    assert enr["transfers"][0]["request"]["headers"]["Cookie"] == "[REDACTED]"
    # download transfers stay isolated from the enrollment probe
    assert len(dump["web"]["transfers"]) == 2


def test_inspect_enrollment_never_crashes_on_transport_error():
    class Boom:
        def open(self, *a, **k):
            raise RuntimeError("network down")
    enr = inspect_enrollment(_auth(), Boom())
    assert "error" in enr and enr["read_only"] is True

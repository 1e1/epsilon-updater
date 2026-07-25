"""Analyzer (consumer) for the first-boot capture dump.

Fully offline. Covers the harness' canonical ``run_capture()`` output (USB transfers from
``dfu.capture.CapturingDevice``, WEB transfers from ``net_capture.RecordingTransport``) as well
as the legacy directory layout. No dependency on the harness modules — only on their formats.
"""

import base64
import json

from nwupdater.dfu import constants as C
from nwupdater.tools import capture_analyze as CA

SERIAL = "NW200SERIAL01"


# -- full capture analysis (legacy dir layout) -----------------------------------------
def _b64json(obj):
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _write_capture(d):
    (d / "meta.json").write_text(
        json.dumps({"app_version": "0.0.1", "calculator": {"model": "n0200", "first_boot": True}})
    )
    usb = [
        {
            "t": 0.0,
            "dir": "out",
            "bmRequestType": C.REQ_OUT,
            "bRequest": C.DFU_DNLOAD,
            "wValue": 0,
            "wIndex": 0,
            "len": 5,
            "data": "2100000020",
        },  # SET_ADDRESS 0x20000000
        {
            "t": 0.1,
            "dir": "in",
            "bmRequestType": C.REQ_IN,
            "bRequest": C.DFU_UPLOAD,
            "wValue": 2,
            "wIndex": 0,
            "len": len(SERIAL),
            "data": SERIAL.encode().hex(),
        },  # identity read
        {
            "t": 0.2,
            "dir": "in",
            "bmRequestType": C.REQ_IN,
            "bRequest": C.DFU_GETSTATUS,
            "wValue": 0,
            "wIndex": 0,
            "len": 6,
            "data": "000000000200",
        },  # OK / dfuIDLE
    ]
    (d / "usb.jsonl").write_text("\n".join(json.dumps(r) for r in usb))
    web = [
        {"method": "POST", "url": "https://my.numworks.com/users/sign_in", "status": 302},
        {
            "method": "GET",
            "url": "https://my.numworks.com/firmwares/n0200/stable.json",
            "status": 200,
        },
        {
            "method": "POST",
            "url": "https://my.numworks.com/devices",
            "status": 403,
            "req_body_b64": _b64json({"serial": SERIAL}),
        },  # enrollment refused
        {
            "method": "GET",
            "url": "https://my.numworks.com/firmwares/n0200/stable.dfu",
            "status": 200,
            "resp_len": 237606,
            "resp_sha256": "838d8fe32834",
        },
    ]
    (d / "web.jsonl").write_text("\n".join(json.dumps(r) for r in web))


def test_analyze_first_boot_capture(tmp_path):
    _write_capture(tmp_path)
    rep = CA.analyze(tmp_path)

    # USB: identity read, no write to the calculator
    assert rep["usb"]["writes"] == []
    assert rep["usb"]["reads"] == [["0x20000000", len(SERIAL)]]
    assert any("no write" in f for f in rep["findings"])

    # WEB: refusal + enrollment candidate + firmware attempt
    assert rep["web"]["refusals"] == [{"url": "https://my.numworks.com/devices", "status": 403}]
    kinds = {c["url"]: c["kind"] for c in rep["web"]["calls"]}
    assert kinds["https://my.numworks.com/devices"] == "enrollment?"
    assert kinds["https://my.numworks.com/firmwares/n0200/stable.dfu"] == "firmware"
    assert rep["web"]["firmware_downloads"][0]["resp_len"] == 237606

    # LINK: the serial read over USB appears in the enrollment body
    assert rep["serial_correlation"] == [SERIAL]
    assert any("server refusal" in f for f in rep["findings"])
    assert any("serial number read over USB" in f for f in rep["findings"])

    # report renders the findings (and does not print the empty-state placeholder)
    text = CA.format_report(rep)
    assert "(none)" not in text and "server refusal" in text


def test_write_to_calculator_is_flagged(tmp_path):
    (tmp_path / "usb.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "dir": "out",
                    "bRequest": C.DFU_DNLOAD,
                    "wValue": 0,
                    "data": "2100000098",
                },  # SET_ADDRESS
                {"dir": "out", "bRequest": C.DFU_DNLOAD, "wValue": 2, "data": "deadbeef"},  # WRITE!
            ]
        )
    )
    rep = CA.analyze(tmp_path)
    assert rep["usb"]["writes"] == [["0x98000000", 4]]
    assert any("WRITE" in f for f in rep["findings"])


def test_har_web_loading(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "startedDateTime": "2026-07-13T10:00:00Z",
                    "request": {
                        "method": "GET",
                        "url": "https://my.numworks.com/firmwares/n0200/stable.dfu",
                        "headers": [{"name": "Cookie", "value": "x"}],
                    },
                    "response": {"status": 200, "headers": [], "content": {"size": 237606}},
                }
            ]
        }
    }
    (tmp_path / "web.har").write_text(json.dumps(har))
    cap = CA.load_capture(tmp_path)
    assert cap["web"][0]["url"].endswith("stable.dfu")
    assert cap["web"][0]["resp_len"] == 237606


# -- canonical: the harness' run_capture() output --------------------------------------
def _run_capture_dict(web_status_manifest=403):
    """Shape emitted by nwupdater.capture_session.run_capture(): CapturingDevice USB transfers
    (dir IN/OUT, hex-string setup fields) + RecordingTransport nested WEB transfers."""
    return {
        "scenario": "scientific-first-boot-download-no-flash",
        "flashed": False,
        "calculator_serial": SERIAL,
        "usb": {
            "model": "n0200",
            "family": "scientifique",
            "os_version": None,
            "slot_info_valid": False,
            "transfers": [
                {
                    "seq": 0,
                    "dir": "OUT",
                    "bmRequestType": "0x21",
                    "bRequest": C.DFU_DNLOAD,
                    "wValue": "0x0000",
                    "wIndex": 0,
                    "data_len": 5,
                    "data": "2100000098",
                },  # SET_ADDR 0x98000000
                {
                    "seq": 1,
                    "dir": "IN",
                    "bmRequestType": "0xa1",
                    "bRequest": C.DFU_UPLOAD,
                    "wValue": "0x0002",
                    "wIndex": 0,
                    "wLength": 32,
                    "data_len": len(SERIAL),
                    "data": SERIAL.encode().hex(),
                },  # identity read
            ],
        },
        "web": {
            "outcome": "refused_or_error",
            "model": "n0200",
            "channel": "stable",
            "transfers": [
                {
                    "seq": 0,
                    "request": {
                        "method": "POST",
                        "url": "https://my.numworks.com/users/sign_in",
                        "headers": {"Cookie": "[REDACTED]"},
                        "body": {"form": {"user[email]": "x"}},
                    },
                    "response": {
                        "status": 302,
                        "headers": {},
                        "body": {"size": 0, "sha256": "e3b0", "content_type": "text/html"},
                    },
                },
                {
                    "seq": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://my.numworks.com/firmwares/n0200/stable.json",
                    },
                    "response": {
                        "status": web_status_manifest,
                        "headers": {},
                        "body": {
                            "size": 60,
                            "sha256": "aa",
                            "content_type": "application/json",
                            "text": '{"error":"device not registered"}',
                        },
                    },
                },
            ],
        },
    }


def test_analyze_run_capture_dict_directly():
    rep = CA.analyze(_run_capture_dict())
    # USB decoded from CapturingDevice format (hex-string fields, IN/OUT)
    assert rep["usb"]["reads"] == [["0x98000000", len(SERIAL)]]
    assert rep["usb"]["writes"] == []
    # WEB refusal surfaced from the nested RecordingTransport response
    assert {"url": "https://my.numworks.com/firmwares/n0200/stable.json", "status": 403} in rep[
        "web"
    ]["refusals"]
    assert any("no write" in f for f in rep["findings"])


def test_analyze_run_capture_from_capture_json(tmp_path):
    (tmp_path / "capture.json").write_text(json.dumps(_run_capture_dict(web_status_manifest=200)))
    rep = CA.analyze(tmp_path)
    assert rep["usb"]["reads"] == [["0x98000000", len(SERIAL)]]
    assert rep["web"]["refusals"] == []

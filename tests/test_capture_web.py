"""Web-feature discovery: capture-hook.js ingestion, per-scenario API map, scrubber, CLI.

Offline. Builds capture-hook.js-shaped dumps (as the browser hook would emit) and checks the
analyzer groups endpoints by scenario, plus the PII scrubber and the CLI entrypoints.
"""

import json

from nwupdater.tools import capture_analyze as CA
from nwupdater.tools import capture_cli
from nwupdater.tools.scrub import scrub


def _hook_capture():
    return {
        "tool": "nwupdater-capture-hook",
        "version": 1,
        "started": 0,
        "markers": [{"t": 10, "scenario": "pair"}],
        "web": [
            {
                "t": 11,
                "scenario": "pair",
                "method": "POST",
                "url": "https://my.numworks.com/devices",
                "status": 201,
                "resp_len": 30,
                "resp_sha256": "aa",
                "resp_body": '{"id":7}',
                "req_body": '{"serial":"ABCD1234EFGH"}',
            },
            {
                "t": 20,
                "scenario": "scripts-list",
                "method": "GET",
                "url": "https://my.numworks.com/scripts.json?foo=1",
                "status": 200,
                "resp_len": 12,
                "resp_body": '[{"name":"a"}]',
            },
            {
                "t": 21,
                "scenario": "scripts-list",
                "method": "GET",
                "url": "https://my.numworks.com/scripts.json?foo=2",
                "status": 200,
                "resp_len": 12,
            },
        ],
        "usb": [
            {
                "t": 12,
                "scenario": "pair",
                "via": "control",
                "dir": "out",
                "request": 1,
                "value": 0,
                "index": 0,
                "data": "2100000020",
            },  # SET_ADDRESS 0x20000000
            {
                "t": 13,
                "scenario": "pair",
                "via": "control",
                "dir": "in",
                "request": 2,
                "value": 2,
                "index": 0,
                "data": b"ABCD1234EFGH".hex(),
            },  # identity read
            {
                "t": 30,
                "scenario": "scripts-list",
                "via": "bulk",
                "dir": "in",
                "endpoint": 1,
                "data": "deadbeef",
            },  # bulk → ignored for DFU
        ],
    }


def test_hook_ingestion_and_api_map_by_scenario():
    rep = CA.analyze(_hook_capture())
    by = rep["by_scenario"]
    assert set(by) == {"pair", "scripts-list"}

    pair_eps = {(e["method"], e["endpoint"]): e for e in by["pair"]["web"]}
    assert pair_eps[("POST", "my.numworks.com/devices")]["statuses"] == [201]
    assert by["pair"]["usb_transfers"] == 2  # SET_ADDRESS + identity read (both control)
    assert by["scripts-list"]["usb_transfers"] == 0  # the lone bulk transfer is excluded

    # query strings collapse → one endpoint counted twice
    sl = by["scripts-list"]["web"]
    assert (
        len(sl) == 1 and sl[0]["endpoint"] == "my.numworks.com/scripts.json" and sl[0]["count"] == 2
    )

    # control USB decoded (bulk ignored); SET_ADDRESS then identity read
    assert rep["usb"]["reads"] == [["0x20000000", 12]]
    assert "API map by feature" in CA.format_report(rep)


def test_serial_correlation_across_usb_and_web():
    rep = CA.analyze(_hook_capture())
    # "ABCD1234EFGH" is read over USB and appears in the enrollment request body
    assert "ABCD1234EFGH" in rep["serial_correlation"]


def test_scrubber_stable_tokens_and_structure():
    obj = {"email": "me@x.com", "dup": ["me@x.com", "other@y.org"], "tok": "A" * 50}
    scrubbed, mapping = scrub(obj)
    assert scrubbed["email"] == "EMAIL_1"
    assert scrubbed["dup"] == ["EMAIL_1", "EMAIL_2"]  # same value → same token
    assert scrubbed["tok"] == "TOKEN_1"
    assert len(mapping) == 3


def test_scrubber_explicit_value_first():
    scrubbed, _mapping = scrub({"s": "serial NW-0200-XYZ here"}, extra_values=["NW-0200-XYZ"])
    assert "VALUE_1" in scrubbed["s"] and "NW-0200-XYZ" not in scrubbed["s"]


def test_cli_analyze_and_scrub(tmp_path):
    p = tmp_path / "capture.json"
    p.write_text(json.dumps(_hook_capture()))
    assert capture_cli.main(["analyze", str(p)]) == 0
    out = tmp_path / "s.json"
    assert capture_cli.main(["scrub", str(p), "-o", str(out), "--value", "ABCD1234EFGH"]) == 0
    assert out.is_file()


def test_hook_js_is_packaged():
    assert capture_cli.HOOK_JS.is_file()
    assert "capture-hook" in capture_cli.HOOK_JS.read_text()


def test_userscript_is_packaged_and_matches_numworks():
    assert capture_cli.USER_JS.is_file()
    src = capture_cli.USER_JS.read_text(encoding="utf-8")
    assert "==UserScript==" in src
    assert "*://*.numworks.com/*" in src and "document-start" in src


def test_capture_server_marks_stamps_and_serves_userscript():
    import json as _j
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    store = {
        "tool": "nwupdater-capture-hook",
        "version": 1,
        "started": 0,
        "markers": [],
        "web": [],
        "usb": [],
    }
    control = {"last": 0.0, "scenario": "idle"}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), capture_cli._make_handler(store, control))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def post(path, obj):
        urllib.request.urlopen(
            urllib.request.Request(
                base + path,
                data=_j.dumps(obj).encode(),
                headers={"Content-Type": "application/json"},
            )
        )

    try:
        post("/mark", {"scenario": "pair"})
        post(
            "/rec",
            {
                "kind": "web",
                "rec": {
                    "method": "GET",
                    "url": "https://my.numworks.com/scripts.json",
                    "status": 200,
                },
            },
        )
        # the server holds the current scenario and stamps incoming frames with it
        assert control["scenario"] == "pair"
        assert store["web"] and store["web"][0]["scenario"] == "pair"
        assert store["markers"] and store["markers"][-1]["scenario"] == "pair"
        st = _j.load(urllib.request.urlopen(base + "/state"))
        assert st["scenario"] == "pair" and st["web"] == 1
        js = urllib.request.urlopen(base + "/capture.user.js").read().decode()
        assert "==UserScript==" in js and "numworks.com" in js
    finally:
        httpd.shutdown()

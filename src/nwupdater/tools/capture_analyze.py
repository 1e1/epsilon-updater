"""Analyse a first-boot capture dump (USB + WEB) — the *consumer* of the capture contract.

Reads a capture directory (see ``docs/01-specs/capture-format.md``) and produces a structured
report answering the questions that matter for the Scientifique first-boot download:

  USB  — decode the DFU/DfuSe dialogue: which addresses the app READ from the calculator
         (identity / serial), whether any WRITE happened (must be none per the test plan),
         and any GETSTATUS errors.
  WEB  — classify the HTTP flow: login, manifest, .dfu download, and — the crux — any device
         ENROLLMENT step and any server REFUSAL (4xx), i.e. "calculator not registered".
  LINK — does a serial read over USB reappear in a web (enrollment) body?

Run:  python -m nwupdater.tools.capture_analyze <dump_dir> [--json]

Offline, read-only; no network, no USB.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..dfu import constants as C

_REQ_NAME: dict = {
    C.DFU_DETACH: "DETACH", C.DFU_DNLOAD: "DNLOAD", C.DFU_UPLOAD: "UPLOAD",
    C.DFU_GETSTATUS: "GETSTATUS", C.DFU_CLRSTATUS: "CLRSTATUS",
    C.DFU_GETSTATE: "GETSTATE", C.DFU_ABORT: "ABORT",
}
_SERIAL_RE = re.compile(rb"[A-Za-z0-9]{8,32}")


# ---------------------------------------------------------------------------- loading
def _read_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _har_headers(headers) -> dict:
    return {h.get("name", ""): h.get("value", "") for h in headers or []}


def _har_to_web(har: dict) -> list[dict]:
    rows = []
    for e in har.get("log", {}).get("entries", []):
        req, resp = e.get("request", {}), e.get("response", {})
        rows.append({
            "t": e.get("startedDateTime"),
            "method": req.get("method", ""),
            "url": req.get("url", ""),
            "status": resp.get("status", 0),
            "req_headers": _har_headers(req.get("headers")),
            "resp_headers": _har_headers(resp.get("headers")),
            "resp_len": (resp.get("content") or {}).get("size", 0),
            "req_body_text": (req.get("postData") or {}).get("text"),
            "resp_body_text": (resp.get("content") or {}).get("text"),
        })
    return rows


def _coerce_int(x) -> int:
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        s = x.strip()
        try:
            return int(s, 16) if s.lower().startswith("0x") else int(s)
        except ValueError:
            return 0
    return 0


def _norm_usb_transfer(r: dict) -> dict:
    """dfu.capture.CapturingDevice record → the shape analyze_usb expects."""
    return {
        "dir": "in" if str(r.get("dir", "")).lower() == "in" else "out",
        "bRequest": _coerce_int(r.get("bRequest")),
        "wValue": _coerce_int(r.get("wValue", 0)),
        "wIndex": _coerce_int(r.get("wIndex", 0)),
        "data": r.get("data", "") or "",
    }


def _norm_web_transfer(t: dict) -> dict:
    """net_capture.RecordingTransport nested record → flat row for analyze_web."""
    req = t.get("request", {}) or {}
    resp = t.get("response", {}) or {}
    body = resp.get("body", {}) or {}
    return {
        "method": req.get("method", ""),
        "url": req.get("url", ""),
        "status": resp.get("status", 0),
        "resp_len": body.get("size", 0),
        "resp_sha256": body.get("sha256"),
        "resp_body_text": body.get("text") or body.get("text_head"),
        "req_body_text": json.dumps(req.get("body"), ensure_ascii=False) if req.get("body") else None,
    }


def _is_run_capture(obj) -> bool:
    return isinstance(obj, dict) and (
        "scenario" in obj or isinstance(obj.get("usb"), dict) or isinstance(obj.get("web"), dict))


def _from_run_capture(cap: dict) -> dict:
    """Normalise nwupdater.capture_session.run_capture() output into records analyze() reads."""
    usb = cap.get("usb") or {}
    web = cap.get("web") or {}
    meta = {
        "scenario": cap.get("scenario"),
        "calculator": {"model": usb.get("model")},
        "os_version": usb.get("os_version"),
        "outcome": web.get("outcome"),
        "calculator_serial": cap.get("calculator_serial"),
    }
    return {"meta": meta,
            "usb": [_norm_usb_transfer(r) for r in (usb.get("transfers") or [])],
            "web": [_norm_web_transfer(t) for t in (web.get("transfers") or [])]}


def _is_hook(obj) -> bool:
    return isinstance(obj, dict) and obj.get("tool") == "nwupdater-capture-hook"


def _norm_hook_usb(r: dict) -> dict:
    return {
        "dir": "in" if str(r.get("dir", "")).lower() == "in" else "out",
        "bRequest": _coerce_int(r.get("request", 0)),
        "wValue": _coerce_int(r.get("value", 0)),
        "wIndex": _coerce_int(r.get("index", 0)),
        "data": r.get("data", "") or "",
        "scenario": r.get("scenario"),
    }


def _norm_hook_web(r: dict) -> dict:
    return {
        "method": r.get("method", ""), "url": r.get("url", ""),
        "status": int(r.get("status") or 0),
        "resp_len": r.get("resp_len", 0), "resp_sha256": r.get("resp_sha256"),
        "resp_body_text": r.get("resp_body"), "req_body_text": r.get("req_body"),
        "scenario": r.get("scenario"),
    }


def _from_hook(obj: dict) -> dict:
    """Normalise capture-hook.js output (fetch/XHR + WebUSB, scenario-tagged)."""
    return {
        "meta": {"tool": "capture-hook", "started": obj.get("started"),
                 "markers": obj.get("markers", [])},
        # only control transfers are DFU-decodable; bulk transfers are ignored for decoding
        "usb": [_norm_hook_usb(r) for r in obj.get("usb", []) if r.get("via", "control") == "control"],
        "web": [_norm_hook_web(r) for r in obj.get("web", [])],
    }


def _dispatch(obj):
    if _is_hook(obj):
        return _from_hook(obj)
    if _is_run_capture(obj):
        return _from_run_capture(obj)
    return None


def load_capture(source: str | Path | dict) -> dict:
    # Primary formats: capture-hook.js dump, or the harness' run_capture() dict.
    obj = None
    if isinstance(source, dict):
        obj = source
    else:
        p = Path(source)
        jf = p if (p.is_file() and p.suffix == ".json") else (p / "capture.json" if p.is_dir() else None)
        if jf is not None and jf.is_file():
            obj = json.loads(jf.read_text())
    if obj is not None:
        dispatched = _dispatch(obj)
        if dispatched is not None:
            return dispatched
    if isinstance(source, dict):
        return {"meta": {}, "usb": [], "web": []}
    # Legacy directory layout (usb.jsonl / web.jsonl / web.har).
    d = Path(source)
    cap: dict = {"meta": {}, "usb": [], "web": []}
    if (d / "meta.json").is_file():
        cap["meta"] = json.loads((d / "meta.json").read_text())
    if (d / "usb.jsonl").is_file():
        cap["usb"] = _read_jsonl(d / "usb.jsonl")
    if (d / "web.jsonl").is_file():
        cap["web"] = _read_jsonl(d / "web.jsonl")
    elif (d / "web.har").is_file():
        cap["web"] = _har_to_web(json.loads((d / "web.har").read_text()))
    return cap


def _endpoint(url: str) -> str:
    import urllib.parse
    try:
        s = urllib.parse.urlsplit(url)
        return (s.netloc + s.path) or url
    except Exception:
        return url


def api_map_by_scenario(cap: dict) -> dict:
    """Group web endpoints (and USB transfer counts) by scenario tag — the feature map."""
    out: dict = {}
    for row in cap["web"]:
        sc = row.get("scenario") or "?"
        d = out.setdefault(sc, {"endpoints": {}, "usb_transfers": 0})
        key = (row.get("method", ""), _endpoint(row.get("url", "")))
        e = d["endpoints"].setdefault(key, {"method": key[0], "endpoint": key[1],
                                            "count": 0, "statuses": []})
        e["count"] += 1
        st = int(row.get("status") or 0)
        if st and st not in e["statuses"]:
            e["statuses"].append(st)
    for r in cap["usb"]:
        sc = r.get("scenario") or "?"
        out.setdefault(sc, {"endpoints": {}, "usb_transfers": 0})["usb_transfers"] += 1
    return {sc: {"web": list(d["endpoints"].values()), "usb_transfers": d["usb_transfers"]}
            for sc, d in out.items()}


# ------------------------------------------------------------------------------- USB
@dataclass
class UsbAnalysis:
    ops: list[str] = field(default_factory=list)
    reads: list[tuple[int, int]] = field(default_factory=list)   # (address, length)
    writes: list[tuple[int, int]] = field(default_factory=list)
    erases: list[int] = field(default_factory=list)
    statuses: list[tuple[str, str]] = field(default_factory=list)  # (status, state)
    left: bool = False
    read_bytes: bytes = b""


def analyze_usb(records: list[dict]) -> UsbAnalysis:
    a = UsbAnalysis()
    pointer = 0
    for r in records:
        br = r.get("bRequest")
        wv = r.get("wValue", 0)
        data = bytes.fromhex(r.get("data", "") or "")
        name = _REQ_NAME.get(br, f"req{br}")
        if r.get("dir") == "out" and br == C.DFU_DNLOAD:
            if wv == 0 and data:
                sub = data[0]
                if sub == C.DFUSE_SET_ADDRESS and len(data) >= 5:
                    pointer = int.from_bytes(data[1:5], "little")
                    a.ops.append(f"SET_ADDRESS 0x{pointer:08x}")
                elif sub == C.DFUSE_ERASE:
                    if len(data) >= 5:
                        addr = int.from_bytes(data[1:5], "little")
                        a.erases.append(addr)
                        a.ops.append(f"ERASE 0x{addr:08x}")
                    else:
                        a.ops.append("MASS_ERASE")
                elif sub == C.DFUSE_READ_UNPROTECT:
                    a.ops.append("READ_UNPROTECT")
                else:
                    a.ops.append(f"DNLOAD-cmd 0x{sub:02x}")
            elif wv >= C.DNLOAD_BLOCK_BASE:
                if len(data) == 0:
                    a.left = True
                    a.ops.append("LEAVE (zero-length DNLOAD → manifest/reset)")
                else:
                    addr = pointer + (wv - C.DNLOAD_BLOCK_BASE) * C.TRANSFER_SIZE
                    a.writes.append((addr, len(data)))
                    a.ops.append(f"WRITE 0x{addr:08x} ({len(data)} o)")
        elif r.get("dir") == "in" and br == C.DFU_UPLOAD:
            addr = pointer + (wv - C.DNLOAD_BLOCK_BASE) * C.TRANSFER_SIZE
            a.reads.append((addr, len(data)))
            a.read_bytes += data
            a.ops.append(f"READ 0x{addr:08x} ({len(data)} o)")
        elif br == C.DFU_GETSTATUS and data:
            status = C.STATUS_NAMES.get(data[0], hex(data[0]))
            state = C.STATE_NAMES.get(data[4], hex(data[4])) if len(data) > 4 else "?"
            a.statuses.append((status, state))
        else:
            a.ops.append(name)
    return a


# ------------------------------------------------------------------------------- WEB
@dataclass
class WebCall:
    method: str
    url: str
    status: int
    kind: str          # login | manifest | firmware | enrollment? | other
    note: str = ""


def _body_text(row: dict) -> str:
    for k in ("req_body_text", "resp_body_text"):
        if row.get(k):
            return row[k]
    for k in ("req_body_b64", "resp_body_b64"):
        if row.get(k):
            try:
                return base64.b64decode(row[k]).decode("utf-8", "replace")
            except Exception:
                pass
    return ""


def _classify_url(method: str, url: str) -> str:
    p = url.lower()
    if "/users/sign_in" in p or "/users/sign_out" in p:
        return "login"
    if re.search(r"/firmwares/\w+/\w+\.json", p):
        return "manifest"
    if p.endswith(".dfu"):
        return "firmware"
    if any(w in p for w in ("device", "calculator", "register", "enroll", "activat", "serial")):
        return "enrollment?"
    if method.upper() in ("POST", "PUT", "PATCH"):
        return "enrollment?"  # unknown mutating call during first boot → worth flagging
    return "other"


def analyze_web(records: list[dict]) -> dict:
    calls: list[WebCall] = []
    refusals: list[WebCall] = []
    enrollments: list[dict] = []
    firmwares: list[dict] = []
    for row in records:
        method = row.get("method", "")
        url = row.get("url", "")
        status = int(row.get("status") or row.get("resp_status") or 0)
        kind = _classify_url(method, url)
        note = ""
        if kind == "firmware":
            note = f"{row.get('resp_len', 0)} o"
            firmwares.append({"url": url, "status": status,
                              "resp_len": row.get("resp_len", 0),
                              "resp_sha256": row.get("resp_sha256")})
        if kind == "enrollment?":
            enrollments.append({"method": method, "url": url, "status": status,
                                "body": _body_text(row)[:2000]})
        c = WebCall(method=method, url=url, status=status, kind=kind, note=note)
        calls.append(c)
        if status >= 400:
            refusals.append(c)
    return {"calls": calls, "refusals": refusals,
            "enrollment_candidates": enrollments, "firmware_downloads": firmwares}


# --------------------------------------------------------------------------- correlate
def correlate_serial(usb: UsbAnalysis, web: dict, web_records: list[dict]) -> list[str]:
    """Serial-like tokens read over USB that reappear verbatim in a web body."""
    usb_tokens = {m.group().decode() for m in _SERIAL_RE.finditer(usb.read_bytes)}
    if not usb_tokens:
        return []
    bodies = " ".join(_body_text(r) for r in web_records)
    return sorted(t for t in usb_tokens if len(t) >= 8 and t in bodies)


# ----------------------------------------------------------------------------- report
def analyze(dump_dir: str | Path) -> dict:
    cap = load_capture(dump_dir)
    usb = analyze_usb(cap["usb"])
    web = analyze_web(cap["web"])
    serials = correlate_serial(usb, web, cap["web"])

    findings: list[str] = []
    if cap["usb"]:
        if usb.writes:
            findings.append(f"⚠️ {len(usb.writes)} WRITE(S) to the calculator detected "
                            "(expected when loading/removing an app or pushing a script; "
                            "abnormal for a plain firmware download).")
        else:
            findings.append("✓ no write to the calculator (matches the plan).")
        if usb.reads:
            span = f"{len(usb.reads)} read(s), {sum(n for _, n in usb.reads)} B"
            findings.append(f"identity read over USB: {span} — addresses {[hex(a) for a, _ in usb.reads][:6]}.")
        err = [s for s in usb.statuses if s[0] != 'OK']
        if err:
            findings.append(f"⚠️ non-OK DFU status(es): {err[:5]}.")
    if cap["web"]:
        if web["refusals"]:
            findings.append("⚠️ server refusal(s) (≥400): " +
                            ", ".join(f"{c.status} {c.url}" for c in web["refusals"][:5]) +
                            " — check the \"calculator not registered\" hypothesis.")
        if web["enrollment_candidates"]:
            findings.append("↳ possible ENROLLMENT step(s): " +
                            ", ".join(f"{e['method']} {e['url']}" for e in web["enrollment_candidates"][:5]))
        if web["firmware_downloads"]:
            fw = web["firmware_downloads"][0]
            findings.append(f"firmware download: {fw['url']} → {fw['status']} "
                            f"({fw.get('resp_len')} B, sha256 {fw.get('resp_sha256')}).")
    if serials:
        findings.append(f"🔗 serial number read over USB found in a WEB body: {serials} "
                        "→ enrollment does transmit the calculator's identity.")

    return {
        "meta": cap["meta"],
        "usb": {"present": bool(cap["usb"]), "ops": usb.ops,
                "reads": [[f"0x{a:08x}", n] for a, n in usb.reads],
                "writes": [[f"0x{a:08x}", n] for a, n in usb.writes],
                "erases": [f"0x{a:08x}" for a in usb.erases],
                "statuses": usb.statuses, "left": usb.left},
        "web": {"present": bool(cap["web"]),
                "calls": [{"method": c.method, "url": c.url, "status": c.status, "kind": c.kind}
                          for c in web["calls"]],
                "refusals": [{"url": c.url, "status": c.status} for c in web["refusals"]],
                "enrollment_candidates": web["enrollment_candidates"],
                "firmware_downloads": web["firmware_downloads"]},
        "serial_correlation": serials,
        "by_scenario": api_map_by_scenario(cap),
        "findings": findings,
    }


def format_report(rep: dict) -> str:
    L = ["=== Capture analysis (Scientific first-boot) ==="]
    if rep["meta"]:
        m = rep["meta"]
        L.append(f"context: {m.get('calculator', {}).get('model', '?')} "
                 f"first_boot={m.get('calculator', {}).get('first_boot')} · app {m.get('app_version', '?')}")
    L.append("\n-- Findings --")
    if rep["findings"]:
        L.extend(f"  • {f}" for f in rep["findings"])
    else:
        L.append("  (none)")
    if rep["usb"]["present"]:
        L.append(f"\n-- USB ({len(rep['usb']['ops'])} DFU operations) --")
        L.append(f"  reads : {rep['usb']['reads']}")
        L.append(f"  writes: {rep['usb']['writes'] or 'none'}")
        if rep["usb"]["statuses"]:
            L.append(f"  status : {rep['usb']['statuses'][:8]}")
    if rep["web"]["present"]:
        L.append(f"\n-- WEB ({len(rep['web']['calls'])} requests) --")
        for c in rep["web"]["calls"]:
            L.append(f"  {c['status'] or '---'}  {c['method']:5s} {c['kind']:12s} {c['url']}")
    by = rep.get("by_scenario") or {}
    if by and set(by) != {"?"}:
        L.append("\n-- API map by feature --")
        for sc in sorted(by):
            d = by[sc]
            L.append(f"  [{sc}]  ({d['usb_transfers']} USB transfers)")
            for e in sorted(d["web"], key=lambda x: x["endpoint"]):
                L.append(f"      {e['method']:5s} {e['endpoint']}  ×{e['count']} {e['statuses']}")
    return "\n".join(L)


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m nwupdater.tools.capture_analyze",
        description="Analyse a USB+WEB capture dump (unofficial project).")
    p.add_argument("dump_dir", help="dump directory (meta.json, usb.jsonl, web.jsonl|web.har)")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(argv)
    rep = analyze(args.dump_dir)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else format_report(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

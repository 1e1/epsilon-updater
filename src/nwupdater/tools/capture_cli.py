"""nwupdater-capture — packageable executable for the web-feature discovery session.

Subcommands:
  serve    start a local page that hands you the capture-hook bookmarklet + checklist, and
           (optionally) receives live records from the hook, writing capture.json on exit.
  analyze  analyse a capture.json → per-scenario API map + findings.
  scrub    remove personal data (email/serial/tokens) before sharing.

Only ``serve`` needs to run on the tester's Mac; capture itself happens in the browser (the
hook). Stdlib only, so it packages cleanly (PyInstaller) — no heavy deps.
"""

from __future__ import annotations

import argparse
import json
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).parent / "web"
HOOK_JS = WEB_DIR / "capture-hook.js"          # bookmarklet fallback (single page)
USER_JS = WEB_DIR / "capture.user.js"          # userscript: continuous, persistent capture


def _web_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return f"/* {path.name} introuvable */"


_LAUNCH_HTML = """<!doctype html><meta charset=utf-8>
<title>nwupdater — capture</title>
<style>body{{font:15px/1.5 -apple-system,sans-serif;max-width:780px;margin:40px auto;padding:0 20px;color:#1b1c1e}}
code{{background:#f4f3ef;border-radius:6px;padding:1px 5px}} ol{{padding-left:22px}} li{{margin:7px 0}}
.b{{display:inline-block;background:#e8930c;color:#000;font-weight:700;padding:8px 14px;border-radius:8px;text-decoration:none}}
.note{{color:#6d6f74;font-size:13px}} h3{{margin-top:26px}}</style>
<h2>nwupdater · capture des fonctions web (non officiel)</h2>
<p><b>Projet indépendant, sans lien avec NumWorks. Aucune garantie.</b> La capture est
<b>continue et persistante</b> : une fois le userscript installé, tout le trafic de
<code>*.numworks.com</code> (fetch/XHR/WebUSB) est enregistré <b>en permanence</b> vers cet
exécutable, même quand tu changes de page. Le panneau ne sert qu'à <b>poser des marques</b>.</p>

<h3>Installation (une fois)</h3>
<ol>
<li>Installe l'extension <b>Tampermonkey</b> (ou Violentmonkey) dans ton navigateur
    (Chrome Web Store / Firefox Add-ons).</li>
<li>Clique <b>une seule fois</b> pour installer le userscript :
    <a class=b href="http://127.0.0.1:{port}/capture.user.js">Installer nw-capture</a>
    <br><span class=note>Tampermonkey affiche une page d'installation → « Installer ». Il
    demandera d'autoriser l'accès à <code>127.0.0.1</code> (pour envoyer les trames ici) → Autoriser.
    <b>Ce bouton ne sert QU'à l'installation</b> — recliquer ne fait que reproposer l'installation, c'est normal.</span></li>
</ol>
<p style="background:#fbe9cd;border-radius:8px;padding:10px 12px"><b>⚠️ Le choix du scénario ne se fait PAS ici.</b>
Une fois installé, va sur <code>my.numworks.com</code> : un panneau <b>« SCÉNARIO de capture »</b>
apparaît <b>en bas à droite de la page NumWorks</b> — c'est là que tu choisis le scénario avant chaque action.</p>

<h3>Capture</h3>
<ol>
<li>Ouvre <a href=https://my.numworks.com target=_blank>my.numworks.com</a> et connecte-toi
    (ton vrai compte). Un panneau « capture continue » apparaît en bas à droite — la capture
    tourne <b>déjà</b>.</li>
<li>Avant chaque action, choisis le <b>scénario</b> dans le panneau (ça pose une marque).
    Navigue/agis librement : rien n'est perdu entre les pages.</li>
<li>Déroule la checklist ci-dessous.</li>
<li>Terminé : reviens ici et fais <b>Ctrl-C</b> dans le terminal → <code>capture.json</code> est écrit.</li>
<li>Nettoie puis partage : <code>nwupdater-capture scrub capture.json --value TON_EMAIL</code></li>
</ol>

<h3>Checklist des scénarios</h3>
<ol>
<li><b>Appairage</b> (compte réel)</li><li><b>Lister les scripts</b> puis en <b>ouvrir</b> un</li>
<li><b>Créer/modifier</b> un script et le <b>pousser</b></li><li><b>Lister les apps</b></li>
<li><b>Charger</b> une app</li><li><b>Supprimer</b> cette app</li>
<li><b>Lister les MAJ</b> — <b>NE PAS appliquer</b></li><li><b>Désappairage</b> (à la fin)</li>
</ol>
<p class=note>Repli mono-page (sans Tampermonkey) : ouvre <a href=/capture-hook.js>/capture-hook.js</a>,
copie tout, colle dans la console (F12) de la page NumWorks — mais les données sont alors
perdues à chaque changement de page.</p>
"""


def _make_handler(store: dict, control: dict):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def _send(self, body: bytes, ctype: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            control["last"] = time.time()
            path = self.path.split("?", 1)[0]
            if path == "/capture.user.js":
                self._send(_web_source(USER_JS).encode("utf-8"), "application/javascript; charset=utf-8")
            elif path == "/capture-hook.js":
                self._send(_web_source(HOOK_JS).encode("utf-8"), "application/javascript; charset=utf-8")
            elif path == "/state":
                st = {"scenario": control.get("scenario", "idle"),
                      "web": len(store["web"]), "usb": len(store["usb"])}
                self._send(json.dumps(st).encode("utf-8"), "application/json; charset=utf-8")
            else:
                self._send(_LAUNCH_HTML.format(port=self.server.server_address[1]).encode("utf-8"),
                           "text/html; charset=utf-8")

        def do_POST(self):
            control["last"] = time.time()
            path = self.path.split("?", 1)[0]
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {}
            if path == "/mark":
                sc = str(msg.get("scenario") or "idle")
                control["scenario"] = sc
                store["markers"].append({"t": int(time.time() * 1000), "scenario": sc})
            else:  # /rec — stamp each frame with the server-held current scenario
                kind, rec = msg.get("kind"), msg.get("rec")
                if kind in ("web", "usb") and isinstance(rec, dict):
                    rec.setdefault("scenario", control.get("scenario", "idle"))
                    store[kind].append(rec)
            self.send_response(204)
            self._cors()
            self.end_headers()

    return H


def _cmd_serve(args) -> int:
    store = {"tool": "nwupdater-capture-hook", "version": 1, "started": int(time.time() * 1000),
             "markers": [], "web": [], "usb": []}
    control = {"last": time.time(), "scenario": "idle"}
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(store, control))
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"nwupdater capture : {url}")
    print("Installe le userscript depuis la page, joue les scénarios sur numworks.com,")
    print("puis Ctrl-C ici pour écrire capture.json (la capture est continue et persistante).")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    if store["web"] or store["usb"]:
        out = Path(args.out or "capture.json")
        out.write_text(json.dumps(store, ensure_ascii=False, indent=2))
        print(f"\ncapture live écrite → {out}  ({len(store['web'])} web, {len(store['usb'])} usb)")
    return 0


def _cmd_analyze(args) -> int:
    from . import capture_analyze as CA
    rep = CA.analyze(args.capture)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else CA.format_report(rep))
    return 0


def _cmd_scrub(args) -> int:
    from . import scrub as S
    return S.main([args.capture] + (["-o", args.out] if args.out else [])
                  + sum((["--value", v] for v in args.value), []))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="nwupdater-capture",
                                description="Capture/analyse des fonctions web NumWorks (non officiel).")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="page locale : bookmarklet + checklist + réception live")
    s.add_argument("--port", type=int, default=8766)
    s.add_argument("--out", help="fichier capture.json (mode live)")
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=_cmd_serve)

    a = sub.add_parser("analyze", help="analyser capture.json → carte d'API par fonctionnalité")
    a.add_argument("capture")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=_cmd_analyze)

    sc = sub.add_parser("scrub", help="caviarder email/série/jetons avant partage")
    sc.add_argument("capture")
    sc.add_argument("-o", "--out")
    sc.add_argument("--value", action="append", default=[])
    sc.set_defaults(func=_cmd_scrub)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

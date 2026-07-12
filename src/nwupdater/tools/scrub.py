"""Scrub personal data from a capture before sharing.

A real-account capture contains your email, calculator serial(s), and possibly script
contents. Secrets (password/CSRF/cookies) are already redacted by the hook/harness, but PII in
response bodies is not. This replaces sensitive values with **stable** placeholders
(``EMAIL_1``, ``SERIAL_1``, …) so the API *shapes* stay analysable while the *values* are gone.

Deterministic: the same value always maps to the same token (within a run), so cross-references
survive (e.g. a serial that appears in USB and in a web body maps to the same ``SERIAL_1``).

    python -m nwupdater.tools.scrub capture.json -o capture.scrubbed.json --value me@example.com
"""

from __future__ import annotations

import json
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# long opaque tokens that slipped through (base64/hex ≥ 40 chars) — belt and braces
_LONGTOK = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


class Scrubber:
    def __init__(self, extra_values=()):
        self._map: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        # user-supplied exact values (email, serial) get scrubbed first, as SERIAL/VALUE
        for v in extra_values:
            if v:
                self._token(v, "VALUE")

    def _token(self, value: str, kind: str) -> str:
        if value not in self._map:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            self._map[value] = f"{kind}_{self._counters[kind]}"
        return self._map[value]

    def text(self, s: str) -> str:
        if not isinstance(s, str) or not s:
            return s
        for v, tok in list(self._map.items()):    # explicit values first
            s = s.replace(v, tok)
        s = _EMAIL.sub(lambda m: self._token(m.group(), "EMAIL"), s)
        s = _LONGTOK.sub(lambda m: self._token(m.group(), "TOKEN"), s)
        return s

    def walk(self, obj):
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, list):
            return [self.walk(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.walk(v) for k, v in obj.items()}
        return obj

    @property
    def mapping(self) -> dict:
        return dict(self._map)


def scrub(obj, extra_values=()):
    """Return (scrubbed_obj, value→token mapping)."""
    s = Scrubber(extra_values)
    return s.walk(obj), s.mapping


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m nwupdater.tools.scrub",
        description="Caviarde les données personnelles d'une capture (projet non officiel).")
    p.add_argument("capture", help="capture.json à nettoyer")
    p.add_argument("-o", "--out", help="fichier de sortie (défaut: <capture>.scrubbed.json)")
    p.add_argument("--value", action="append", default=[],
                   help="valeur exacte à caviarder (email, n° de série) ; répétable")
    p.add_argument("--mapping", action="store_true", help="afficher la table valeur→jeton")
    args = p.parse_args(argv)

    with open(args.capture, encoding="utf-8") as f:
        obj = json.load(f)
    scrubbed, mapping = scrub(obj, extra_values=args.value)
    out = args.out or (args.capture.rsplit(".", 1)[0] + ".scrubbed.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(scrubbed, f, ensure_ascii=False, indent=2)
    print(f"caviardé → {out}  ({len(mapping)} valeur(s) remplacée(s))")
    if args.mapping:
        for v, tok in mapping.items():
            print(f"  {tok} ← {v[:12]}…" if len(v) > 12 else f"  {tok} ← {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

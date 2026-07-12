"""Rafraîchir les fixtures depuis my.numworks.com (à lancer manuellement, pas en CI).

Identifiants lus dans l'environnement (jamais en dur) :
    NWUPDATER_EMAIL=… NWUPDATER_PASSWORD=… python3 tests/fixtures/refresh.py

Ne stocke NI le jeton NI un firmware complet : uniquement la structure du formulaire (CSRF
redacté) et les manifestes JSON (métadonnées non secrètes).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
from nwupdater.catalog import auth as A  # noqa: E402
from nwupdater.catalog import download as D  # noqa: E402

HERE = Path(__file__).parent
MODELS = ("n0110", "n0200")


def main() -> int:
    email = os.environ.get("NWUPDATER_EMAIL")
    password = os.environ.get("NWUPDATER_PASSWORD")
    if not (email and password):
        print("Définissez NWUPDATER_EMAIL et NWUPDATER_PASSWORD.", file=sys.stderr)
        return 2

    tr = A.UrllibTransport()
    html = tr.open("GET", A.SIGNIN_URL, headers={"User-Agent": A.UA}).body.decode("utf-8", "replace")
    m = re.search(r'<input[^>]*name="authenticity_token"[^>]*>', html)
    snippet = re.sub(r'value="[^"]+"', 'value="REDACTED_CSRF_TOKEN"', m.group(0) if m else "")
    (HERE / "signin_form.html").write_text(snippet + "\n", encoding="utf-8")

    auth = A.login_with_password(email, password, transport=tr)  # jeton gardé en mémoire seulement
    for model in MODELS:
        raw = D._get(D.manifest_url(model, "stable"), auth, transport=tr).body
        (HERE / f"manifest_{model}_stable.json").write_bytes(raw)
        print(f"ok {model}: {D.FirmwareManifest.from_json(model, 'stable', raw).version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

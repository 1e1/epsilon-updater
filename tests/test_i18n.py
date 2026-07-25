"""Guard the web UI localization table (``server/web/i18n.js``).

The keys are kept sorted and in the SAME order across the FR and EN blocks so a missing or
mismatched translation shows up as a one-line diff. These tests turn that convention into a
CI failure instead of a manual review, and also flag any ``t("key")`` used by ``app.js`` that
has no entry at all.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "src" / "nwupdater" / "server" / "web"


def _keys(lang: str) -> list[str]:
    txt = (WEB / "i18n.js").read_text(encoding="utf-8")
    m = re.search(rf"\n  {lang}: \{{\n(.*?)\n  \}},", txt, re.DOTALL)
    assert m, f"{lang} block not found in i18n.js"
    return re.findall(r"^    ([A-Za-z_][A-Za-z0-9_]*):", m.group(1), re.MULTILINE)


def test_fr_en_identical_key_order() -> None:
    fr, en = _keys("fr"), _keys("en")
    assert fr == en, "FR and EN keys differ in set or order — a translation is missing/misplaced"


def test_keys_sorted() -> None:
    for lang in ("fr", "en"):
        keys = _keys(lang)
        assert keys == sorted(keys), f"{lang} keys are not alphabetically sorted"


def test_one_key_per_line_no_duplicates() -> None:
    for lang in ("fr", "en"):
        keys = _keys(lang)
        assert len(keys) == len(set(keys)), f"duplicate key in {lang} block"


def test_every_key_used_by_app_is_translated() -> None:
    known = set(_keys("fr"))
    app = (WEB / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r"""\bt\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""", app))
    missing = sorted(used - known)
    assert not missing, f"keys used in app.js but absent from i18n.js: {missing}"

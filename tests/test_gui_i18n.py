"""FR/EN parity for the native UI, and the guarantee that every label it draws resolves.

Reads the JSON assets directly, so it runs whether or not PySide6 is installed: a missing
translation must fail the build, not surface as a raw key in a teacher's classroom.
"""

import json
import re
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "nwupdater" / "gui" / "assets"
QML = Path(__file__).resolve().parents[1] / "src" / "nwupdater" / "gui" / "qml"
LANGS = ("fr", "en")


def load(name: str) -> dict:
    return json.loads((ASSETS / name).read_text(encoding="utf-8"))


def merged() -> dict[str, dict[str, str]]:
    shared, overlay = load("i18n.json"), load("i18n-gui.json")
    return {lang: {**shared[lang], **overlay[lang]} for lang in LANGS}


def test_shared_dictionary_is_the_web_one():
    """``i18n.json`` is generated from ``server/web/i18n.js`` — one dictionary, two front-ends."""
    shared = load("i18n.json")
    assert set(shared) == set(LANGS)
    assert set(shared["fr"]) == set(shared["en"])


def test_overlay_only_adds_what_the_native_shell_needs():
    overlay = load("i18n-gui.json")
    assert set(overlay["fr"]) == set(overlay["en"])
    assert overlay["fr"], "the overlay should not be empty"


@pytest.mark.parametrize("lang", LANGS)
def test_no_empty_translations(lang):
    assert [k for k, v in merged()[lang].items() if not v.strip()] == []


def test_every_key_used_in_qml_exists_in_both_languages():
    used = set()
    for qml in QML.glob("*.qml"):
        used |= set(re.findall(r'i18n\.t\(\s*"([^"]+)"', qml.read_text(encoding="utf-8")))
    assert used, "no i18n call found — the scan is broken, not the translations"
    strings = merged()
    for lang in LANGS:
        assert sorted(used - set(strings[lang])) == []


def test_placeholders_match_across_languages():
    """A `{name}` present in one language and missing in the other silently drops data."""
    strings = merged()
    for key, french in strings["fr"].items():
        english = strings["en"].get(key, "")
        assert set(re.findall(r"\{(\w+)\}", french)) == set(re.findall(r"\{(\w+)\}", english)), key


# -- the status line --------------------------------------------------------------------
BACKEND = Path(__file__).resolve().parents[1] / "src" / "nwupdater" / "gui" / "backend.py"
# `self.toast.emit("key", {"a": …, "b": …}, flag)` — the key and its placeholder names.
TOAST = re.compile(r'self\.toast\.emit\(\s*"(\w+)"\s*,\s*\{(.*?)\}', re.DOTALL)


def emitted_toasts() -> dict[str, set[str]]:
    source = BACKEND.read_text(encoding="utf-8")
    found: dict[str, set[str]] = {}
    for key, params in TOAST.findall(source):
        found.setdefault(key, set()).update(re.findall(r'"(\w+)"\s*:', params))
    assert found, "no toast found — the scan is broken, not the backend"
    return found


def test_every_toast_key_resolves_in_both_languages():
    """The status bar renders `i18n.t(key, params)`. A key with no entry falls back to the key
    itself, which is how a teacher ended up reading `install_ok::20.4.0` on screen."""
    strings = merged()
    missing = {
        lang: sorted(k for k in emitted_toasts() if k not in strings[lang]) for lang in LANGS
    }
    assert missing == {"fr": [], "en": []}


def test_every_toast_supplies_the_placeholders_its_string_needs():
    """`already_staged` is "« {name} » est déjà dans le plan." — emitting it without `name`
    leaves the braces on screen."""
    strings = merged()
    for key, supplied in emitted_toasts().items():
        for lang in LANGS:
            needed = set(re.findall(r"\{(\w+)\}", strings[lang][key]))
            assert needed <= supplied, f"{key} ({lang}) needs {sorted(needed - supplied)}"


def test_the_relative_time_keys_exist_for_every_bucket():
    """`format.relative_key` can only ever return these five."""
    strings = merged()
    for key in ("rel_never", "rel_now", "rel_min", "rel_hour", "rel_day"):
        for lang in LANGS:
            assert strings[lang].get(key), f"{key} missing in {lang}"

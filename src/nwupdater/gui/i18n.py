"""FR/EN strings, shared with the web UI.

``assets/i18n.json`` is generated from ``server/web/i18n.js`` so both front-ends read the
same dictionary — one source of truth, and ``tests/test_i18n.py``'s parity invariant keeps
holding. Placeholders use the web syntax: ``{name}``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

_ASSETS = Path(__file__).with_name("assets")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def load_strings() -> dict[str, dict[str, str]]:
    """Shared web dictionary, overlaid with the strings only the native shell needs
    (menus, keyboard affordances). Keeping the overlay separate means ``i18n.json`` can be
    regenerated from ``i18n.js`` without hand-merging."""
    strings = json.loads((_ASSETS / "i18n.json").read_text(encoding="utf-8"))
    overlay = json.loads((_ASSETS / "i18n-gui.json").read_text(encoding="utf-8"))
    for lang, extra in overlay.items():
        strings.setdefault(lang, {}).update(extra)
    return strings


class I18n(QObject):
    """Exposed to QML as ``i18n``. Every label binds to ``i18n.t("key")``.

    ``t`` is a slot, and a QML binding only re-evaluates when a *property* it read changes — a
    slot call creates no dependency. So switching language does NOT invalidate those bindings on
    its own, whatever this docstring used to claim: labels stayed in the old language and the
    menu only decided what the next launch would look like. What makes it work is
    :func:`~nwupdater.gui.app.install_context`, which re-sets the context property on
    ``langChanged`` — the documented way to invalidate every binding that references it.
    """

    langChanged = Signal()

    def __init__(self, lang: str = "fr", parent: QObject | None = None):
        super().__init__(parent)
        self._s = load_strings()
        self._lang = lang if lang in self._s else "fr"

    def _lang_get(self) -> str:
        return self._lang

    def _lang_set(self, value: str) -> None:
        if value in self._s and value != self._lang:
            self._lang = value
            self.langChanged.emit()

    lang = Property(str, _lang_get, _lang_set, notify=langChanged)

    @Slot(str, result=str)
    @Slot(str, "QVariantMap", result=str)
    def t(self, key: str, params: dict | None = None) -> str:
        text = self._s[self._lang].get(key) or self._s["en"].get(key) or key
        if params:
            text = _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)
        return text

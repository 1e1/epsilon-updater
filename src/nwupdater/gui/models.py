"""List models for the QML views.

Why a real model rather than handing QML a plain array: the web UI rebuilds whole panes with
``innerHTML`` on every state change, which throws away scroll position and focus. A model that
updates *in place* when the rows are the same keeps both — that is optimisation 1 of
``docs/05-packaging-ui/native-ui-zoning.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Slot,
)

_BASE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class RowsModel(QAbstractListModel):
    """Rows of dicts, one QML role per declared field.

    ``set_rows`` diffs against the current content: identical keys in identical order emit
    ``dataChanged`` for the rows that actually changed (view state survives); any structural
    difference falls back to a reset.
    """

    def __init__(self, fields: Sequence[str], key: str = "name", parent=None):
        super().__init__(parent)
        self._fields = list(fields)
        self._key = key
        self._rows: list[dict[str, Any]] = []
        self._roles = {_BASE_ROLE + i: f for i, f in enumerate(self._fields)}

    # -- QAbstractListModel ---------------------------------------------------------
    def roleNames(self) -> dict[int, QByteArray]:
        return {r: QByteArray(n.encode()) for r, n in self._roles.items()}

    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        # Anything raised here escapes through a C++ virtual call — Qt has no way to unwind it,
        # and the scene dies later with a bare segfault. Keep this total.
        if not index.isValid() or role not in self._roles:
            return None
        row = index.row()
        if not (0 <= row < len(self._rows)):
            return None
        return self._rows[row].get(self._roles[role])

    # -- updates --------------------------------------------------------------------
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        rows = [dict(r) for r in rows]
        same_shape = len(rows) == len(self._rows) and all(
            a.get(self._key) == b.get(self._key) for a, b in zip(rows, self._rows)
        )
        if same_shape:
            for i, (new, old) in enumerate(zip(rows, self._rows)):
                if new != old:
                    self._rows[i] = new
                    idx = self.index(i, 0)
                    self.dataChanged.emit(idx, idx, list(self._roles))
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict:
        return self._rows[row] if 0 <= row < len(self._rows) else {}

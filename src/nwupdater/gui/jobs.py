"""Running one blocking core call off the GUI thread.

Every ``Session`` method is synchronous and serialised by the session's own I/O lock. Calling
one straight from a QML handler would freeze the window for the whole of a flash, so each goes
through :class:`JobRunner`.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    """One off-thread call.

    ``setAutoDelete(False)`` plus the runner's strong reference are load-bearing. With
    auto-delete on, C++ destroys the runnable — and the signal object it owns — the moment
    ``run`` returns, which is *before* Qt dispatches the queued completion: the call then
    succeeds in silence and the UI stays "busy" forever.
    """

    def __init__(self, fn: Callable[[], Any], on_done, on_error, owner: QObject):
        super().__init__()
        self.setAutoDelete(False)
        self._fn = fn
        self._signals = _JobSignals(owner)
        self._signals.done.connect(on_done)
        self._signals.failed.connect(on_error)

    def run(self) -> None:  # pragma: no cover - thread body
        try:
            self._signals.done.emit(self._fn())
        except Exception as exc:  # reported in the UI; the app stays up
            traceback.print_exc()
            self._signals.failed.emit(str(exc) or exc.__class__.__name__)


class JobRunner:
    """Keeps in-flight jobs alive until Qt has delivered their result."""

    def __init__(self, owner: QObject, max_threads: int = 2):
        self._owner = owner
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max_threads)
        self._inflight: set[_Job] = set()

    def submit(self, fn: Callable[[], Any], on_done, on_error) -> None:
        holder: list[_Job] = []

        def release() -> None:
            self._inflight.discard(holder[0])

        def done(result: Any) -> None:
            release()
            on_done(result)

        def failed(message: str) -> None:
            release()
            on_error(message)

        job = _Job(fn, done, failed, self._owner)
        holder.append(job)
        self._inflight.add(job)
        self._pool.start(job)

    @property
    def busy_count(self) -> int:
        return len(self._inflight)

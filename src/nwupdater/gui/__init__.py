"""Native desktop UI (Qt Quick) — the V3 shell around the headless core.

The core is untouched: this package drives :class:`nwupdater.server.session.Session` **directly**,
with no local HTTP server in between. Rationale and measurements:
``docs/05-packaging-ui/native-ui-feasibility.md`` and ``native-ui-zoning.md``.

Layering (top depends on bottom, never the reverse)::

    qml/                Presentation. Bindings and gestures only — no rule lives here.
    backend.py          The single QObject. Properties, slots, signals; delegates everything.
    jobs.py             Runs one blocking core call off the GUI thread.
    models.py           List models that update rows in place (scroll and focus survive).
    workshop.py         Staging projected into rows            }  pure Python:
    roster.py           Fleet, classes and distribution views  }  no Qt, no I/O,
    plan.py             The memory write plan                  }  unit-tested in
    format.py           Byte sizes and relative times          }  tests/test_gui_*.py
    i18n.py             FR/EN strings, shared with the web UI.

Everything that can be decided without a window is decided below ``backend.py``, so the rule that
matters most — which bytes actually get rewritten — is testable without Qt at all.

Two rules the layering exists to keep, both of which were broken once and are now tested:

* **No device I/O on the GUI thread — reads included.** ``Backend.refresh`` gathers the whole
  inventory in a worker and hands back one snapshot; the GUI thread only assigns it. The first
  version did this inline, so the window appeared only after the calculator had been read and
  froze for every hot-plug poll.
* **Nothing crosses into QML already translated.** The backend emits i18n *keys* — row fields,
  toast messages, relative times — and QML renders them. A sentence formatted down here freezes
  the UI in one language; that is how the roster's last-scan column stayed French in English.
"""

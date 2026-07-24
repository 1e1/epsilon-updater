"""Session layer: holds a connected calculator (virtual by default) and exposes the Lot 2/3/4
operations as plain dicts for the local HTTP API.

The implementation is split by responsibility across a shared base and concern mixins; ``Session``
composes them so the public method surface is one flat, stable API.
"""

from __future__ import annotations

from ._session_apps import AppsMixin
from ._session_auth import AuthMixin
from ._session_base import SessionBase
from ._session_catalog import CatalogMixin
from ._session_firmware import FirmwareMixin
from ._session_scripts import ScriptsMixin


class Session(CatalogMixin, AppsMixin, AuthMixin, FirmwareMixin, ScriptsMixin, SessionBase):
    """The updater session: device lifecycle + catalogue + apps + auth + firmware + scripts."""

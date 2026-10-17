"""Suite-wide guard: the tests never reach a real calculator.

``usbio.open_calculator`` is the single door to real hardware. Left open, any test that drops
its demo device lets the hot-plug probe (or a rescan) open whatever calculator is plugged into
the developer's machine and hold it for the rest of the run, so a teacher's window running next
to the suite gets "Access denied" on its own calculator.

What still goes through is how the USB layer itself is tested: fakes injected as
``core``/``util``, a fake ``usb`` package installed in ``sys.modules`` (a real pyusb module has a
``__file__``, a stand-in built with ``types.ModuleType`` does not), and a run without pyusb.
"""

import pytest

from nwupdater.dfu import usbio


@pytest.fixture(autouse=True)
def _no_real_usb(monkeypatch):
    real = usbio.open_calculator

    def guarded(core=None, util=None, **kw):
        if core is None or util is None:
            try:
                import usb.core
            except ImportError:
                return real(core, util, **kw)  # no pyusb: nothing to protect
            if getattr(usb.core, "__file__", None) is not None:
                raise usbio.NoCalculatorFound("real USB is disabled under the test suite")
        return real(core, util, **kw)

    monkeypatch.setattr(usbio, "open_calculator", guarded)


@pytest.fixture(autouse=True)
def _isolated_user_dirs(tmp_path_factory, monkeypatch):
    """Suite-wide guard: the tests never touch the developer's own files.

    A test that forgets its own isolation (a server fixture calling ``/api/auth/logout``) used to
    delete the real ``~/.config/nwupdater/credentials.json``. Every user directory the package
    reads points into a per-test temporary one; a test still sets its own on top when it needs to.
    """
    home = tmp_path_factory.mktemp("user")
    for var, sub in (
        ("NWUPDATER_CONFIG_DIR", "config/nwupdater"),
        ("NWUPDATER_APPS_DIR", "config/nwupdater/apps"),
        ("NWUPDATER_SCRIPTS_DIR", "config/nwupdater/scripts"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        monkeypatch.setenv(var, str(home / sub))

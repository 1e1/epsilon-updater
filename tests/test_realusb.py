"""Real-hardware USB acquisition (dfu/usbio.py) — driven with FAKE pyusb modules.

No pyusb, no device: we inject fake ``core``/``util`` objects mirroring the small pyusb API
surface used. Confirms device selection, DFU-interface detection, claim, alt-setting, error
paths, and that DfuClient threads the interface number into the control-transfer wIndex.
"""

import pytest

from nwupdater.dfu import constants as C
from nwupdater.dfu import usbio
from nwupdater.dfu.protocol import DfuClient


# -- fake pyusb ------------------------------------------------------------------------
class FakeInterface:
    def __init__(self, cls, sub, number=0, alt=0, iInterface=0):
        self.bInterfaceClass = cls
        self.bInterfaceSubClass = sub
        self.bInterfaceNumber = number
        self.bAlternateSetting = alt
        self.iInterface = iInterface


class FakeConfig:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class FakeDevice:
    def __init__(self, bcd, interfaces, *, id_product=0):
        self.bcdDevice = bcd
        self.idProduct = id_product
        self._cfg = FakeConfig(interfaces)
        self.configured = False
        self.alt_set = None

    def set_configuration(self):
        self.configured = True

    def get_active_configuration(self):
        return self._cfg

    def set_interface_altsetting(self, *, interface, alternate_setting):
        self.alt_set = (interface, alternate_setting)


class FakeCore:
    def __init__(self, by_pid):
        self.by_pid = by_pid  # {pid: [FakeDevice, ...]}

    def find(self, *, find_all=False, idVendor=None, idProduct=None, backend=None):
        devs = self.by_pid.get(idProduct, [])
        return iter(devs) if find_all else (devs[0] if devs else None)


class FakeUtil:
    def __init__(self, *, fail=False):
        self.claims = []
        self.fail = fail

    def claim_interface(self, dev, number):
        if self.fail:
            raise OSError("Access denied (insufficient permissions)")
        self.claims.append((dev, number))


def _dfu_intf(number=0, iInterface=0):
    return FakeInterface(C.DFU_INTERFACE_CLASS, C.DFU_INTERFACE_SUBCLASS,
                         number=number, iInterface=iInterface)


# -- find_calculator -------------------------------------------------------------------
def test_finds_configures_and_claims_dfu_interface():
    dev = FakeDevice(0x0110, [FakeInterface(0xFF, 0x00, 0), _dfu_intf(0)], id_product=C.PID_EPSILON)
    core = FakeCore({C.PID_EPSILON: [dev]})
    util = FakeUtil()
    od = usbio.find_calculator(core, util)
    assert od.bcd_device == 0x0110
    assert od.interface == 0
    assert od.id_product == C.PID_EPSILON
    assert dev.configured is True
    assert dev.alt_set == (0, C.ALT_FLASH)
    assert util.claims == [(dev, 0)]


def test_pid_priority_prefers_bootloader_first():
    # both userland and ST bootloader present → picks the first in C.KNOWN_PIDS order
    ep = FakeDevice(0x0110, [_dfu_intf(0)], id_product=C.PID_EPSILON)
    bl = FakeDevice(0x0110, [_dfu_intf(0)], id_product=C.PID_ST_BOOTLOADER)
    core = FakeCore({C.PID_EPSILON: [ep], C.PID_ST_BOOTLOADER: [bl]})
    od = usbio.find_calculator(core, FakeUtil())
    assert od.id_product == C.KNOWN_PIDS[0]  # scan order honored


def test_non_zero_interface_number_is_reported():
    dev = FakeDevice(0x0120, [_dfu_intf(2)], id_product=C.PID_NW_BOOTLOADER)
    od = usbio.find_calculator(FakeCore({C.PID_NW_BOOTLOADER: [dev]}), FakeUtil())
    assert od.interface == 2


def test_no_calculator_raises_with_hint():
    with pytest.raises(usbio.NoCalculatorFound) as e:
        usbio.find_calculator(FakeCore({}), FakeUtil())
    assert "DFU" in str(e.value) or "bootloader" in str(e.value)


def test_no_dfu_interface_raises():
    dev = FakeDevice(0x0110, [FakeInterface(0xFF, 0x00, 0)])  # no DFU-class interface
    with pytest.raises(usbio.DfuInterfaceNotFound):
        usbio.find_calculator(FakeCore({C.PID_EPSILON: [dev]}), FakeUtil())


def test_claim_failure_raises_permission_hint():
    dev = FakeDevice(0x0110, [_dfu_intf(0)])
    with pytest.raises(usbio.InterfaceClaimError):
        usbio.find_calculator(FakeCore({C.PID_EPSILON: [dev]}), FakeUtil(fail=True))


# -- DfuClient threads interface into wIndex -------------------------------------------
class RecordingDev:
    idVendor = C.USB_VID
    idProduct = C.PID_EPSILON
    bcdDevice = 0x0110

    def __init__(self):
        self.calls = []

    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None):
        self.calls.append((bmRequestType, bRequest, wValue, wIndex))
        if bmRequestType == C.REQ_IN and bRequest == C.DFU_GETSTATE:
            return bytes([C.STATE_DFU_IDLE])
        return b""


def test_dfuclient_uses_given_interface_as_windex():
    dev = RecordingDev()
    DfuClient(dev, sleep=lambda *_: None, interface=3).get_state()
    assert dev.calls[-1][3] == 3  # wIndex == interface

    dev2 = RecordingDev()
    DfuClient(dev2, sleep=lambda *_: None).get_state()  # default
    assert dev2.calls[-1][3] == C.DFU_INTERFACE


# -- integration: drive the REAL code path against the virtual device ------------------
# We stub only the physical USB layer (a fake ``usb`` package) so _open_real_device ->
# usbio.find_calculator -> DfuClient run for real, delegating control transfers to the
# in-process virtual DFU device (full DfuSe state machine). No hardware, no pyusb.
class _VirtualUsbAdapter:
    def __init__(self, vdev):
        self._v = vdev
        self.idVendor = C.USB_VID
        self.idProduct = C.PID_EPSILON
        self.bcdDevice = vdev.bcdDevice

    def set_configuration(self):
        pass

    def get_active_configuration(self):
        # advertise the layout string index like real hardware, so usbio reads the flash
        # sector geometry through ctrl_transfer (forwarded to the virtual device).
        return FakeConfig([_dfu_intf(0, iInterface=self._v.iInterface)])

    def set_interface_altsetting(self, *, interface, alternate_setting):
        pass

    def ctrl_transfer(self, *a, **k):
        return self._v.ctrl_transfer(*a, **k)


def _install_fake_usb(monkeypatch, adapter):
    import sys
    import types
    usb = types.ModuleType("usb")
    core = types.ModuleType("usb.core")
    util = types.ModuleType("usb.util")

    def find(*, find_all=False, idVendor=None, idProduct=None):
        hit = idProduct == C.PID_EPSILON and idVendor == C.USB_VID
        if find_all:
            return iter([adapter] if hit else [])
        return adapter if hit else None

    core.find = find
    util.claim_interface = lambda dev, number: None
    usb.core = core
    usb.util = util
    monkeypatch.setitem(sys.modules, "usb", usb)
    monkeypatch.setitem(sys.modules, "usb.core", core)
    monkeypatch.setitem(sys.modules, "usb.util", util)


def test_real_path_identify_against_virtual_device(monkeypatch, capsys):
    from nwupdater import cli
    from nwupdater.testing.virtual_dfu import virtual_calculator

    vdev = virtual_calculator("n0110", os_version="23.2.4", commit="abc1234")
    _install_fake_usb(monkeypatch, _VirtualUsbAdapter(vdev))

    rc = cli.main(["identify"])  # no --virtual → REAL path through _open_real_device
    out = capsys.readouterr().out
    assert rc == 0
    assert "n0110" in out
    assert "23.2.4" in out


def test_real_install_requires_confirmation(monkeypatch, capsys):
    from nwupdater import cli
    from nwupdater.testing.virtual_dfu import virtual_calculator

    _install_fake_usb(monkeypatch, _VirtualUsbAdapter(virtual_calculator("n0110")))
    monkeypatch.setattr("builtins.input", lambda *a: "no")   # user declines
    rc = cli.main(["install", "--to-version", "25.2.0"])     # real path, no --yes
    assert rc == 1
    assert "cancelled" in capsys.readouterr().err


def test_real_install_with_yes_flashes_virtual_device(monkeypatch, capsys):
    from nwupdater import cli
    from nwupdater.testing.virtual_dfu import virtual_calculator

    _install_fake_usb(monkeypatch, _VirtualUsbAdapter(virtual_calculator("n0110", os_version="23.2.4")))
    rc = cli.main(["install", "--yes", "--to-version", "25.2.0"])  # real path, confirmation skipped
    out = capsys.readouterr().out
    assert rc == 0
    assert "25.2.0" in out  # synthetic image flashed to the inactive slot and read back


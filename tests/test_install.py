"""Lot 3 — install engine tests, all against the virtual device (no real USB)."""

import pytest

from nwupdater.dfu import constants as C
from nwupdater.dfu.protocol import DfuClient
from nwupdater.install.image import FirmwareImage
from nwupdater.install.installer import CompatibilityError, Installer, plan_install
from nwupdater.models import MODELS
from nwupdater.testing.virtual_dfu import virtual_calculator


def _model(name):
    return next(m for m in MODELS.values() if m.name == name)


def _client(dev):
    return DfuClient(dev, sleep=lambda *_: None)


def test_plan_ab_targets_inactive_slot():
    model = _model("n0110")
    img = FirmwareImage.synthetic(model, version="99.9.9")
    plan = plan_install(model, img, active_slot="A")
    assert plan.target_slot == "B"
    # external segment authored at slot A (0x90000000) remapped to slot B (0x90400000)
    assert plan.segments[0].address == 0x90400000
    assert plan.boot_address == 0x90410000


def test_install_synthetic_to_inactive_slot_and_verify():
    model = _model("n0110")
    dev = virtual_calculator("n0110", os_version="23.2.4")  # slot A has real OS
    cli = _client(dev)
    img = FirmwareImage.synthetic(model, version="99.9.9", commit="newos00")

    inst = Installer(cli, model)
    plan = inst.install(img, active_slot="A", verify=True)

    # the freshly flashed slot B carries the new version...
    assert inst.read_installed_version(plan) == "99.9.9"
    # ...and slot A (the still-active OS) is untouched
    a_userland = cli.read(0x90010000, C.USERLAND_HEADER_SIZE)
    from nwupdater.formats.headers import UserlandHeader

    assert UserlandHeader.unpack(a_userland).expected_software_version == "23.2.4"


def test_install_and_boot_leaves_to_bootloader():
    # Booting leaves to the bootloader (internal-flash base), NOT the flashed slot: a leave into a
    # QSPI slot boots it unauthenticated ("UNOFFICIAL SOFTWARE"). Leaving to 0x08000000 cold-boots
    # via the bootloader, which re-verifies the signature and keeps the device official.
    model = _model("n0110")
    dev = virtual_calculator("n0110")
    inst = Installer(_client(dev), model)
    img = FirmwareImage.synthetic(model, version="99.9.9")
    inst.install(img, active_slot="A", boot=True)
    assert dev.left is True
    assert dev.jump_address == C.BOOTLOADER_RESET_ADDRESS + C.USERLAND_HEADER_SIZE


def test_install_single_slot_scientific_n0200():
    model = _model("n0200")
    dev = virtual_calculator("n0200", os_version="1.0.0")
    inst = Installer(_client(dev), model)
    img = FirmwareImage.synthetic(model, version="1.1.0")
    plan = inst.install(img, verify=True)
    assert plan.target_slot is None
    assert inst.read_installed_version(plan) == "1.1.0"


def test_compatibility_rejects_wrong_model():
    model = _model("n0110")
    img = FirmwareImage.synthetic(_model("n0120"), version="99.9.9")  # bcd 0x0120
    inst = Installer(_client(virtual_calculator("n0110")), model)
    with pytest.raises(CompatibilityError):
        inst.install(img)


def test_progress_callback_invoked():
    model = _model("n0110")
    events = []
    inst = Installer(
        _client(virtual_calculator("n0110")),
        model,
        progress=lambda phase, d, t: events.append((phase, d, t)),
    )
    inst.install(FirmwareImage.synthetic(model, version="99.9.9"))
    assert any(e[0] == "write" for e in events)
    assert any(e[0] == "verify" for e in events)
    assert events[-1][1] == events[-1][2]  # done == total at the end


def test_dfuse_roundtrip():
    model = _model("n0110")
    img = FirmwareImage.synthetic(model, version="99.9.9")
    blob = img.to_dfuse()
    assert blob[:5] == b"DfuSe"
    parsed = FirmwareImage.from_dfuse(blob)
    assert parsed.bcd_device == 0x0110
    assert [(s.address, s.data) for s in parsed.segments] == [
        (s.address, s.data) for s in img.segments
    ]


def test_from_dfuse_truncated_raises_valueerror_not_structerror():
    # A truncated container must raise the module's own ValueError, never a bare struct.error.
    with pytest.raises(ValueError):
        FirmwareImage.from_dfuse(b"DfuSe\x01")  # prefix present, body missing
    good = FirmwareImage.synthetic(_model("n0110"), version="1.0.0").to_dfuse()
    with pytest.raises(ValueError):
        FirmwareImage.from_dfuse(good[:200])  # cut inside the target/element headers


def test_headers_unpack_short_buffer_is_invalid():
    # Malformed (too short) header buffers return valid=False instead of raising struct.error.
    from nwupdater.formats.headers import KernelHeader, SlotInfo, UserlandHeader

    assert SlotInfo.unpack(b"\x00\x00").valid is False
    assert KernelHeader.unpack(b"\xf0\x0d").valid is False
    assert UserlandHeader.unpack(b"\xfe\xed").valid is False

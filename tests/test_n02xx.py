"""N02xx (Scientifique) modeling: opaque/encrypted firmware, DFU base 0x98000000, no slots.

Reflects the reverse-engineering in docs/01-specs/n02xx-firmware-format.md. Offline, virtual
device only — no USB, no network. Uses deterministic header-free bytes to stand in for the
real encrypted payload (which carries no parseable structure).
"""

from nwupdater.dfu.protocol import DfuClient
from nwupdater.install.image import FirmwareImage, FirmwareSegment
from nwupdater.install.installer import Installer, plan_install
from nwupdater.models import MODELS
from nwupdater.testing.virtual_dfu import virtual_calculator

N0200 = MODELS[0x0200]
DFU_BASE = 0x98000000


def _opaque_bytes(n: int) -> bytes:
    # deterministic, high-variety, and guaranteed to contain none of the Epsilon header magics
    return bytes(((i * 37 + 11) ^ (i >> 3)) & 0xFF for i in range(n))


def test_n0200_is_modeled_as_opaque_single_slot():
    assert N0200.opaque_firmware is True
    assert N0200.family == "scientifique"
    assert N0200.memory.internal_flash_origin == DFU_BASE
    assert N0200.memory.external_flash_origin is None
    assert N0200.memory.has_ab_slots is False


def test_opaque_image_flashed_verbatim_with_no_boot():
    image = FirmwareImage([FirmwareSegment(DFU_BASE, _opaque_bytes(8192))], bcd_device=0x0000)
    plan = plan_install(N0200, image)
    assert plan.target_slot is None      # single-slot
    assert plan.full_image is False
    assert plan.boot_address is None     # opaque: nothing to jump to, no guessed offset
    assert [s.address for s in plan.segments] == [DFU_BASE]  # verbatim


def test_opaque_install_verifies_and_version_readback_is_none():
    dev = virtual_calculator("n0200")
    inst = Installer(DfuClient(dev, sleep=lambda *_: None), N0200)
    image = FirmwareImage([FirmwareSegment(DFU_BASE, _opaque_bytes(8192))], bcd_device=0x0000)
    plan = inst.install(image, verify=True)             # read-back verify must pass
    assert inst.read_installed_version(plan) is None    # no readable version in an opaque blob


class _RecClient:
    """Minimal DfuClient stand-in recording the erase flag of each write."""
    def __init__(self):
        self.writes = []

    def write(self, address, data, *, erase=False):
        self.writes.append(erase)

    def read(self, address, length):
        return b""

    def leave(self, jump_address):
        pass


def test_n0200_flash_issues_no_erase():
    # matches the official flasher: N0200 writes with NO DfuSe erase
    inst = Installer(_RecClient(), N0200)
    img = FirmwareImage([FirmwareSegment(DFU_BASE, _opaque_bytes(6144))], bcd_device=0x0000)
    inst.install(img, verify=False)
    assert inst.client.writes and all(e is False for e in inst.client.writes)


def test_n0110_flash_still_erases():
    inst = Installer(_RecClient(), MODELS[0x0110])
    img = FirmwareImage.synthetic(MODELS[0x0110], version="1.0.0")
    inst.install(img, verify=False)
    assert inst.client.writes and all(e is True for e in inst.client.writes)


def test_opaque_dfuse_roundtrip_is_compatible_with_n0200():
    # DfuSe like the official one: PID 0xA51A, generic bcdDevice 0x0000, element @0x98000000
    blob = FirmwareImage([FirmwareSegment(DFU_BASE, _opaque_bytes(4096))]).to_dfuse(
        id_product=0xA51A, bcd_device=0x0000)
    image = FirmwareImage.from_dfuse(blob)
    assert image.id_product == 0xA51A
    assert image.segments[0].address == DFU_BASE
    inst = Installer(DfuClient(virtual_calculator("n0200"), sleep=lambda *_: None), N0200)
    inst.check_compatibility(image)  # must not raise

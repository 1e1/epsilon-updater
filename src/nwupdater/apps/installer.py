"""Install a `.nwa` third-party app into the external-apps flash region (Lot 4).

Reuses the DFU write engine (Lot 3). Compatibility is checked client-side against the
device identity read over DFU: external-apps region geometry + API level + magic.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dfu.protocol import DfuClient
from ..formats.nwa import AppInfo, InstalledApp, iter_apps
from ..install.installer import VerificationError


def list_installed(client: DfuClient, region: tuple[int, int] | None) -> list[InstalledApp]:
    """Enumerate the apps currently installed in the external-apps zone (read-only UPLOAD)."""
    if not region:
        return []
    start, end = region
    if not start or end <= start:
        return []
    return iter_apps(client.read(start, end - start))


class AppCompatibilityError(RuntimeError):
    pass


# Best-effort EXTERNAL_APPS_API_LEVEL. The real value is compiled into the OS and enforced
# at runtime; it is not exposed in the headers we read over DFU. Callers may override.
DEFAULT_DEVICE_API_LEVEL = 0


def validate_nwa(
    blob: bytes, device_api_level: int, *, error: type[Exception] = AppCompatibilityError
) -> AppInfo:
    """Parse a ``.nwa`` blob and confirm it is installable here: valid AppInfo magic and an API
    level matching the device. Raises ``error(message)`` on any problem. Shared by
    :class:`AppInstaller` and :class:`~nwupdater.apps.manage.AppManager` so the check can't drift."""
    info = AppInfo.parse(blob)
    if not info.valid:
        if blob[:4] == b"\x7fELF":
            raise error(
                "this .nwa is a relocatable ELF and must be linked to the device's flash/RAM "
                "addresses before install (see nwupdater.apps.link); a raw ELF is not flashable"
            )
        raise error("invalid AppInfo magic (not a .nwa)")
    if info.api_level != device_api_level:
        raise error(f"API level {info.api_level} != device {device_api_level}")
    return info


def write_verified(client: DfuClient, address: int, blob: bytes, *, erase: bool) -> None:
    """Write ``blob`` at ``address``, then read it back and raise :class:`VerificationError` on
    mismatch. The single verified-write behind every app-install path."""
    client.write(address, blob, erase=erase)
    if client.read(address, len(blob)) != blob:
        raise VerificationError(f"read-back mismatch @0x{address:08x}")


@dataclass
class AppInstallResult:
    name: str
    address: int
    size: int
    api_level: int


class AppInstaller:
    def __init__(
        self,
        client: DfuClient,
        *,
        external_apps_flash: tuple[int, int],
        device_api_level: int = DEFAULT_DEVICE_API_LEVEL,
    ):
        self.client = client
        self.region = external_apps_flash
        self.device_api_level = device_api_level

    @property
    def region_size(self) -> int:
        start, end = self.region
        return max(0, end - start)

    def check(self, blob: bytes, *, at_offset: int = 0) -> AppInfo:
        if self.region_size == 0:
            raise AppCompatibilityError("this model has no external-apps region")
        info = validate_nwa(blob, self.device_api_level)
        if at_offset + len(blob) > self.region_size:
            raise AppCompatibilityError(
                f"not enough space ({len(blob)} B at offset {at_offset}, "
                f"region {self.region_size} B)"
            )
        return info

    def install(self, blob: bytes, *, at_offset: int = 0, verify: bool = True) -> AppInstallResult:
        info = self.check(blob, at_offset=at_offset)
        address = self.region[0] + at_offset
        if verify:
            write_verified(self.client, address, blob, erase=True)
        else:
            self.client.write(address, blob, erase=True)
        return AppInstallResult(info.name or "?", address, len(blob), info.api_level)

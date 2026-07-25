"""Effective per-device feature capabilities — a single resolver.

The CLI, the local server and the web UI need to know what a connected calculator can actually
do (update firmware, run third-party ``.nwa`` apps, hold Python scripts, …). That decision used
to be re-derived in several places from ``family == "..."`` string checks and ad-hoc device-field
probes. This module centralises it.

Three inputs combine with a logical AND — a capability holds only if all three allow it:

  - **structural** — what the hardware model supports, from the model registry alone
    (``Capabilities.structural``). Authoritative and never overridable: flipping one of these on
    unsupported hardware is a brick risk, so a config layer must not be able to grant them.
  - **observed** — what the *connected* device actually exposes (regions/headers read over DFU,
    carried by a :class:`~nwupdater.dfu.identity.CalculatorIdentity`).
  - **policy** — UX choices layered on top (e.g. classroom mode hides the apps/scripts workshops
    even on capable hardware). Safe to toggle; can only ever *remove* a capability.

See docs and the model registry (:mod:`nwupdater.models`) for the hardware facts behind each flag.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .dfu.identity import CalculatorIdentity
from .models import Model


@dataclass(frozen=True)
class Policy:
    """UX overlay on top of the hardware capabilities. Never grants what the hardware lacks."""

    classroom: bool = False  # fleet management only: hide the per-device apps/scripts workshops


@dataclass(frozen=True)
class Capabilities:
    """Effective feature set for a device. All flags default off (the safe unknown-device value)."""

    firmware_update: bool = False
    firmware_readable: bool = (
        False  # plaintext SlotInfo/Kernel/Userland headers (False on opaque N02xx)
    )
    ab_slots: bool = False  # A/B slot layout for atomic updates
    external_apps: bool = False  # third-party ``.nwa`` apps (needs external QSPI flash)
    scripts: bool = False  # Python scripts in RAM storage

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def structural(cls, model: Model | None) -> Capabilities:
        """What the hardware supports, from the registry alone — no connected device required.

        Returns the all-off default for an unknown model (assume nothing rather than guess)."""
        if model is None:
            return cls()
        mem = model.memory
        return cls(
            firmware_update=True,  # every known model is flashable over DFU
            firmware_readable=not model.opaque_firmware,
            ab_slots=mem.has_ab_slots,
            external_apps=mem.external_flash_origin is not None,
            scripts=not model.opaque_firmware and model.family == "graphique",
        )


def resolve(
    model: Model | None,
    identity: CalculatorIdentity | None = None,
    policy: Policy | None = None,
) -> Capabilities:
    """Effective capabilities = structural(model) ∧ observed(identity) ∧ policy.

    ``identity`` refines the structural set with what the connected device actually exposes; pass
    ``None`` to skip that step (e.g. before any device has been read). ``policy`` defaults to no
    overlay. A capability the hardware lacks can never be turned on by ``identity`` or ``policy``.
    """
    structural = Capabilities.structural(model)
    policy = policy or Policy()

    external_apps = structural.external_apps
    scripts = structural.scripts

    if identity is not None:
        region = identity.external_apps_flash
        external_apps = external_apps and bool(region and region != (0, 0))
        scripts = scripts and bool(identity.storage_ram)

    if policy.classroom:
        external_apps = False
        scripts = False

    return Capabilities(
        firmware_update=structural.firmware_update,
        firmware_readable=structural.firmware_readable,
        ab_slots=structural.ab_slots,
        external_apps=external_apps,
        scripts=scripts,
    )

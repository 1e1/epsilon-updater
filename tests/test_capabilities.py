"""Device capability resolver: structural ∧ observed ∧ policy."""

from nwupdater.capabilities import Capabilities, Policy, resolve
from nwupdater.dfu.identity import CalculatorIdentity
from nwupdater.models import MODELS
from nwupdater.server.session import Session


def _ident(model, *, region=None, storage=None):
    return CalculatorIdentity(
        bcd_device=model.bcd_device,
        model=model,
        model_name=model.name,
        family=model.family,
        external_apps_flash=region,
        storage_ram=storage,
    )


# -- structural (hardware only) ---------------------------------------------------
def test_structural_graphing_full():
    caps = Capabilities.structural(MODELS[0x0110])
    assert caps.firmware_update and caps.firmware_readable and caps.ab_slots
    assert caps.external_apps and caps.scripts


def test_structural_scientific_is_opaque_and_bare():
    caps = Capabilities.structural(MODELS[0x0200])
    assert caps.firmware_update  # still flashable
    assert not caps.firmware_readable  # encrypted N02xx blob
    assert not caps.ab_slots and not caps.external_apps and not caps.scripts


def test_structural_n0100_has_no_qspi():
    caps = Capabilities.structural(MODELS[0x0100])
    assert caps.firmware_update and caps.firmware_readable and caps.scripts
    assert not caps.ab_slots and not caps.external_apps  # no external flash


def test_unknown_model_is_all_off():
    assert resolve(None) == Capabilities()


# -- observed refinement ----------------------------------------------------------
def test_observed_gates_structural_capabilities():
    m = MODELS[0x0110]
    bare = resolve(m, _ident(m, region=(0, 0), storage=None))
    assert (
        not bare.external_apps and not bare.scripts
    )  # hardware-capable but device exposes neither
    full = resolve(m, _ident(m, region=(0x90400000, 0x90800000), storage=(0x20000000, 0x10000)))
    assert full.external_apps and full.scripts


def test_observed_cannot_grant_beyond_hardware():
    m = MODELS[0x0200]  # scientific: no apps/scripts, whatever it claims to expose
    caps = resolve(m, _ident(m, region=(1, 2), storage=(3, 4)))
    assert not caps.external_apps and not caps.scripts


# -- policy overlay ---------------------------------------------------------------
def test_classroom_policy_masks_workshops_but_keeps_updates():
    m = MODELS[0x0110]
    ident = _ident(m, region=(0x90400000, 0x90800000), storage=(0x20000000, 0x10000))
    caps = resolve(m, ident, Policy(classroom=True))
    assert not caps.external_apps and not caps.scripts
    assert caps.firmware_update and caps.firmware_readable


# -- parity: every registered model resolves --------------------------------------
def test_every_registered_model_resolves():
    for model in MODELS.values():
        structural = Capabilities.structural(model)
        assert structural.firmware_update  # every known model is flashable
        assert resolve(model).to_dict().keys() == structural.to_dict().keys()


# -- integration: the session seam ------------------------------------------------
def test_session_identity_exposes_capabilities():
    caps = Session(model_name="n0110").identity()["capabilities"]
    assert caps["external_apps"] and caps["scripts"] and caps["firmware_readable"]


def test_session_classroom_policy_hides_scripts_and_apps():
    s = Session(model_name="n0110")
    assert s.scripts()["has_scripts"] and s.apps()["has_external_apps"]
    s.policy = Policy(classroom=True)
    assert s.scripts()["has_scripts"] is False
    assert s.apps()["has_external_apps"] is False
    assert s.identity()["capabilities"]["firmware_update"] is True

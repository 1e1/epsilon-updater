"""Model registry helpers, including the unknown-device path."""

from nwupdater.models import MODELS, describe_bcd, family_for_bcd, model_for_bcd


def test_describe_known_and_unknown():
    assert "n0110" in describe_bcd(0x0110)
    unknown = describe_bcd(0x0999)
    assert "n0999" in unknown and "unknown" in unknown  # not in the registry


def test_family_for_bcd_ranges():
    assert family_for_bcd(0x0110) == "graphique"
    assert family_for_bcd(0x0200) == "scientifique"
    assert family_for_bcd(0x9999) == "unknown"


def test_model_for_bcd():
    assert model_for_bcd(0x0110) is MODELS[0x0110]
    assert model_for_bcd(0x0999) is None

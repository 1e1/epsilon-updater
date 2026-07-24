"""Session auth wrappers (login_token / auth_status / logout / _serial) — offline, isolated
config dir so nothing touches the real ~/.config."""

import base64
import json

import pytest

from nwupdater.catalog import auth as A
from nwupdater.server.session import Session


def _token(exp_iso="2099-01-01T00:00:00.000Z"):
    payload = {"_rails": {"message": "W1td", "exp": exp_iso, "pur": A.REMEMBER_PURPOSE}}
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"{b64}--deadbeefsignature"


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path / "cfg"))


def test_auth_status_signed_out():
    st = Session(model_name="n0110").auth_status()
    assert st["authenticated"] is False and st["expired"] is False and st["expires_at"] is None


def test_login_token_then_status_then_logout():
    s = Session(model_name="n0110")
    assert s.login_token(_token())["authenticated"] is True
    assert s.auth_status()["authenticated"] is True  # round-trips through the on-disk token
    assert s.logout()["authenticated"] is False
    assert s.auth_status()["authenticated"] is False


def test_login_token_rejects_empty():
    with pytest.raises(ValueError, match="empty token"):
        Session(model_name="n0110").login_token("   ")


def test_login_token_expired_is_reported():
    st = Session(model_name="n0110").login_token(_token(exp_iso="2000-01-01T00:00:00.000Z"))
    assert st["authenticated"] is False and st["expired"] is True


def test_serial_read_from_virtual_device():
    serial = Session(model_name="n0110")._serial()
    assert serial and len(serial) == 16

"""§FIRSTHOUR (2026-09-03) — the console a PERSON is sent to (core/public_url.py).

registry-a's base is api.theprotocol.cloud but its people arrive from the apex, which serves
the app at ``/``; ``PUBLIC_UI_URL`` names that console. Unset, the console is ``<base>/ui``;
unknown, links fall back to the relative ``/#/<route>`` (a registry root 301s to /ui)."""
from agentvault_registry.core import public_url as pu


def test_console_defaults_to_base_plus_ui(monkeypatch):
    monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
    monkeypatch.setattr(pu, "public_base_url_static", lambda: "https://frame-c.theprotocol.cloud")
    assert pu.public_ui_url_static() == "https://frame-c.theprotocol.cloud/ui"
    assert pu.public_ui_origin() == "https://frame-c.theprotocol.cloud"
    # the 303 stays RELATIVE unless the console is named: the person stays on the host they typed
    assert pu.spa_url("email-verification?status=success") == "/#/email-verification?status=success"


def test_public_ui_url_names_the_apex(monkeypatch):
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud/")
    monkeypatch.setattr(pu, "public_base_url_static", lambda: "https://api.theprotocol.cloud")
    assert pu.public_ui_url_static() == "https://theprotocol.cloud"
    assert pu.public_ui_origin() == "https://theprotocol.cloud"
    assert pu.spa_url("email-verification?status=success&already=true") == "https://theprotocol.cloud/#/email-verification?status=success&already=true"


def test_loopback_console_is_rejected_and_unknown_falls_back_to_relative(monkeypatch):
    monkeypatch.setenv("PUBLIC_UI_URL", "http://localhost:5173")
    monkeypatch.setattr(pu, "public_base_url_static", lambda: None)
    assert pu.public_ui_url_static() is None
    assert pu.spa_url("email-verification?status=failed&reason=expired") == "/#/email-verification?status=failed&reason=expired"


def test_operator_machine_address_never_leaks_into_a_human_link(monkeypatch):
    """Our cloud operators carry PUBLIC_URL with the external mTLS port (measured dead for a browser)."""
    monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
    monkeypatch.setattr(pu, "public_base_url_static", lambda: "https://op-berlin.op.theprotocol.cloud:27543")
    assert pu.spa_url("email-verification?status=success") == "/#/email-verification?status=success"
    monkeypatch.setenv("PUBLIC_UI_URL", "https://op-berlin.op.theprotocol.cloud")
    assert pu.public_ui_origin() == "https://op-berlin.op.theprotocol.cloud"
    assert pu.spa_url("x") == "https://op-berlin.op.theprotocol.cloud/#/x"


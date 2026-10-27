"""§FESUITE (2026-10-10): the organization invitation mail's link names the console the invited person uses.

It was BASE_URL + "/ui": on EU that is https://eu.theprotocol.cloud/ui (a console of its own, 200), while EU's members
sign in on the apex (PUBLIC_UI_URL=https://theprotocol.cloud), so an invited member arrived on a host where they were
not signed in (sessions are per host). The verify and reset mails were moved to the console address at §FIRSTHOUR; this
mail was not. The send is captured (no mail leaves); the controls: a frame that names no console keeps <base>/ui, and
a frame with no public address keeps the bare API path.
"""
import asyncio

import pytest

from agentvault_registry.services import organization_service as osvc


@pytest.fixture
def sent(monkeypatch):
    for k in ("PUBLIC_UI_URL", "PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    calls = []

    async def capture(**kw):
        calls.append(kw)
        return True

    monkeypatch.setattr(osvc, "send_themed_email", capture)
    monkeypatch.setattr(osvc, "EMAIL_AVAILABLE", True)
    return calls


def _link(calls):
    assert len(calls) == 1, calls
    return calls[0]["context"]["accept_url"]


def test_the_link_opens_the_console_the_frame_names(sent, monkeypatch):
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "https://eu.theprotocol.cloud", raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://eu.theprotocol.cloud")
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    assert asyncio.run(osvc.send_invitation_email("m@example.com", "tok123", "Hansa Works")) is True
    assert _link(sent) == "https://theprotocol.cloud/#/organizations/invitations/tok123/accept"


def test_control_a_frame_that_names_no_console_keeps_its_own_ui(sent, monkeypatch):
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "https://sandbox-b.theprotocol.cloud", raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://sandbox-b.theprotocol.cloud")
    asyncio.run(osvc.send_invitation_email("m@example.com", "tok456", "Hansa Works"))
    assert _link(sent) == "https://sandbox-b.theprotocol.cloud/ui/#/organizations/invitations/tok456/accept"


def test_control_no_public_address_keeps_the_api_path(sent, monkeypatch):
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "http://localhost:8000", raising=False)
    asyncio.run(osvc.send_invitation_email("m@example.com", "tok789", "Hansa Works"))
    assert _link(sent) == "/api/v1/organizations/invitations/tok789/accept"

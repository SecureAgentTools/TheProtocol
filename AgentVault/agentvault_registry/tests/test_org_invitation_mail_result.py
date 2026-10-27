"""§FESUITE (V0594): an organization invitation says what happened to its mail.

The send's result was discarded: the route answered "Invitation sent to X" when the send failed or no mail service was
configured, and the console's toast said the same (named at V0592: "the invite rail discards whether its mail was
sent"). And the mail went out inside the open transaction, before the commit, so a slow mail server held it open and a
commit that failed after a sent mail left the person a link to a token that never existed. Now the invitation is
committed first, then mailed, and the route's answer carries mail_sent with a message that says the same. The database
and the mail are fakes that record their order; no mail leaves.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.services import organization_service as osvc


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Db:
    """The three reads create_invitation makes (no pending invitation, the organization, the inviter), in order."""

    def __init__(self, order):
        self.order = order
        self._answers = [None, SimpleNamespace(name="Hansa Works"), SimpleNamespace(name="Ines")]

    async def execute(self, _stmt):
        return _Result(self._answers.pop(0))

    def add(self, _obj):
        self.order.append("add")

    async def flush(self):
        self.order.append("flush")

    async def commit(self):
        self.order.append("commit")


@pytest.fixture
def order(monkeypatch):
    seen = []

    async def no_event(*_a, **_k):
        seen.append("event")

    monkeypatch.setattr(osvc, "_emit_org_event", no_event)
    return seen


def _create(monkeypatch, order, sent: bool):
    async def mail(**_kw):
        order.append("mail")
        return sent

    monkeypatch.setattr(osvc, "send_invitation_email", mail)
    return asyncio.run(osvc.InvitationService.create_invitation(
        db=_Db(order), organization_id="org-1", email="m@example.com", role="member", invited_by_id=7))


def test_the_invitation_is_committed_before_its_mail_goes(monkeypatch, order):
    invitation, mail_sent = _create(monkeypatch, order, True)
    assert mail_sent is True
    assert invitation.email == "m@example.com"
    assert order.index("commit") < order.index("mail"), order


def test_a_mail_that_was_not_sent_is_reported_not_swallowed(monkeypatch, order):
    invitation, mail_sent = _create(monkeypatch, order, False)
    assert mail_sent is False, "the send's failure was discarded"
    assert "commit" in order, "the invitation stands without its mail"


def _answer(monkeypatch, mail_sent: bool) -> dict:
    from agentvault_registry.routers import organizations as orgs

    async def allowed(*_a, **_k):
        return None

    async def created(**_kw):
        return SimpleNamespace(id="inv-1", token="tok", expires_at=datetime(2026, 10, 18, tzinfo=timezone.utc)), mail_sent

    monkeypatch.setattr(orgs, "get_organization_with_permission", allowed)
    monkeypatch.setattr(orgs.InvitationService, "create_invitation", staticmethod(created))
    return asyncio.run(orgs.invite_member(
        org_id="org-1", invite=orgs.MemberInvite(email="m@example.com", role="member"),
        current_developer=SimpleNamespace(id=7), db=None))


def test_the_route_says_the_mail_was_not_sent(monkeypatch):
    body = _answer(monkeypatch, False)
    assert body["mail_sent"] is False
    assert "sent to" not in body["message"], body["message"]
    assert "could not be sent" in body["message"]
    assert body["invitation_id"] == "inv-1"


def test_control_a_sent_mail_says_sent(monkeypatch):
    body = _answer(monkeypatch, True)
    assert body["mail_sent"] is True
    assert body["message"] == "Invitation sent to m@example.com"

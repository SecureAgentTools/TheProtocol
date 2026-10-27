"""§DOCSFIX D6-484 + D6-500 (2026-10-16): an organization invitation reaches its invitee, whatever the address's case.

D6-484: the OrganizationMemberInvited reactor tells the invitee by their developer id (`invitee_developer_id`), and the
event the invitation route emits carried no developer id at all (org_id, invitation_id, email, role, invited_by), so
the reactor returned on every invitation and no invitee was ever told. The event now names the invitee's account on this
registry when one exists (matched on the address without regard to case, as sign-in matches it). A bridged copy of a
peer frame's invitation names no developer here: a developer id is only unique per database.

D6-500: the accept route compared the invited address with the signed-in developer's exactly, while sign-in and the
invitation preview ignore case: an invitation to "Alice@Example.com" could not be accepted by alice@example.com, whom
the preview had just told it was addressed to them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from agentvault_registry.background_tasks import reactor_org_lifecycle_notification as R
from agentvault_registry.services import organization_service as OS


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(first=lambda: self._value, all=lambda: [] if self._value is None else [self._value])


class _InviteSession:
    """Answers create_invitation's reads by what each statement asks; records the order of its verbs."""

    def __init__(self, accounts):
        self.accounts = accounts            # {lower-case email: developer id} of this registry
        self.calls = []

    async def execute(self, stmt):
        sql = _sql(stmt)
        self.calls.append(sql)
        if "FROM organization_invitations" in sql:
            return _Result(None)                                    # no pending invitation yet
        if "FROM organizations" in sql:
            return _Result(SimpleNamespace(name="Halden Analytics"))
        if "lower(developers.email)" in sql:
            for email, dev_id in self.accounts.items():
                if f"'{email}'" in sql:
                    return _Result(dev_id)
            return _Result(None)
        if "FROM developers" in sql:
            return _Result(SimpleNamespace(name="Inviter"))
        return _Result(None)

    def add(self, obj):
        self.calls.append("add")

    async def flush(self):
        self.calls.append("flush")

    async def commit(self):
        self.calls.append("commit")


@pytest.fixture
def emitted(monkeypatch):
    seen = []

    async def _emit(event_type, aggregate_id, data, idempotency_key=None):
        seen.append((event_type, aggregate_id, dict(data)))

    async def _mail(**k):
        return True

    monkeypatch.setattr(OS, "_emit_org_event", _emit)
    monkeypatch.setattr(OS, "send_invitation_email", _mail)
    return seen


@pytest.mark.parametrize("invited,accounts,want", [
    ("dana@example.com", {"dana@example.com": 42}, 42),
    ("Dana@Example.COM", {"dana@example.com": 42}, 42),
    ("nobody@example.com", {"dana@example.com": 42}, None),
])
def test_the_invited_event_names_the_invitees_account(emitted, invited, accounts, want):
    db = _InviteSession(accounts)
    invitation, mail_sent = _run(OS.InvitationService.create_invitation(
        db=db, organization_id="org-1", email=invited, role="member", invited_by_id=3))
    assert mail_sent is True
    assert [e[0] for e in emitted] == ["OrganizationMemberInvited"]
    data = emitted[0][2]
    assert data["invitee_developer_id"] == want
    assert data["invitation_id"] == invitation.id and data["org_id"] == "org-1"
    assert "commit" in db.calls


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, dev_id, title, message, notification_type="info"):
        self.calls.append((dev_id, title))


class _Ctx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def reactor(monkeypatch):
    notified = _Notified()

    async def _name(db, org_id):
        return "Halden Analytics"

    monkeypatch.setattr(R, "_notify_user", notified)
    monkeypatch.setattr(R, "_org_name", _name)
    monkeypatch.setattr(R, "get_db_context", lambda: _Ctx())
    # the handler unbound, with a stand-in self: constructing a reactor registers its leader key once per process
    handler = lambda data: R.OrgMemberInvitedReactor.handle_event(SimpleNamespace(name="OrgMemberInvited"), data)
    return SimpleNamespace(handle_event=handler), notified


def test_the_reactor_tells_the_invitee(reactor):
    r, notified = reactor
    _run(r.handle_event({"org_id": "org-1", "invitation_id": "i-1", "role": "member", "invited_by": 3,
                         "invitee_developer_id": 42}))
    assert notified.calls == [(42, "Invitation to Halden Analytics")]


def test_a_peers_invitation_tells_nobody_here(reactor):
    r, notified = reactor
    _run(r.handle_event({"org_id": "org-9", "invitation_id": "i-9", "role": "member", "invited_by": 5,
                         "invitee_developer_id": 42, "_foreign_frame_id": "asia.theprotocol.cloud"}))
    assert notified.calls == [], "a peer's developer 42 is not ours"


def test_an_invitation_with_no_account_here_tells_nobody(reactor):
    r, notified = reactor
    _run(r.handle_event({"org_id": "org-1", "invitation_id": "i-2", "role": "member", "invited_by": 3,
                         "invitee_developer_id": None}))
    assert notified.calls == []


class _Passed(Exception):
    """Raised by the session at the first read after the address check: the check let the developer through."""


class _AcceptSession:
    def __init__(self, invitation):
        self.invitation = invitation
        self.reads = 0

    async def execute(self, stmt):
        self.reads += 1
        if self.reads == 1:
            return _Result(self.invitation)
        raise _Passed()

    async def commit(self):
        pass


def _invitation(email):
    return SimpleNamespace(email=email, status="pending", organization_id="org-1", role="member", invited_by=3,
                           expires_at=datetime.now(timezone.utc) + timedelta(days=1))


@pytest.mark.parametrize("invited,signed_in", [
    ("Alice@Example.com", "alice@example.com"),
    ("alice@example.com", "ALICE@EXAMPLE.COM"),
    ("alice@example.com", "alice@example.com"),
])
def test_accept_matches_the_address_without_regard_to_case(invited, signed_in):
    db = _AcceptSession(_invitation(invited))
    with pytest.raises(_Passed):
        _run(OS.InvitationService.accept_invitation(db=db, token="t", developer=SimpleNamespace(id=7, email=signed_in)))


def test_accept_still_refuses_another_address():
    db = _AcceptSession(_invitation("alice@example.com"))
    with pytest.raises(ValueError, match="different email address"):
        _run(OS.InvitationService.accept_invitation(db=db, token="t",
                                                    developer=SimpleNamespace(id=7, email="mallory@example.com")))

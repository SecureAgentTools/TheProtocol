"""§TWOAGENT #16 (2026-09-23) — a verification link is mailed at most once per cooldown, and a good link is not replaced.

Measured on EU (Stage 0, Session A): every unverified login answered "We just sent a fresh verification link" and did
so: `_issue_fresh_verification_email` ROTATED the token on every call, so each login mailed a new link and killed the
one before it. `POST /auth/resend-verification` needs no authentication and called the same helper, so anyone who knew
an address could keep invalidating its pending link and fill its inbox.

Now: at most one mail per account per VERIFICATION_RESEND_COOLDOWN_S (a cooldown changes nothing and the resend route
answers the same generic 200), and the CURRENT token is re-mailed while it has a quarter of its window left.

RED on V0430: the token rotates on every call and every call mails. The control (an expired link IS replaced and
mailed) passes on both trees.
"""
from __future__ import annotations

import datetime as _dt
import types

import pytest

from agentvault_registry.routers import auth_secure


class _Redis:
    def __init__(self):
        self.keys = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


class _Db:
    def add(self, *_a):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def mail(monkeypatch):
    sent: list = []

    async def _send(to_email, username, token):
        sent.append(token)
        return True
    redis = _Redis()

    async def _get_redis():
        return redis
    from agentvault_registry.background_tasks import leader
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    monkeypatch.setattr(auth_secure, "send_verification_email", _send)
    for k, v in (("MAIL_SERVER", "smtp.test"), ("MAIL_USERNAME", "u"), ("MAIL_FROM", "noreply@test"),
                 ("EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS", 24)):
        monkeypatch.setattr(auth_secure.settings, k, v, raising=False)
    return sent


def _dev(hours_left):
    return types.SimpleNamespace(id=5, email="d@test", name="d", is_verified=False, email_verification_token="tok-1",
                                 verification_token_expires=_dt.datetime.now(_dt.timezone.utc)
                                 + _dt.timedelta(hours=hours_left))


async def test_a_good_link_is_re_mailed_not_replaced(mail):
    dev = _dev(23)
    out = await auth_secure._issue_fresh_verification_email(_Db(), dev, source="login_gate")
    assert out == "sent" and dev.email_verification_token == "tok-1" and mail == ["tok-1"]


async def test_a_second_request_inside_the_cooldown_sends_nothing(mail):
    dev = _dev(23)
    await auth_secure._issue_fresh_verification_email(_Db(), dev, source="login_gate")
    out = await auth_secure._issue_fresh_verification_email(_Db(), dev, source="login_gate")
    assert out == "cooldown" and mail == ["tok-1"] and dev.email_verification_token == "tok-1"


async def test_control_an_expired_link_is_replaced_and_mailed(mail):
    dev = _dev(-1)
    await auth_secure._issue_fresh_verification_email(_Db(), dev, source="login_gate")
    assert len(mail) == 1 and mail[0] != "tok-1" and dev.email_verification_token == mail[0]


async def test_a_strangers_resends_cannot_flood_or_kill_the_link(mail, monkeypatch):
    dev = _dev(23)

    async def _by_email(db, email):
        return dev
    monkeypatch.setattr(auth_secure.developer_crud, "get_developer_by_email", _by_email)
    a = await auth_secure.resend_verification_email(email="d@test", db=_Db())
    b = await auth_secure.resend_verification_email(email="d@test", db=_Db())
    assert a == b and "If that email is registered" in a["message"]
    assert mail == ["tok-1"] and dev.email_verification_token == "tok-1"


async def test_a_claimed_window_still_sends(mail):
    """§EXTTEST (V0649): the login gate claims the window before it answers, and its background send passes claimed=True;
    without that flag the send meets the gate's own claim and mails nothing (the control)."""
    dev = _dev(20)
    assert await auth_secure._verification_resend_allowed(dev.id)
    assert await auth_secure._issue_fresh_verification_email(_Db(), dev, source="login_gate") == "cooldown"
    assert await auth_secure._issue_fresh_verification_email(_Db(), dev, source="login_gate", claimed=True) == "sent"
    assert mail == ["tok-1"]

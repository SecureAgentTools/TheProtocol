"""§TWOAGENT V0432 — Session A's review of V0431, two follow-ups.

1. G4's issuer-authority answer disclosed the issuer's WHOLE current permission set to the delegate's home, which
   needs only what the credential granted that the issuer still holds. Now the answer is that intersection.
2. #16 claimed the resend cooldown BEFORE the send, so an SMTP failure still blocked the next request for 5 minutes.
   Now every "not_sent" outcome releases it.

RED on V0431: the answer carries the issuer's full set; a failed send keeps the cooldown.
"""
from __future__ import annotations

import datetime as _dt
import json
import types

import pytest


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Db:
    def __init__(self, handlers):
        self.handlers = handlers

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        for needle, rows in self.handlers:
            if needle in sql:
                return _Result(rows)
        return _Result([])

    def add(self, *_a):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


async def test_the_issuers_home_discloses_only_the_granted_intersection(monkeypatch):
    from agentvault_registry.services import xreg_issuer_authority as xia
    from agentvault_registry.services import contract_xframe
    from agentvault_registry import agent_authz

    async def _resolve(db, value):
        return "asia" if "asia" in str(value or "") else None

    async def _held(db, did, act_principal=None):
        return {"teg.transfer", "gov.vote", "staking.manage", "authz.delegate"}
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(agent_authz, "resolve_agent_permissions", _held)
    issued = {"credential_id": "c1", "delegate_registry": "https://asia.theprotocol.cloud:8443",
              "permissions": ["teg.transfer"], "expires_at": "2099-01-01T00:00:00+00:00"}
    db = _Db([("xreg_delegation_issue", [(json.dumps(issued),)]), ("FROM agents WHERE did", [("active", "active")])])
    a = await xia.issuer_answer(db, "did:theprotocol:eu.test:i", "c1", "asia")
    assert a["issuer_permissions"] == ["teg.transfer"]


class _Redis:
    def __init__(self):
        self.keys = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    async def delete(self, key):
        self.keys.pop(key, None)
        return 1


async def test_a_failed_send_does_not_hold_the_cooldown(monkeypatch):
    from agentvault_registry.routers import auth_secure
    from agentvault_registry.background_tasks import leader
    redis = _Redis()
    attempts: list = []

    async def _get_redis():
        return redis

    async def _send(to_email, username, token):
        attempts.append(token)
        return len(attempts) > 1      # the first SMTP attempt fails, the second goes out
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    monkeypatch.setattr(auth_secure, "send_verification_email", _send)
    for k, v in (("MAIL_SERVER", "smtp.test"), ("MAIL_USERNAME", "u"), ("MAIL_FROM", "noreply@test"),
                 ("EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS", 24)):
        monkeypatch.setattr(auth_secure.settings, k, v, raising=False)
    dev = types.SimpleNamespace(id=7, email="d@test", name="d", is_verified=False, email_verification_token="tok-1",
                                verification_token_expires=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=23))
    first = await auth_secure._issue_fresh_verification_email(_Db([]), dev, source="login_gate")
    second = await auth_secure._issue_fresh_verification_email(_Db([]), dev, source="login_gate")
    assert (first, second) == ("not_sent", "sent") and len(attempts) == 2

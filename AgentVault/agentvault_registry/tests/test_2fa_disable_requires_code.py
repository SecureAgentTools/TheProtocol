"""D6-233 (2026-10-16): POST /auth/2fa/disable asks for the second factor, not only the password.

The code was optional (checked only when sent), so the password alone turned 2FA off; and the request's 6-digit pattern
refused every backup code (XXXX-XXXX) before the handler could try one. Wrong codes were not counted, so the code could
be guessed without limit. Each test marked BASE fails on 14520b9f.

Through FastAPI on the real router; only the developer dependency and the database session are replaced.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import auth_2fa
from agentvault_registry.services import TwoFactorAuthService

PW = "correct horse battery 42!"
BACKUP = "ABCD-1234"


class _Session:
    """Records the parameters of every statement the handler sends."""

    def __init__(self):
        self.params = []

    async def execute(self, stmt, *a, **k):
        self.params.append(dict(stmt.compile().params))

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def disabled(self) -> bool:
        return any(p.get("two_fa_enabled") is False for p in self.params)

    def failures_counted(self) -> list:
        return [p["two_fa_recovery_attempts"] for p in self.params if "two_fa_recovery_attempts" in p
                and "two_fa_enabled" not in p]


@pytest.fixture()
def rig(monkeypatch):
    async def _quiet(*a, **k):   # the "2FA changed" push is not under test
        return None
    import agentvault_registry.background_tasks.push_notify as pn
    monkeypatch.setattr(pn, "notify", _quiet)
    secret = pyotp.random_base32()
    dev = SimpleNamespace(
        id=7, email="dev@example.test", two_fa_enabled=True, totp_secret=secret,
        hashed_password=security.hash_password(PW),
        backup_codes={"codes": TwoFactorAuthService.hash_backup_codes([BACKUP])},
        two_fa_recovery_attempts=0, two_fa_last_failure=None,
    )
    session = _Session()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_2fa.router)
    app.dependency_overrides[security.get_current_developer] = lambda: dev
    app.dependency_overrides[get_db] = lambda: session
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False), dev=dev, db=session,
                           totp=pyotp.TOTP(secret))


def _wrong_code(totp) -> str:
    valid = {totp.at(datetime.now(timezone.utc).timestamp() + d) for d in (-60, -30, 0, 30, 60)}
    return next(c for c in ("000000", "111111", "222222", "333333", "444444", "555555", "666666") if c not in valid)


def test_password_alone_does_not_disable(rig):   # BASE: 200, 2FA turned off
    r = rig.client.post("/auth/2fa/disable", json={"password": PW})
    assert r.status_code == 422, r.text
    assert not rig.db.disabled()


def test_a_backup_code_disables(rig):   # BASE: 422 (the 6-digit pattern)
    r = rig.client.post("/auth/2fa/disable", json={"password": PW, "code": BACKUP})
    assert r.status_code == 200, r.text
    assert rig.db.disabled()


def test_a_backup_code_typed_without_the_hyphen_disables(rig):   # BASE: 422
    r = rig.client.post("/auth/2fa/disable", json={"password": PW, "code": BACKUP.replace("-", "").lower()})
    assert r.status_code == 200, r.text
    assert rig.db.disabled()


def test_a_wrong_code_is_refused_and_counted(rig):   # BASE: refused, but never counted
    r = rig.client.post("/auth/2fa/disable", json={"password": PW, "code": _wrong_code(rig.totp)})
    assert r.status_code == 400, r.text
    assert not rig.db.disabled()
    assert rig.db.failures_counted() == [1]


def test_after_five_failures_even_a_right_code_waits(rig):   # BASE: 200
    rig.dev.two_fa_recovery_attempts = 5
    rig.dev.two_fa_last_failure = datetime.now(timezone.utc)
    r = rig.client.post("/auth/2fa/disable", json={"password": PW, "code": rig.totp.now()})
    assert r.status_code == 429, r.text
    assert not rig.db.disabled()


def test_control_password_and_current_code_disable(rig):
    r = rig.client.post("/auth/2fa/disable", json={"password": PW, "code": rig.totp.now()})
    assert r.status_code == 200, r.text
    assert rig.db.disabled()


def test_control_a_wrong_password_is_refused_with_a_right_code(rig):
    r = rig.client.post("/auth/2fa/disable", json={"password": PW + "x", "code": rig.totp.now()})
    assert r.status_code == 401, r.text
    assert not rig.db.disabled()


async def test_the_mcp_tool_asks_for_the_code_before_calling():   # BASE: it sent the password alone
    from agentvault_registry.mcp import tools_developer as td
    sent = []

    async def _rec(auth, method, path, json_body=None, **k):
        sent.append((path, json_body))
        return {"ok": True}
    td_orig = td._dev_request
    td._dev_request = _rec
    try:
        out = await td.disable_2fa_self(SimpleNamespace(), password=PW)
        assert "error" in out and sent == []
        await td.disable_2fa_self(SimpleNamespace(), password=PW, code="123456")
        assert sent == [("/api/v1/auth/2fa/disable", {"password": PW, "code": "123456"})]
    finally:
        td._dev_request = td_orig
    schema = next(t for t in td.DEVELOPER_TOOL_SCHEMAS if t["name"] == "theprotocol_disable2FASelf")["inputSchema"]
    assert schema["required"] == ["password", "code"]

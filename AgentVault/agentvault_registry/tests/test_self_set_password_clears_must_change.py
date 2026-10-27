"""A password the person sets themselves clears must_change_password (§HELLOFRAME, 2026-09-19).

The frame request intake and the fiat onramp create magic-link accounts with must_change_password=True beside a random
password nobody ever sees. The only way in is the mailed link, and /auth/reset-password set the person's own password
without clearing the flag, so the frame kit drive met every such applicant at "This account was issued with a password
that someone else has seen" and a second forced change. Both routes where a person sets their own password now clear
it, as change-password always did. These tests drive the route functions themselves with a fake session.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import auth_secure
from agentvault_registry import schemas


class FakeSession:
    def __init__(self):
        self.added, self.commits = [], 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def issued_account(**changes):
    base = dict(id=7, email="ada@northwind.example", hashed_password="issued", must_change_password=True,
                password_reset_token="mailed-token", hashed_recovery_key="recovery",
                password_reset_token_expires=datetime.now(timezone.utc) + timedelta(days=7),
                token_version=0, updated_at=None)
    base.update(changes)
    return SimpleNamespace(**base)


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(auth_secure, "validate_password_strength", lambda p: (True, ""))
    monkeypatch.setattr(auth_secure.security, "hash_password", lambda p: f"hashed:{p}")


def _route(fn):
    # The email route carries the rate limiter's decorator; the function under it is what this test drives.
    return getattr(fn, "__wrapped__", fn)


def test_the_mailed_link_clears_the_issued_password_flag(patched, monkeypatch):
    dev = issued_account()

    async def by_token(db, token):
        return dev if token == "mailed-token" else None

    monkeypatch.setattr(auth_secure, "get_developer_by_reset_token", by_token)
    db = FakeSession()
    out = asyncio.run(_route(auth_secure.reset_password_via_email)(
        request=None, token="mailed-token", new_password="Own-Chosen-Password-19!", db=db))
    assert "updated" in out["message"].lower()
    assert dev.must_change_password is False
    assert dev.hashed_password == "hashed:Own-Chosen-Password-19!"
    assert dev.password_reset_token is None and dev.password_reset_token_expires is None
    assert dev.token_version == 1 and db.commits == 1


def test_an_expired_link_changes_nothing(patched, monkeypatch):
    dev = issued_account(password_reset_token_expires=datetime.now(timezone.utc) - timedelta(minutes=1))

    async def by_token(db, token):
        return dev

    monkeypatch.setattr(auth_secure, "get_developer_by_reset_token", by_token)
    with pytest.raises(Exception) as exc:
        asyncio.run(_route(auth_secure.reset_password_via_email)(
            request=None, token="mailed-token", new_password="Own-Chosen-Password-19!", db=FakeSession()))
    assert getattr(exc.value, "status_code", None) == 400
    assert dev.must_change_password is True and dev.hashed_password == "issued"


def test_the_recovery_key_path_clears_it_too(patched, monkeypatch):
    dev = issued_account()

    async def by_id(db, developer_id):
        return dev if developer_id == 7 else None

    monkeypatch.setattr(auth_secure.developer_crud, "get_developer_by_id", by_id)
    db = FakeSession()
    out = asyncio.run(auth_secure.set_new_password_after_recovery(
        set_in=schemas.PasswordSetNew(new_password="Own-Chosen-Password-19!"), db=db,
        claims=(7, dev.token_version or 0)))   # the password-set token carries the version it was issued at (V0636)
    assert "updated" in out["message"].lower()
    assert dev.must_change_password is False and dev.token_version == 1
    # §FESUITE (V0530): the recovery keys are no longer wiped here. recover-account burns the ONE key it verified, and
    # the account's other keys keep working (registration issues three; one recovery used to leave none).
    assert dev.hashed_recovery_key == "recovery"

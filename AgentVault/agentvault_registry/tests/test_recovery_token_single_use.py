"""The password-set token account recovery answers sets a password once (agentvault2-66, 2026-10-24).

The MCP tester's recovery chain (earned_agent_public.lifecycle_earned_auth_chain) found that POST /auth/set-new-password
took the same token again for its whole five minutes: the token carried no version and the route checked none. It now
carries the account's token_version (`tv`) and the route refuses it once that version has moved, which setting the
password does (as do a reset and a logout)."""
import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry import schemas, security
from agentvault_registry.routers import auth_secure as A


class _Db:
    def add(self, x):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _dev(tv):
    return types.SimpleNamespace(id=7, token_version=tv, hashed_password="old", must_change_password=True,
                                 updated_at=None)


def _set(monkeypatch, dev, claims):
    async def _get(db, developer_id):
        return dev
    monkeypatch.setattr(A.developer_crud, "get_developer_by_id", _get)
    body = schemas.PasswordSetNew(new_password="Tw!a83f19c0d27e4b56Z9a")
    return asyncio.run(A.set_new_password_after_recovery(set_in=body, db=_Db(), claims=claims))


def test_a_recovery_token_sets_a_password_once(monkeypatch):
    dev = _dev(3)
    out = _set(monkeypatch, dev, (7, 3))
    assert "updated" in out["message"].lower() and dev.token_version == 4
    with pytest.raises(HTTPException) as e:
        _set(monkeypatch, dev, (7, 3))          # the same token again: the version it was issued at has moved
    assert e.value.status_code == 401


def test_a_token_that_names_no_version_is_refused(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _set(monkeypatch, _dev(0), (7, None))
    assert e.value.status_code == 401


def test_the_recovery_answer_carries_the_accounts_version(monkeypatch):
    dev = types.SimpleNamespace(id=7, is_verified=True, hashed_recovery_key="h", token_version=5)

    async def _by_email(db, email):
        return dev
    monkeypatch.setattr(A.developer_crud, "get_developer_by_email", _by_email)
    monkeypatch.setattr(A.security, "match_recovery_key", lambda key, hashed: 0)
    monkeypatch.setattr(A.security, "burn_recovery_key", lambda hashed, used: hashed)
    tok = asyncio.run(A.recover_account_with_key(
        schemas.PasswordResetRecover(email="t@example.com", recovery_key="avrec-k"), db=_Db()))
    assert asyncio.run(security.verify_temp_password_claims(tok.access_token)) == (7, 5)

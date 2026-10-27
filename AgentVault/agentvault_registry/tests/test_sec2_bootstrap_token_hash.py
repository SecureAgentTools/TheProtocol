"""D6-283 (2026-10-16): a bootstrap token is stored as its hash, never as the token.

P23-001 (2026-04-30) added `token_value_hash` and kept writing the plaintext into `token_value` "for one cycle"; the
cycle never ended, and the used-token lookup in create_agent still compared the plaintext column. Now the row keeps
only the SHA-256 hash (the legacy NOT NULL column holds a marker derived from it), the plain token exists only in the
response that hands it out, and both lookups (the live token, and a used one told apart from an unknown one) go by the
hash, confirmed in constant time. A token issued before this change also carries its hash, so it keeps working within
its five minutes; only a token with no hash at all (issued before 2026-04-30) is no longer recognised.

Through FastAPI on the real onboarding routes; only the database is a double (it keeps what was added and answers a
statement only when the statement looks the token up by its hash).
RED on 7140a4a6: test_the_row_stores_no_plaintext (the base stores the token itself) and
test_a_used_token_is_told_it_was_used (with no plaintext stored, the base cannot find the used row: 401, not 409).
"""
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.middleware.rate_limiter import shared_limiter
from agentvault_registry.routers import onboarding


def _sha(v):
    return hashlib.sha256(v.encode()).hexdigest()


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def add(self, obj):
        self.rows.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def execute(self, stmt, *a, **k):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        active_only = "used_at IS NULL" in sql
        for row in self.rows:
            if row.token_value_hash and f"'{row.token_value_hash}'" in sql:   # looked up by its hash
                if active_only and (row.is_used or row.used_at is not None):
                    return _Result(None)
                return _Result(row)
            if f"'{row.token_value}'" in sql:                                 # looked up by the stored column
                return _Result(None if active_only and row.is_used else row)
        return _Result(None)


@pytest.fixture(autouse=True)
def no_limits(monkeypatch):
    monkeypatch.setattr(shared_limiter, "enabled", False)


def _client(db):
    app = FastAPI()
    app.state.limiter = shared_limiter
    app.include_router(onboarding.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[security.get_current_developer_unified] = lambda: SimpleNamespace(
        id=41, is_verified=True, is_admin=False)
    return TestClient(app, raise_server_exceptions=False)


def test_the_row_stores_no_plaintext():
    db = _Db()
    r = _client(db).post("/onboard/bootstrap/request-token", json={})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    plain = r.json()["bootstrap_token"]
    assert plain.startswith("bst_")
    (row,) = db.rows
    assert row.token_value_hash == _sha(plain)
    assert plain not in str(row.token_value), "the plain token is stored"
    assert row.token_value == f"sha256:{_sha(plain)}"


def _used_row(plain):
    return SimpleNamespace(token_value=f"sha256:{_sha(plain)}", token_value_hash=_sha(plain), is_used=True,
                           used_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=4))


AGENT = {"agent_did_method": "theprotocol", "agent_host": "https://agent.example.invalid"}


def test_a_used_token_is_told_it_was_used():
    plain = "bst_0123456789abcdef_" + "a" * 32
    r = _client(_Db([_used_row(plain)])).post("/onboard/create_agent", json=AGENT, headers={"Bootstrap-Token": plain})
    assert r.status_code == 409, (r.status_code, r.text[:300])


def test_control_an_unknown_token_is_401():
    r = _client(_Db([_used_row("bst_other_" + "b" * 32)])).post(
        "/onboard/create_agent", json=AGENT, headers={"Bootstrap-Token": "bst_0123456789abcdef_" + "c" * 32})
    assert r.status_code == 401, (r.status_code, r.text[:300])


@pytest.mark.asyncio
async def test_the_live_lookup_goes_by_the_hash_and_confirms_it():
    """The crud lookup a create_agent call makes: by hash, and a row whose stored hash differs is not returned."""
    from agentvault_registry.crud import bootstrap_token as crud
    plain = "bst_0123456789abcdef_" + "d" * 32
    live = SimpleNamespace(token_value=f"sha256:{_sha(plain)}", token_value_hash=_sha(plain), is_used=False,
                           used_at=None, expires_at=datetime.now(timezone.utc) + timedelta(minutes=4))
    assert await crud.get_active_bootstrap_token_by_value(_Db([live]), plain) is live
    assert await crud.get_active_bootstrap_token_by_value(_Db([live]), plain + "x") is None

"""§DOCSFIX D6-154 (2026-10-16): a capability token keeps paying on the money paths after an explicit consume.

POST /agents/capabilities/consume debits a token and sets its status to 'active'; the resolver treats 'issued' and
'active' alike (both are live), but the money paths' atomic debit (security.enforce_agent_spend) matched only
status = 'issued', so a token consumed once explicitly was refused on every money path as "capability budget or uses
exhausted" with its budget intact. The debit accepts both live statuses now; the budget, the uses, the revocation and
the exhausted status still bind it. The debit's own statement runs against an in-memory SQLite table.

RED on the pre-change tree: the active-token test. The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool

from agentvault_registry import agent_authz as authz
from agentvault_registry import security
from agentvault_registry.services import admin_audit, org_policy

HOLDER = "did:theprotocol:eu.theprotocol.cloud:holder-0000"
PAYEE = "did:theprotocol:eu.theprotocol.cloud:payee-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self, conn):
        self.conn = conn

    async def execute(self, stmt, params=None):
        params = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in (params or {}).items()}
        return self.conn.execute(stmt, params)


@pytest.fixture
def tokens(monkeypatch):
    eng = sa.create_engine("sqlite://", poolclass=StaticPool)
    conn = eng.connect()
    conn.execute(sa.text("CREATE TABLE agent_capability_tokens (id INTEGER PRIMARY KEY, status TEXT, revoked_at TEXT, "
                         "budget_total NUMERIC, budget_spent NUMERIC, max_uses INTEGER, uses INTEGER)"))

    async def _ok(*a, **k):
        return True, None

    async def _org(db, did):
        return {}

    async def _audit(*a, **k):
        return None
    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce")
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _ok)
    monkeypatch.setattr(org_policy, "get_org_settings", _org)
    monkeypatch.setattr(admin_audit, "log_ironkey_action", _audit)
    yield conn
    conn.close()


def _token(conn, *, status, spent="1", total="10", uses=1, max_uses=None, revoked=None):
    conn.execute(sa.text("INSERT INTO agent_capability_tokens VALUES (41, :s, :r, :t, :sp, :mu, :u)"),
                 {"s": status, "r": revoked, "t": float(total), "sp": float(spent), "mu": max_uses, "u": uses})


def _spend(conn, amount="1"):
    req = types.SimpleNamespace(state=types.SimpleNamespace(ironkey_capability={"id": 41, "caveats": {}}))
    return _run(security.enforce_agent_spend(_Db(conn), HOLDER, amount, counterparty_did=PAYEE, request=req))


def _spent(conn):
    return conn.execute(sa.text("SELECT budget_spent, uses FROM agent_capability_tokens WHERE id = 41")).one()


def test_a_token_debited_explicitly_still_pays_on_a_money_path(tokens):
    _token(tokens, status="active")
    assert _spend(tokens) is None
    assert tuple(_spent(tokens)) == (2, 2)


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_fresh_token_pays(tokens):
    _token(tokens, status="issued", spent="0", uses=0)
    assert _spend(tokens) is None and tuple(_spent(tokens)) == (1, 1)


@pytest.mark.parametrize("row", [
    {"status": "active", "spent": "10"},                  # its budget is spent
    {"status": "active", "uses": 3, "max_uses": 3},       # its uses are spent
    {"status": "exhausted", "spent": "10"},
    {"status": "revoked", "revoked": "2026-10-16"},
])
def test_control_a_spent_or_revoked_token_is_refused(tokens, row):
    _token(tokens, **row)
    with pytest.raises(HTTPException) as e:
        _spend(tokens)
    assert e.value.status_code == 403 and "exhausted" in e.value.detail

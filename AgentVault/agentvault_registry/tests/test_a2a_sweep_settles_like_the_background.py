"""§DOCSFIX D6-778 (2026-10-17): a token the stale-settlement sweep settles owes what a background settle's success owes.

The background settle (routers/a2a_payment._process_settlement_async) records a success, tells the payer's owner
`payment.settled` and stamps a contract-bound token's contract.payment_transaction_id. The sweep
(background_tasks/a2a_payment_expiry) settles a token whose kept transfer completed (D6-437 / CB-442) and wrote only the
token's row: such a payment told its payer nothing and stamped no contract. Both now run one helper,
a2a_payment._after_settled, and only the writer of the SETTLED row runs it (a token the background settled first is
left alone by the sweep, and the reverse).

The sweep runs its own statements against an in-memory SQLite table built from the models.

RED on the pre-change tree: the notice and the contract stamp after a sweep settle. The controls are green before and
after. 2026-10-17: the kept success is the settlement's own request (its body hash; the sweep trusts no other record
under the key, tests/test_a2a_sweep_trusts_only_its_own_record.py); it was planted under a placeholder hash.
"""
from __future__ import annotations

import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")
sweep = importlib.import_module("agentvault_registry.background_tasks.a2a_payment_expiry")
leader = importlib.import_module("agentvault_registry.background_tasks.leader")
durable = importlib.import_module("agentvault_registry.services.idempotency.durable")
helpers = importlib.import_module("agentvault_registry.background_tasks.reactor_helpers")
models = importlib.import_module("agentvault_registry.models")

T = models.A2APaymentAuthorization
C = models.RefactoringUpgradeContract
PAYER = "did:theprotocol:eu.theprotocol.cloud:payer-0000"
PAYEE = "did:theprotocol:asia.theprotocol.cloud:payee-0000"
SCOPE = "teg.cross-registry-transfer"   # the payee is on another registry


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, *a, **k):
        return self.conn.execute(stmt, *a, **k)

    async def commit(self):
        self.conn.commit()


class _Redis:
    def __init__(self, records):
        self.records = records

    async def get(self, key):
        return self.records.get(key)


@pytest.fixture
def env(monkeypatch):
    eng = sa.create_engine("sqlite://", poolclass=StaticPool)
    T.__table__.create(eng)
    C.__table__.create(eng)
    c = eng.connect()
    sent = []

    async def _dispatch(event, data, dids, *, source_label="x"):
        sent.append((event, data.get("token_id"), data.get("settlement_tx_id"), tuple(dids)))
        return 1

    async def _remote(db, did):
        return False
    monkeypatch.setattr(sweep, "async_session_factory", lambda: _Db(c))
    monkeypatch.setattr(durable, "enabled", lambda: False)
    monkeypatch.setattr(a2a, "_is_local_agent", _remote)
    monkeypatch.setattr(helpers, "dispatch_webhook_for_agents", _dispatch)
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    monkeypatch.setenv("REDIS_URL", "redis://redis.test:6379/0")
    yield c, sent
    c.close()


def _token(conn, tid, *, contract_id=None, status="settling"):
    now = datetime.now(timezone.utc)
    conn.execute(sa.insert(T.__table__).values(
        id=tid, caller_did=PAYER, target_agent_did=PAYEE, amount=Decimal("2"), token_hash=f"h-{tid}",
        token_prefix="apt_x", status=status, created_at=now - timedelta(seconds=605), contract_id=contract_id,
        expires_at=now + timedelta(seconds=300), consumed_at=now - timedelta(seconds=600), task_id="task-7"))
    conn.commit()


def _contract(conn, cid):
    conn.execute(sa.insert(C.__table__).values(
        id=cid, client_agent_did=PAYER, upgrader_agent_did=PAYEE, status="IN_PROGRESS", scope_description="s",
        source_code_repo_url="r", source_code_branch="b", acceptance_criteria={}, payment_amount=Decimal("2")))
    conn.commit()


def _stamp(conn, cid):
    return conn.execute(sa.select(C.__table__.c.payment_transaction_id).where(C.__table__.c.id == cid)).scalar()


def _row(conn, tid):
    return tuple(conn.execute(sa.select(T.__table__.c.status, T.__table__.c.settlement_tx_id)
                              .where(T.__table__.c.id == tid)).one())


def _store(monkeypatch, records):
    async def _get():
        return _Redis(records)
    monkeypatch.setattr(leader, "get_redis", _get)


def _kept_success(tid, tx):
    from tests.test_a2a_settle_sweep_asks_first import _own
    key = a2a._settlement_key(tid, f"h-{tid}")
    return {f"idempotency:{SCOPE}:{key}": json.dumps({"body_hash": _own(tid, SCOPE, task="task-7"),
                                                      "response": {"transfer_id": tx, "status": "completed"}})}


def test_a_token_the_sweep_settles_tells_its_payer(env, monkeypatch):
    conn, sent = env
    _token(conn, "tok-1")
    _store(monkeypatch, _kept_success("tok-1", "xf-9"))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "xf-9")
    assert sent == [("payment.settled", "tok-1", "xf-9", (PAYER,))]


def test_a_contract_bound_token_the_sweep_settles_stamps_its_contract(env, monkeypatch):
    conn, sent = env
    _contract(conn, 41)
    _token(conn, "tok-1", contract_id=41)
    _store(monkeypatch, _kept_success("tok-1", "xf-9"))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "xf-9") and _stamp(conn, 41) == "xf-9"
    assert [s[0] for s in sent] == ["payment.settled"]


def test_the_notice_carries_the_token_as_the_background_settle_sends_it(env, monkeypatch):
    conn, _ = env
    seen = []

    async def _notify(event, auth, tx_id):
        seen.append((event, auth.id, auth.caller_did, auth.target_agent_did, str(auth.amount), auth.status,
                     auth.task_id, tx_id))
    monkeypatch.setattr(a2a, "_notify_payer", _notify)
    _token(conn, "tok-1")
    _store(monkeypatch, _kept_success("tok-1", "xf-9"))
    _run(sweep._expire_stale_tokens())
    [(event, tid, payer, payee, amount, status, task, tx)] = seen
    assert (event, tid, payer, payee, status, task, tx) == ("payment.settled", "tok-1", PAYER, PAYEE, "settled",
                                                             "task-7", "xf-9")
    assert Decimal(amount) == Decimal("2")


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_token_the_sweep_fails_sends_no_settled_notice(env, monkeypatch):
    conn, sent = env
    _token(conn, "tok-1")
    _store(monkeypatch, {})
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("failed", None) and sent == []


def test_control_a_token_settled_before_the_sweeps_write_is_left_to_its_writer(env, monkeypatch):
    conn, sent = env
    _token(conn, "tok-1")
    _store(monkeypatch, _kept_success("tok-1", "xf-9"))
    real = sweep._settlement_outcome

    async def _raced(token_id, token_hash, scope, callers, **kw):
        out = await real(token_id, token_hash, scope, callers, **kw)
        # the background settle wins the row between the sweep's question and its write
        conn.execute(sa.update(T.__table__).where(T.__table__.c.id == token_id)
                     .values(status="settled", settlement_tx_id="xf-9"))
        conn.commit()
        return out
    monkeypatch.setattr(sweep, "_settlement_outcome", _raced)
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "xf-9") and sent == []

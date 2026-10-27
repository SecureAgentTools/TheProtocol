"""§DOCSFIX D6-437 + CB-442 (2026-10-16): the stale-settlement sweep asks whether the transfer completed before it calls
an A2A payment token failed, and a transfer that completes after the sweep ended the wait is recorded.

Before: a token still `settling` 90 s after it was verified (or created) was marked FAILED with no question asked. The
clock starts at verification, not at settlement, so a token settled late in its life could be failed while its
transfer ran; the transfer then completed and its result was dropped (the token read FAILED with no settlement_tx_id),
and a payer reading FAILED may pay again.

Now the settlement's transfer carries one Idempotency-Key per token, under which the transfer endpoint keeps its
answer, and the sweep reads that record (Redis, then the durable copy, on the endpoint the settlement used) before it
decides:
a kept success settles the token with its transaction id; a kept failure, or nothing under the key, fails it; a claim
(a transfer still running, or one that ended without an answer) or a store it cannot read leaves it settling. The
background settle records a success that arrives after the sweep failed the token.

The sweep runs its own statements against an in-memory SQLite table built from the model.

§DOCSFIX review: the key is `a2a-settle-<token id>-<digest of the token's hash>`. The token id is public (the
A2APaymentAuthorized event carries it, and the frame's public event feed shows it), and a transfer endpoint keeps a key
for whoever sends it first, so a key built from the id alone let anyone occupy it with a transfer of their own: the
settlement was refused as a different request, and the sweep could read the stranger's transfer as the payment. The
sweep also reads only the endpoint the settlement used (a payee on this registry: /teg/transfer's records).

A registry with no store (REDIS_URL unset) fails a stale token as before; a store that cannot be reached right now is
a store that could not be read (the durable copy answers when it can, else the token waits), never one that holds
nothing.

RED on the pre-change tree: every test but the controls at the end. RED before the review: the three tests of the key
and the endpoint ("only the holders", "the token id alone", "the other endpoint") and the two of a Redis that cannot
be reached ("cannot be reached now", "while Redis cannot be reached").

2026-10-17: a record the sweep trusts is one of the settlement's own request (its body hash): the payer can derive the
key. These tests planted records under a placeholder hash ("b"), so they could not tell the settlement's record from a
transfer of the payer's own under the same key (tests/test_a2a_sweep_trusts_only_its_own_record.py); they now plant
the settlement's own request (_own).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")
sweep = importlib.import_module("agentvault_registry.background_tasks.a2a_payment_expiry")
leader = importlib.import_module("agentvault_registry.background_tasks.leader")
durable = importlib.import_module("agentvault_registry.services.idempotency.durable")
cache = importlib.import_module("agentvault_registry.services.idempotency.cache")
models = importlib.import_module("agentvault_registry.models")
ti = importlib.import_module("agentvault_registry.routers.teg_integration")

T = models.A2APaymentAuthorization
PAYER = "did:theprotocol:eu.theprotocol.cloud:payer-0000"
PAYEE = "did:theprotocol:asia.theprotocol.cloud:payee-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── an async session over SQLite, so the sweep's own SQL decides ───────────────────────────────────────────────────

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


LOCAL = set()   # payees on this registry (the test's agents table); every other payee is remote


@pytest.fixture
def conn(monkeypatch):
    eng = sa.create_engine("sqlite://", poolclass=StaticPool)
    T.__table__.create(eng)
    c = eng.connect()
    LOCAL.clear()

    async def _is_local(db, did):
        return did in LOCAL
    monkeypatch.setattr(sweep, "async_session_factory", lambda: _Db(c))
    monkeypatch.setattr(durable, "enabled", lambda: False)
    # §DOCSFIX D6-778: a token the sweep settles notifies its payer (test_a2a_sweep_settles_like_the_background.py)

    async def _no_notice(*a, **k):
        return 0
    monkeypatch.setattr(importlib.import_module("agentvault_registry.background_tasks.reactor_helpers"),
                        "dispatch_webhook_for_agents", _no_notice)
    monkeypatch.setattr(a2a, "_is_local_agent", _is_local)
    monkeypatch.setenv("REDIS_URL", "redis://redis.test:6379/0")   # this registry has a store
    yield c
    c.close()


def _token(conn, tid, *, status="settling", verified_s_ago=600):
    now = datetime.now(timezone.utc)
    conn.execute(sa.insert(T.__table__).values(
        id=tid, caller_did=PAYER, target_agent_did=PAYEE, amount=Decimal("2"), token_hash=f"h-{tid}",
        token_prefix="apt_x", status=status, created_at=now - timedelta(seconds=verified_s_ago + 5),
        expires_at=now + timedelta(seconds=300), consumed_at=now - timedelta(seconds=verified_s_ago)))
    conn.commit()


def _row(conn, tid):
    r = conn.execute(sa.select(T.__table__.c.status, T.__table__.c.settlement_tx_id).where(T.__table__.c.id == tid))
    return tuple(r.one())


class _Redis:
    def __init__(self, records=None, *, fail=False):
        self.records = records or {}
        self.fail = fail

    async def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.records.get(key)


def _store(monkeypatch, records=None, *, fail=False, none=False):
    """none: leader.get_redis answers None (no REDIS_URL, or a Redis it cannot reach right now)."""
    async def _get():
        return None if none else _Redis(records, fail=fail)
    monkeypatch.setattr(leader, "get_redis", _get)


def _key(tid):
    return a2a._settlement_key(tid, f"h-{tid}")   # _token stores token_hash h-<id>


def _kept(scope, tid, rec, *, key=None):
    return {f"idempotency:{scope}:{key or _key(tid)}": json.dumps(rec)}


AMOUNT = "2.000000"   # _token's amount, as the token's Numeric(30, 6) column gives it back


def _own_body(tid, scope, *, task=None, backend=None):
    """The request the token's settlement sends under its key, as the transfer endpoint on `scope` keeps it (its
    request model's dump, and on the cross-registry endpoint the backend it ran with)."""
    msg = f"A2A service payment (token={tid[:8]}, task={task or 'n/a'})"
    if scope == "teg.transfer":
        return ti.TEGTransferRequest(receiver_agent_id=PAYEE, amount=AMOUNT, message=msg).model_dump(mode="json")
    return dict(ti.CrossRegistryTransferRequest(receiver_did=PAYEE, amount=AMOUNT, message=msg).model_dump(mode="json"),
                backend=backend)


def _own(tid, scope, *, caller=None, **kw):
    """The body hash a record of the settlement's own request keeps: `caller`'s (D6-777), or, without a caller, the
    bare hash of a record written before records were the caller's (the form _kept writes)."""
    body = _own_body(tid, scope, **kw)
    return cache._record_hash(caller, body) if caller else cache._body_hash(body)


# ── the sweep asks first ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_transfer_the_store_kept_as_a_success_settles_its_token(conn, monkeypatch):
    _token(conn, "tok-1")
    _store(monkeypatch, _kept("teg.cross-registry-transfer", "tok-1",
                              {"body_hash": _own("tok-1", "teg.cross-registry-transfer"),
                               "response": {"transfer_id": "xf-9", "status": "completed"}}))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "xf-9")


def test_a_transfer_still_claimed_leaves_its_token_settling(conn, monkeypatch):
    _token(conn, "tok-1")
    LOCAL.add(PAYEE)
    _store(monkeypatch, _kept("teg.transfer", "tok-1", {"body_hash": _own("tok-1", "teg.transfer"), "pending": True,
                                                        "kept": True, "owner": "o"}))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settling", None)


def test_a_store_that_cannot_be_read_leaves_the_token_settling(conn, monkeypatch):
    _token(conn, "tok-1")
    _store(monkeypatch, fail=True)
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settling", None)


def test_a_redis_that_cannot_be_reached_now_leaves_the_token_settling(conn, monkeypatch):
    _token(conn, "tok-1")
    _store(monkeypatch, none=True)   # REDIS_URL set: an outage, not a registry without a store
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settling", None)


def test_while_redis_cannot_be_reached_the_durable_copy_answers(conn, monkeypatch):
    _token(conn, "tok-1")
    _store(monkeypatch, none=True)

    async def _get(scope, key):
        if (scope, key) == ("teg.cross-registry-transfer", _key("tok-1")):
            return {"body_hash": _own("tok-1", scope), "state": "answer",
                    "payload": {"transfer_id": "xf-7", "status": "completed"}}
        return None
    monkeypatch.setattr(durable, "enabled", lambda: True)
    monkeypatch.setattr(durable, "get", _get)
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "xf-7")


def test_the_durable_copy_answers_when_redis_lost_the_record(conn, monkeypatch):
    _token(conn, "tok-1")
    LOCAL.add(PAYEE)
    _store(monkeypatch, {})
    asked = []

    async def _get(scope, key):
        asked.append((scope, key))
        if scope == "teg.transfer":
            return {"body_hash": _own("tok-1", scope, caller=cache.agent_caller(PAYER)), "state": "answer",
                    "payload": {"transaction_id": "tx-4", "status": "completed"}}
        return None
    monkeypatch.setattr(durable, "enabled", lambda: True)
    monkeypatch.setattr(durable, "get", _get)
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "tx-4")
    # the endpoint the settlement used, and only that one, under the payer's own record of the key (D6-777)
    assert asked == [("teg.transfer", cache._durable_key(_key("tok-1"), cache.agent_caller(PAYER)))]


# ── the background settle: the token's key, and a late success ───────────────────────────────────────────────────

class _Resp:
    status_code = 200

    def __init__(self, body):
        self.body = body
        self.text = str(body)

    def json(self):
        return self.body


class _Client:
    def __init__(self, body):
        self.body = body
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, dict(headers or {})))
        return _Resp(self.body)


class _Sess:
    def __init__(self, auth):
        self.auth = auth

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, model, key):
        return self.auth

    async def commit(self):
        pass

    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None)


def _background(monkeypatch, *, status, body, key=None):
    helpers = importlib.import_module("agentvault_registry.background_tasks.reactor_helpers")
    sent = []

    async def _dispatch(event, data, dids, *, source_label="x"):
        sent.append((event, data.get("settlement_tx_id")))
        return 1

    async def _remote(db, did):
        return False
    client = _Client(body)
    auth = types.SimpleNamespace(id="tok-1", caller_did=PAYER, target_agent_did=PAYEE, amount=Decimal("2"),
                                 status=status, settlement_tx_id=None, settled_at=None, task_id=None)
    monkeypatch.setattr(helpers, "dispatch_webhook_for_agents", _dispatch)
    monkeypatch.setattr(a2a, "_get_settle_client", lambda: client)
    monkeypatch.setattr(a2a, "_is_local_agent", _remote)
    monkeypatch.delenv("A2A_SETTLE_VIA_SMART_SEND", raising=False)
    monkeypatch.setattr(a2a, "AsyncSessionLocal", lambda: _Sess(auth))
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    _run(a2a._process_settlement_async(auth_id="tok-1", caller_jwt="j", receiver_did=PAYEE, amount=Decimal("2"),
                                       message="m", contract_id=None, settlement_key=key))
    return auth, sent, client


DONE = {"transfer_id": "xf-9", "status": "completed"}


def test_the_background_settlement_sends_the_key_it_is_given(monkeypatch):
    _, _, client = _background(monkeypatch, status="settling", body=DONE, key=_key("tok-1"))
    assert client.calls[0][1].get("Idempotency-Key") == _key("tok-1")


def test_settle_keys_its_transfer_with_a_key_only_the_tokens_holders_can_derive(monkeypatch):
    # settle_payment hands the background settlement the key; the token id (public) does not suffice to derive it
    handed = []

    def _process(**kw):
        handed.append(kw)
        return asyncio.sleep(0)
    auth = types.SimpleNamespace(id="tok-1", caller_did=PAYER, target_agent_did=PAYEE, amount=Decimal("2"),
                                 status="consumed", token_hash=a2a._hash_token("apt_" + "ab" * 32), contract_id=None,
                                 task_id=None, settlement_tx_id=None)

    class _SettleDb:
        async def execute(self, stmt, *a, **k):
            return types.SimpleNamespace(scalar_one_or_none=lambda: auth, rowcount=1)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    async def _purse(db, agent, request):
        return agent, agent.did
    monkeypatch.setattr(a2a, "_process_settlement_async", _process)
    monkeypatch.setattr(a2a, "_payer_purse", _purse)
    monkeypatch.setattr(a2a._rb, "bond_mode", lambda: "off")
    monkeypatch.setattr(a2a._ep, "propagation_mode", lambda: "off")
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    out = _run(a2a.settle_payment(a2a.SettleRequest(token="apt_" + "ab" * 32), types.SimpleNamespace(
        headers={"Authorization": "Bearer jwt"}), current_agent=types.SimpleNamespace(did=PAYER), db=_SettleDb(),
        idempotency_key=None))
    assert out.status == "settling"
    [kw] = handed
    assert kw["settlement_key"] == a2a._settlement_key("tok-1", auth.token_hash)
    assert kw["settlement_key"].startswith("a2a-settle-tok-1-") and len(kw["settlement_key"]) > len("a2a-settle-tok-1-")


def test_a_record_under_the_token_id_alone_is_no_settlement_of_it(conn, monkeypatch):
    # what anyone reading the public feed could have sent: a transfer of their own under a2a-settle-<token id>
    _token(conn, "tok-1")
    _store(monkeypatch, _kept("teg.cross-registry-transfer", "tok-1",
                              {"body_hash": "x", "response": {"transfer_id": "xf-stranger", "status": "completed"}},
                              key="a2a-settle-tok-1"))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("failed", None)


def test_a_record_on_the_other_endpoint_is_not_this_settlement(conn, monkeypatch):
    # the payee is on this registry, so the settlement ran on /teg/transfer; a success kept on the cross-registry
    # endpoint under the same key is someone else's transfer
    _token(conn, "tok-1")
    LOCAL.add(PAYEE)
    _store(monkeypatch, _kept("teg.cross-registry-transfer", "tok-1",
                              {"body_hash": "x", "response": {"transfer_id": "xf-other", "status": "completed"}}))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("failed", None)


def test_a_transfer_that_completes_after_the_sweep_failed_its_token_is_recorded(monkeypatch):
    auth, sent, _ = _background(monkeypatch, status="failed", body=DONE)
    assert (auth.status, auth.settlement_tx_id) == ("settled", "xf-9") and auth.settled_at is not None
    assert sent == [("payment.settled", "xf-9")]


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_nothing_under_the_key_fails_the_token(conn, monkeypatch):
    _token(conn, "tok-1")
    _store(monkeypatch, {})
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("failed", None)


def test_control_a_local_payees_settlement_is_read_on_the_local_endpoint(conn, monkeypatch):
    _token(conn, "tok-1")
    LOCAL.add(PAYEE)
    _store(monkeypatch, _kept("teg.transfer", "tok-1",
                              {"body_hash": _own("tok-1", "teg.transfer"),
                               "response": {"transaction_id": "tx-5", "status": "completed"}}))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settled", "tx-5")


def test_control_a_kept_failed_answer_fails_the_token(conn, monkeypatch):
    _token(conn, "tok-1")
    _store(monkeypatch, _kept("teg.cross-registry-transfer", "tok-1",
                              {"body_hash": _own("tok-1", "teg.cross-registry-transfer"),
                               "response": {"transfer_id": "xf-9", "status": "failed",
                                                              "error_message": "refused"}}))
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("failed", None)


def test_control_a_registry_without_a_store_fails_a_stale_token_as_before(conn, monkeypatch):
    _token(conn, "tok-1")
    monkeypatch.delenv("REDIS_URL")
    _store(monkeypatch, none=True)
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("failed", None)


def test_control_a_token_inside_the_wait_is_not_touched(conn, monkeypatch):
    _token(conn, "tok-1", verified_s_ago=10)
    _store(monkeypatch, {})
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-1") == ("settling", None)


def test_control_expired_authorized_and_consumed_tokens_still_expire(conn, monkeypatch):
    _token(conn, "tok-a", status="authorized")
    _token(conn, "tok-c", status="consumed")
    conn.execute(sa.update(T.__table__).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=5)))
    conn.commit()
    _store(monkeypatch, {})
    _run(sweep._expire_stale_tokens())
    assert _row(conn, "tok-a")[0] == "expired" and _row(conn, "tok-c")[0] == "expired"


def test_control_a_failed_transfer_after_a_sweep_leaves_the_token_failed_and_silent(monkeypatch):
    auth, sent, _ = _background(monkeypatch, status="failed", body={"transfer_id": "xf-9", "status": "failed"})
    assert (auth.status, auth.settlement_tx_id) == ("failed", None) and sent == []


def test_control_an_already_settled_token_is_left_alone(monkeypatch):
    auth, sent, _ = _background(monkeypatch, status="settled", body=DONE)
    assert auth.status == "settled" and auth.settlement_tx_id is None and sent == []

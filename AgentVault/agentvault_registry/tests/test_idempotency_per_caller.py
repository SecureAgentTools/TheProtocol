"""D6-777 (2026-10-17): an Idempotency-Key record is the caller's, on every route that takes the header.

Every record is kept under the caller the route acts for, the keys a route derives from the client's key (escrow legs,
ledger events, room receipts) come from the caller-bound key (services/idempotency/cache.caller_key), and a record an
older image kept under the key alone is neither replayed nor run past. So two members of one organization who send
the same key value each move their own units, a member's retry replays only its own legs, and an agent's kept answer
(a payment token included) is given again only to that agent.

Through FastAPI on the real routes: organizations (fund, remit), a2a_payment (authorize), bundles (restore) and the
token bridge (transfer). The database, the TEG's escrow mover and Redis are doubles (the mover answers a key it has seen
with that key's leg, as the TEG's /admin/exchange/move does). RED on 15620967: every test except the two controls
(the same caller's retry; another body under the same caller), which are green before and after; the sweep and record
tests need the caller API this change adds.
"""
from __future__ import annotations

import ast
import json
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import a2a_payment
from agentvault_registry.routers import bundles as bundles_router
from agentvault_registry.routers import organizations as orgs
from agentvault_registry.services import exchange_service as xs
from agentvault_registry.services import org_treasury as ot
from agentvault_registry.services.bundles import service as bundles_svc
from agentvault_registry.services.idempotency import cache

ORG = "6b1f6f4e-3c2a-4d7e-9a51-2f0c9d8e7a10"
TREASURY = "did:theprotocol:orgtreasury-acme"
ESCROW = xs.EXCHANGE_ESCROW_SENTINEL
OTHERS_DEPOSITS = Decimal("1000")   # what other traders hold in the shared escrow
X, Y = "did:theprotocol:member-agent-x", "did:theprotocol:member-agent-y"
P, Q = "did:theprotocol:org-agent-p", "did:theprotocol:org-agent-q"


class FakeRedis:
    """The commands the cache sends (GET, SET with NX and EX, DELETE, EXISTS, TTL and the kept claim's EVAL), no clock."""

    def __init__(self):
        self.data = {}

    async def get(self, k):
        return self.data.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.data:
            return None
        self.data[k] = str(v)
        return True

    async def delete(self, *ks):
        return sum(1 for k in ks if self.data.pop(k, None) is not None)

    async def exists(self, k):
        return 1 if k in self.data else 0

    async def ttl(self, k):
        return 60 if k in self.data else -2

    async def eval(self, script, numkeys, *args):
        k1, k2, claim, _ttl, token, _beat = args
        if k1 in self.data:
            return 0
        self.data[k1], self.data[k2] = claim, token
        return 1


class Mover:
    """The TEG's /admin/exchange/move as the registry sees it: a key that already ran answers its own leg again
    (exref replay, before any balance check and whatever the request asks), a fresh debit beyond the source's balance is
    refused, and a leg can be made to fail once."""

    def __init__(self, balances, fail_once=()):
        self.bal = {k: Decimal(v) for k, v in balances.items()}
        self.done = {}
        self.fail_once = list(fail_once)
        self.keys = []

    async def agent_balance(self, did):
        return self.bal.get(did, Decimal("0"))

    async def move(self, src, dst, amount, reason, key, floor=None, timeout_s=35.0):
        self.keys.append(key)
        if key in self.done:
            return dict(self.done[key], idempotent_replay=True)
        for i, (s, d) in enumerate(self.fail_once):
            if (s, d) == (src, dst):
                del self.fail_once[i]
                raise xs.MoverError(502, "exchange mover timeout: ReadTimeout")
        if src != ESCROW and self.bal.get(src, Decimal("0")) < amount:
            raise xs.MoverError(400, "exchange mover 400: exchange/move transfer failed: Insufficient balance")
        self.bal[src] = self.bal.get(src, Decimal("0")) - amount
        self.bal[dst] = self.bal.get(dst, Decimal("0")) + amount
        self.done[key] = {"transaction_id": f"tx-{len(self.done) + 1}", "status": "completed"}
        return self.done[key]


@pytest.fixture
def redis(monkeypatch):
    from agentvault_registry.background_tasks import leader
    r = FakeRedis()

    async def _get():
        return r
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setenv("IDEMPOTENCY_DURABLE", "off")   # the durable copy has its own tests (test_idempotency_durable)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.005)
    return r


# ── the organization treasury: fund and remit ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(monkeypatch, redis):
    """The org routes on a FastAPI app: the developer or agent each request names, a member of ORG; the treasury, the
    membership checks, the procurement cap and the ledger event stubbed; the receipts the routes post recorded."""
    receipts = []

    async def _member(org_id, developer, db, required_role=None):
        return SimpleNamespace(id=org_id, owner_id=developer.id)

    async def _own(db, org_id):
        return TREASURY

    async def _none(*a, **k):
        return None

    async def _receipt(db, org_id, *, kind, amount, ref, counterparty=None, **k):
        receipts.append((kind, ref, amount))

    monkeypatch.setattr(orgs, "get_organization_with_permission", _member)
    monkeypatch.setattr(ot, "_own_treasury_or_raise", _own)
    monkeypatch.setattr(ot, "_org_agent_or_raise", _none)
    monkeypatch.setattr(ot, "_procurement_cap_or_raise", _none)
    monkeypatch.setattr(ot, "_emit_org_money_event", lambda *a, **k: None)
    import agentvault_registry.services.admin_audit as audit
    import agentvault_registry.services.org_room_events as rooms
    monkeypatch.setattr(audit, "log_admin_action", _none)
    monkeypatch.setattr(rooms, "post_org_receipt", _receipt)

    def _developer(request: Request):
        return SimpleNamespace(id=int(request.headers["x-test-developer"]), email="m@example.org")

    def _agent(request: Request):
        return SimpleNamespace(did=request.headers["x-test-agent"], id=9, status="active")

    app = FastAPI()
    app.include_router(orgs.router)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[security.get_current_developer] = _developer
    app.dependency_overrides[security.get_current_agent] = _agent
    app.dependency_overrides[security.verify_agent_token] = lambda: {"type": "agent"}
    client = TestClient(app, raise_server_exceptions=False)

    def _use(mover):
        monkeypatch.setattr(xs, "mover", mover)
        return mover
    return SimpleNamespace(client=client, use=_use, receipts=receipts)


def _fund(org, developer, agent, amount, key):
    return org.client.post(f"/api/v1/organizations/{ORG}/treasury/fund", json={"agent_did": agent, "amount": amount},
                           headers={"x-test-developer": str(developer), "Idempotency-Key": key})


def _remit(org, agent, amount, key):
    return org.client.post(f"/api/v1/organizations/{ORG}/treasury/remit", json={"amount": amount},
                           headers={"x-test-agent": agent, "Idempotency-Key": key})


def test_two_members_sending_one_key_value_each_fund_their_own_move(org):
    m = org.use(Mover({TREASURY: "100", ESCROW: OTHERS_DEPOSITS}))
    a = _fund(org, 5, X, "10", "order-1")
    b = _fund(org, 6, Y, "20", "order-1")   # another admin of the same organization, the same key value
    assert (a.status_code, b.status_code) == (200, 200), (a.text[:300], b.text[:300])
    assert m.bal.get(Y, Decimal("0")) == Decimal("20"), \
        "the second member's fund was answered with the first member's legs: its agent received nothing"
    assert (m.bal[TREASURY], m.bal[X], m.bal[ESCROW]) == (Decimal("70"), Decimal("10"), OTHERS_DEPOSITS)
    refs = [ref for kind, ref, _amount in org.receipts if kind == "treasury.fund"]
    assert len(refs) == 2 and refs[0] != refs[1], "the second member's receipt shared the first one's reference"


def test_a_member_never_finishes_another_members_half_finished_move(org):
    """The first member's credit leg failed: its units wait in the escrow until its own retry. A second member's
    request under the same key value runs its own two legs."""
    m = org.use(Mover({TREASURY: "100", ESCROW: OTHERS_DEPOSITS}, fail_once=[(ESCROW, X)]))
    first = _fund(org, 5, X, "10", "order-2")
    assert first.status_code == 502, first.text[:300]   # its debit ran, its credit did not
    second = _fund(org, 6, Y, "30", "order-2")
    assert second.status_code == 200, second.text[:300]
    assert m.bal[ESCROW] >= OTHERS_DEPOSITS, "the escrow paid out more than it received"
    assert (m.bal[TREASURY], m.bal.get(Y)) == (Decimal("60"), Decimal("30"))
    again = _fund(org, 5, X, "10", "order-2")   # the first member's own retry finishes its own move
    assert again.status_code == 200 and (m.bal[X], m.bal[ESCROW]) == (Decimal("10"), OTHERS_DEPOSITS)


def test_two_agents_of_one_organization_each_remit_their_own_units(org):
    m = org.use(Mover({P: "40", Q: "40", ESCROW: OTHERS_DEPOSITS}))
    a = _remit(org, P, "10", "remit-1")
    b = _remit(org, Q, "15", "remit-1")
    assert (a.status_code, b.status_code) == (200, 200), (a.text[:300], b.text[:300])
    assert m.bal[Q] == Decimal("25"), "the second agent's remit was answered with the first agent's legs"
    assert (m.bal[P], m.bal[TREASURY], m.bal[ESCROW]) == (Decimal("30"), Decimal("25"), OTHERS_DEPOSITS)


def test_control_the_same_members_retry_replays_its_own_legs(org):
    m = org.use(Mover({TREASURY: "100", ESCROW: OTHERS_DEPOSITS}))
    assert _fund(org, 5, X, "10", "order-3").status_code == 200
    again = _fund(org, 5, X, "10", "order-3")
    assert again.status_code == 200 and again.json()["result"]["idempotent_replay"] is True
    assert (m.bal[TREASURY], m.bal[X]) == (Decimal("90"), Decimal("10")), "a retry paid twice"


# ── a cached route: the A2A payment token ──────────────────────────────────────────────────────────────────────────

class _A2ADb:
    def __init__(self):
        self.added = []

    async def execute(self, stmt, params=None):
        return SimpleNamespace(scalar_one_or_none=lambda: None, fetchall=lambda: [], rowcount=1)

    async def scalar(self, stmt):
        return 0   # no pending tokens

    def add(self, obj):
        obj.id = f"tok-{len(self.added) + 1:04d}"
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def a2a(monkeypatch, redis):
    async def _admit(*a, **k):
        return None
    monkeypatch.setattr(a2a_payment._rb, "gate", _admit)
    monkeypatch.setattr(a2a_payment._ep, "gate", _admit)
    monkeypatch.setattr(a2a_payment, "enforce_agent_spend", _admit)
    monkeypatch.setattr(a2a_payment, "emit_or_report", _admit)
    db = _A2ADb()

    def _agent(request: Request):
        return SimpleNamespace(did=request.headers["x-test-agent"], id=3, liquid_balance=100, status="active")

    app = FastAPI()
    app.include_router(a2a_payment.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[security.get_current_agent] = _agent
    app.dependency_overrides[security.verify_agent_token] = lambda: {"type": "agent"}
    client = TestClient(app, raise_server_exceptions=False)

    def _authorize(agent, key, amount="1.5"):
        return client.post("/api/v1/a2a-payment/authorize",
                           json={"target_agent_did": "did:theprotocol:elsewhere:service", "amount": amount},
                           headers={"x-test-agent": agent, "Idempotency-Key": key})
    return SimpleNamespace(authorize=_authorize, db=db, redis=redis)


def test_another_agent_never_receives_a_payment_token_kept_under_the_same_key(a2a):
    first = a2a.authorize("did:theprotocol:payer-a", "pay-1")
    second = a2a.authorize("did:theprotocol:payer-b", "pay-1")   # the same key value and the same body
    assert (first.status_code, second.status_code) == (200, 200), (first.text[:300], second.text[:300])
    assert second.json()["token"] != first.json()["token"], "the second agent was handed the first agent's token"
    assert len(a2a.db.added) == 2 and a2a.db.added[1].caller_did == "did:theprotocol:payer-b"


def test_control_the_same_agents_retry_gets_its_own_token_and_another_body_is_refused(a2a):
    first = a2a.authorize("did:theprotocol:payer-a", "pay-2")
    again = a2a.authorize("did:theprotocol:payer-a", "pay-2")
    assert again.status_code == 200 and again.json()["token"] == first.json()["token"] and len(a2a.db.added) == 1
    other = a2a.authorize("did:theprotocol:payer-a", "pay-2", amount="2")
    assert other.status_code == 422 and "different request payload" in other.text and len(a2a.db.added) == 1


def test_a_record_kept_before_records_were_the_callers_is_never_replayed(a2a):
    """A record an older image kept under the scope and the key alone names no caller: it is not handed to anyone,
    its own writer included, and the request mints nothing (its answer says the outcome is not known, so the console
    keeps the key and the payout lane holds)."""
    target = "did:theprotocol:elsewhere:service"
    full = a2a_payment.AuthorizeRequest(target_agent_did=target, amount="1.5").model_dump(mode="json")
    kept = a2a_payment.AuthorizeResponse(token="apt_" + "0" * 64, token_id="tok-old", amount="1.5",
                                         target_agent_did=target, expires_at="2026-10-17T05:00:00+00:00")
    a2a.redis.data["idempotency:a2a.authorize:pay-3"] = json.dumps({
        "body_hash": cache._body_hash(full), "response": kept.model_dump(mode="json")})
    r = a2a.authorize("did:theprotocol:payer-a", "pay-3")
    assert r.status_code == 422, (r.status_code, r.text[:300])
    assert "apt_" not in r.text and "(outcome not known)" in r.text and a2a.db.added == []


# ── a service with its own record: the bundle restore ──────────────────────────────────────────────────────────────

def test_two_developers_sending_one_key_value_each_restore_their_own_bundle(monkeypatch, redis):
    ran = []

    async def _restore(db, installer_dev_id, bundle_row_id, conflict_resolution, mode, include_cicd):
        ran.append(installer_dev_id)
        return {"bundle_id": bundle_row_id, "installer": installer_dev_id, "produced_agents": []}
    monkeypatch.setattr(bundles_svc, "restore_bundle", _restore)

    def _developer(request: Request):
        return SimpleNamespace(id=int(request.headers["x-test-developer"]))
    app = FastAPI()
    app.include_router(bundles_router.router)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[security.get_current_developer] = _developer
    c = TestClient(app, raise_server_exceptions=False)

    def _go(dev):
        return c.post("/bundles/b-1/restore", json={}, headers={"x-test-developer": str(dev), "Idempotency-Key": "r-1"})
    a, b, a2 = _go(5), _go(6), _go(5)
    assert (a.status_code, b.status_code) == (200, 200), (a.text[:300], b.text[:300])
    assert b.json()["installer"] == 6 and ran == [5, 6], "the second developer was refused over the first one's key"
    assert a2.status_code == 200 and a2.json()["installer"] == 5 and ran == [5, 6], "a retry restored twice"


# ── the bridge transfer: its answer is kept under the client's key ─────────────────────────────────────────────────

def test_a_bridge_transfer_retried_under_its_key_is_answered_again_and_locks_once(monkeypatch, redis):
    """The answer is kept under the client's key (the bridge row keeps its own key, bridge-<id>, apart): a retry under
    the client's key is answered with the first transfer, and the units are locked once."""
    from agentvault_registry.core.mainframe_gate import require_mainframe_only
    from agentvault_registry.routers import token_bridge
    teg = []

    async def _teg(endpoint, body):
        teg.append(endpoint)
        return {"tx_id": f"teg-{len(teg)}"}

    async def _remote(url, endpoint, body):
        return {"status": "minted", "mint_tx_id": "mint-1"}

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(token_bridge, "_call_teg", _teg)
    monkeypatch.setattr(token_bridge, "_call_remote_frame", _remote)
    monkeypatch.setattr(token_bridge, "enforce_agent_spend", _none)
    emitter_calls: list = []

    async def _emitted(*a, **k):
        emitter_calls.append((a, k))
        return None
    monkeypatch.setattr(token_bridge, "emit_or_report", _emitted)
    monkeypatch.setattr(token_bridge, "get_event_emitter", lambda: None)
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")

    class _Db:
        def add(self, obj):
            pass

        async def commit(self):
            pass

    app = FastAPI()
    app.include_router(token_bridge.router)
    app.dependency_overrides[get_db] = lambda: _Db()
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did="did:theprotocol:a:sender", id=1)
    app.dependency_overrides[security.verify_agent_token] = lambda: {"type": "agent"}
    c = TestClient(app, raise_server_exceptions=False)
    body = {"target_agent_did": "did:theprotocol:b:holder", "amount": "5",
            "target_frame_url": "https://frame-b.example.invalid:8443"}
    first = c.post("/api/v1/bridge/transfer", json=body, headers={"Idempotency-Key": "bridge-retry-1"})
    reported = len(emitter_calls)
    again = c.post("/api/v1/bridge/transfer", json=body, headers={"Idempotency-Key": "bridge-retry-1"})
    assert (first.status_code, again.status_code) == (200, 200), (first.text[:300], again.text[:300])
    assert len(emitter_calls) == reported, "the replay reported the transfer a second time"
    assert again.json()["bridge_tx_id"] == first.json()["bridge_tx_id"] and teg == ["lock"]


# ── the readers: the stale-settlement sweep reads the record the transfer kept for the payer's side ─────────────────

def _kept_settlement(tid, caller, answer):
    """The settlement's transfer as the cross-registry endpoint keeps it: a kept attempt under the token's settlement
    key, as `caller` (the payer, or the wallet an anchored hand pays from), for the settlement's own request (the sweep
    trusts no other record under the key; this planted {"receiver_did": "r"} until 2026-10-17)."""
    import asyncio
    from tests.test_a2a_settle_sweep_asks_first import _key, _own_body

    async def _go():
        a = await cache.begin_attempt("teg.cross-registry-transfer", _key(tid),
                                      _own_body(tid, "teg.cross-registry-transfer"), principal=caller)

        async def _work():
            a.mark_dispatched()
            return answer
        await cache.run_kept(a, _work, error_moved_nothing=lambda s, d: False)
    asyncio.run(_go())


def test_the_sweep_settles_a_token_from_the_payers_own_kept_transfer(redis, monkeypatch):
    import asyncio
    from tests import test_a2a_settle_sweep_asks_first as sw
    with sw_db(monkeypatch) as conn:
        sw._token(conn, "tok-1")
        _kept_settlement("tok-1", cache.agent_caller(sw.PAYER), {"status": "completed", "transfer_id": "xf-1"})
        asyncio.run(sw.sweep._expire_stale_tokens())
        assert sw._row(conn, "tok-1") == ("settled", "xf-1")


def test_the_sweep_settles_an_anchored_hands_token_from_its_wallets_kept_transfer(redis, monkeypatch):
    import asyncio
    from agentvault_registry.services import spawn_anchor
    from tests import test_a2a_settle_sweep_asks_first as sw
    wallet = "did:theprotocol:eu.theprotocol.cloud:wallet-0000"

    async def _birth(db, did):
        return {"issuer": wallet, "anchored": True} if did == sw.PAYER else None

    async def _walk(db, did):
        return did
    monkeypatch.setattr(spawn_anchor, "_birth_token_of", _birth)
    monkeypatch.setattr(spawn_anchor, "_walk_to_wallet_holder", _walk)
    with sw_db(monkeypatch) as conn:
        sw._token(conn, "tok-2")
        _kept_settlement("tok-2", cache.agent_caller(wallet), {"status": "completed", "transfer_id": "xf-2"})
        asyncio.run(sw.sweep._expire_stale_tokens())
        assert sw._row(conn, "tok-2") == ("settled", "xf-2")


def test_control_the_sweep_never_settles_from_another_agents_record(redis, monkeypatch):
    import asyncio
    from tests import test_a2a_settle_sweep_asks_first as sw
    with sw_db(monkeypatch) as conn:
        sw._token(conn, "tok-3")
        _kept_settlement("tok-3", cache.agent_caller(sw.PAYEE), {"status": "completed", "transfer_id": "theirs"})
        asyncio.run(sw.sweep._expire_stale_tokens())
        assert sw._row(conn, "tok-3") == ("failed", None)


class sw_db:
    """The sweep test's SQLite session (tests/test_a2a_settle_sweep_asks_first.conn), as a context manager here."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch

    def __enter__(self):
        import sqlalchemy as sa
        from sqlalchemy.pool import StaticPool
        from tests import test_a2a_settle_sweep_asks_first as sw
        self.eng = sa.create_engine("sqlite://", poolclass=StaticPool)
        sw.T.__table__.create(self.eng)
        self.c = self.eng.connect()

        async def _remote(db, did):
            return False
        self.monkeypatch.setattr(sw.sweep, "async_session_factory", lambda: sw._Db(self.c))
        self.monkeypatch.setattr(sw.durable, "enabled", lambda: False)
        self.monkeypatch.setattr(sw.a2a, "_is_local_agent", _remote)
        self.monkeypatch.setenv("REDIS_URL", "redis://test")
        return self.c

    def __exit__(self, *a):
        self.c.close()
        return False


# ── the record itself ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_record_needs_its_caller_and_asks_for_it_before_any_store(redis):
    import asyncio
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            asyncio.run(cache.idempotency_lookup("teg.transfer", "k", {"a": 1}, principal=bad))
        with pytest.raises(ValueError):
            asyncio.run(cache.begin_attempt("teg.transfer", "k", {"a": 1}, principal=bad))
    with pytest.raises(ValueError):
        cache.agent_caller(None)
    assert redis.data == {}, "a request without its caller touched the store"


def test_a_caller_key_is_the_callers_alone_and_fits_a_leg():
    a, b = cache.developer_caller(5), cache.developer_caller(6)
    assert cache.caller_key(a, "k") == cache.caller_key(a, "k") != cache.caller_key(b, "k")
    assert cache.caller_key(a, "k") != cache.caller_key(a, "k2")
    assert len(cache.caller_key(a, "x" * 4000)) == 33
    ref = ot.move_ref("remit", ORG, cache.agent_caller("did:theprotocol:" + "z" * 200), "k" * 500)
    assert len(f"{ref}:out") <= 128, "the TEG takes a leg key of up to 128 characters"
    assert not ref.startswith(f"orgremit-{ORG}-"), "a leg written before shares the new form"


def test_two_admins_of_a_listing_each_move_its_treasury_on_their_own_legs(monkeypatch):
    """The AGORA treasury transfer derives its escrow legs from the key as well: the legs are the admin's."""
    import asyncio
    m = Mover({"did:theprotocol:org-acme-treasury": "100", ESCROW: OTHERS_DEPOSITS})
    listing = SimpleNamespace(id=7, symbol="ACME", treasury_agent_did="did:theprotocol:org-acme-treasury")

    class _Db:
        async def execute(self, *a, **k):
            return SimpleNamespace(scalar_one_or_none=lambda: listing)

    async def _admin(db, org_id, dev_id, role):
        return True
    monkeypatch.setattr(xs.OrganizationService, "check_member_permission", _admin)
    monkeypatch.setattr(xs, "ExchangeMover", lambda: m)
    for dev, dest in ((5, X), (6, Y)):
        asyncio.run(xs.treasury_move(_Db(), ORG, "ACME", dest, Decimal("10"), "transfer", SimpleNamespace(id=dev),
                                     idempotency_key="move-1"))
    assert m.bal.get(Y) == Decimal("10") and m.bal[ESCROW] == OTHERS_DEPOSITS


def test_every_keyed_call_in_the_registry_names_its_caller():
    """A gate over the whole package: every call of the record API passes its caller (a call that does not is a
    TypeError on its path, and this finds the ones no test reaches)."""
    root = pathlib.Path(cache.__file__).resolve().parents[2]   # .../agentvault_registry
    need = {"idempotency_lookup": "principal", "idempotency_store": "principal", "begin_attempt": "principal",
            "stored_answer": "callers"}
    missing, seen = [], 0
    for f in root.rglob("*.py"):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            if name in need:
                seen += 1
                if need[name] not in {k.arg for k in n.keywords}:
                    missing.append(f"{f.relative_to(root)}:{n.lineno} {name}")
    assert seen >= 40, f"the gate saw {seen} calls: it is not looking at the registry"
    assert missing == [], missing

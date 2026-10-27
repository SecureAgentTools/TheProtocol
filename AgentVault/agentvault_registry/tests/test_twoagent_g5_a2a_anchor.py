"""§TWOAGENT G5 (2026-09-23) — a walletless (anchored) hand can buy a service; it pays from the wallet it spends from.

Measured on EU (finding 32): the Scrivener spawned a child (perms a2a.pay, teg.transfer, teg.transfer_xreg, fx.quote;
budget 3 ECU; counterparty_allow = the ASIA seller). With its birth token on X-Capability-Token,
`POST /a2a-payment/authorize` answered 402 "Insufficient balance: 0 ECU available, 2.041529 ECU required" while the
parent held 749.37 ECU: authorize read the CALLER's balance and settle transferred with the caller's JWT, and neither
asked the spawn anchor that /teg/send, contracts and the exchange honour.

Now authorize admits the whole spend (the hand's caveats, then the purse's balance and the purse's own gates for the
settlement rail, read-only, before any service is delivered) and settle moves the admitted amount AS the purse, so
the hand's budget is charged once. The /buy rail forwards the capability token on its inner calls. And on the way:
the birth token's `counterparty_allow` caveat, written at spawn and checked only at attenuation, now binds the money
rails (fail-closed when a spend names no counterparty).

RED on the pre-change tree: every test but the controls at the end.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

import pytest
from fastapi import HTTPException

a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")
anchor = importlib.import_module("agentvault_registry.services.spawn_anchor")
authz = importlib.import_module("agentvault_registry.agent_authz")
idem = importlib.import_module("agentvault_registry.services.idempotency")
security = importlib.import_module("agentvault_registry.security")

CHILD = "did:theprotocol:eu.theprotocol.cloud:hand-0000"
PARENT = "did:theprotocol:eu.theprotocol.cloud:parent-0000"
SELLER = "did:theprotocol:asia.theprotocol.cloud:seller-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(coro)
        loop.run_until_complete(asyncio.sleep(0))  # let a create_task'd settlement body run
        return out
    finally:
        loop.close()


class _Headers(dict):
    def get(self, k, default=None):
        for key, v in self.items():
            if key.lower() == k.lower():
                return v
        return default


def _request(*, cap=None, bearer="child-jwt"):
    h = _Headers({"Authorization": f"Bearer {bearer}"})
    if cap is not None:
        h["X-Capability-Token"] = "att_birth"
    return types.SimpleNamespace(headers=h, state=types.SimpleNamespace(ironkey_capability=cap),
                                 url=types.SimpleNamespace(path="/api/v1/a2a-payment/x"), client=None)


BIRTH = {"id": 41, "issuer_did": PARENT, "caveats": {"birth": True, "anchored": True, "permissions": ["a2a.pay"]}}
child = types.SimpleNamespace(did=CHILD, id=7, liquid_balance=0)
parent = types.SimpleNamespace(did=PARENT, id=3, liquid_balance=Decimal("749.36896"))


def _wire_anchor(monkeypatch, purse=parent):
    monkeypatch.setenv("SPAWN_WALLET_ANCHOR_MODE", "on")

    async def _walk(db, start):
        return purse.did if purse else None

    async def _get(db, did):
        return purse if purse and did == purse.did else None

    async def _hand(*a, **k):
        return None
    monkeypatch.setattr(anchor, "_walk_to_wallet_holder", _walk)
    import agentvault_registry.crud.agent as crud_agent
    monkeypatch.setattr(crud_agent, "get_agent_by_did", _get)
    import agentvault_registry.services.liability as liab
    monkeypatch.setattr(liab, "record_hand_action", _hand)


class _AuthDB:
    def __init__(self):
        self.added = []

    async def scalar(self, *a, **k):
        return 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = "tok-0001"

    async def execute(self, *a, **k):
        return types.SimpleNamespace(rowcount=1)


def _wire_authorize(monkeypatch):
    received = []

    async def _none(*a, **k):
        return None

    async def _lookup(*a, **k):
        return None, None

    async def _emit(emitter, **kw):
        received.append(kw)
    monkeypatch.setattr(a2a._rb, "gate", _none)
    monkeypatch.setattr(a2a._ep, "gate", _none)
    monkeypatch.setattr(a2a, "enforce_agent_spend", _none)
    monkeypatch.setattr(idem, "idempotency_lookup", _lookup)
    monkeypatch.setattr(idem, "idempotency_store", _none)
    monkeypatch.setattr(a2a, "emit_or_report", _emit)
    monkeypatch.setattr(a2a, "get_event_emitter", lambda: None)
    monkeypatch.setattr(a2a, "_issuer_url", lambda r: "https://eu.example")
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    return received


def _authorize(request, amount="2.041529"):
    req = a2a.AuthorizeRequest(target_agent_did=SELLER, amount=amount)
    return _run(a2a.authorize_payment(req, request, current_agent=child, db=_AuthDB(), idempotency_key=None))


# ── authorize ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_anchored_hand_is_authorized_against_the_wallet_it_spends_from(monkeypatch):
    _wire_anchor(monkeypatch)
    received = _wire_authorize(monkeypatch)
    out = _authorize(_request(cap=BIRTH))
    assert out.amount == "2.041529" and out.target_agent_did == SELLER
    assert len(received) == 1, "the authorization is recorded on the ledger exactly once"
    assert received[0]["data"]["purse_did"] == PARENT and received[0]["data"]["caller_did"] == CHILD


def test_an_empty_purse_is_refused_and_the_refusal_names_it(monkeypatch):
    _wire_anchor(monkeypatch, purse=types.SimpleNamespace(did=PARENT, id=3, liquid_balance=Decimal("1")))
    _wire_authorize(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _authorize(_request(cap=BIRTH))
    assert e.value.status_code == 402 and PARENT in e.value.detail and "spends from" in e.value.detail


def test_a_purse_that_could_not_settle_is_refused_before_anything_is_delivered(monkeypatch):
    _wire_anchor(monkeypatch)
    _wire_authorize(monkeypatch)
    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce")

    async def _perms(db, did, act=None):
        return {"teg.transfer", "a2a.pay"}  # no teg.transfer_xreg, and the seller is on another frame

    async def _local(db, did):
        return False
    monkeypatch.setattr(authz, "resolve_agent_permissions", _perms)
    monkeypatch.setattr(a2a, "_is_local_agent", _local)
    with pytest.raises(HTTPException) as e:
        _authorize(_request(cap=BIRTH))
    assert e.value.status_code == 403 and "teg.transfer_xreg" in e.value.detail and "Nothing was authorized" in e.value.detail


def test_the_purses_own_spend_policy_is_asked_at_authorize(monkeypatch):
    _wire_anchor(monkeypatch)
    _wire_authorize(monkeypatch)
    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce")

    async def _perms(db, did, act=None):
        return {"teg.transfer", "teg.transfer_xreg"}

    async def _local(db, did):
        return False

    async def _policy(db, did, amount, **kw):
        return (False, "counterparty_not_allowlisted") if did == PARENT else (True, None)
    monkeypatch.setattr(authz, "resolve_agent_permissions", _perms)
    monkeypatch.setattr(authz, "check_spend_policy", _policy)
    monkeypatch.setattr(a2a, "_is_local_agent", _local)
    with pytest.raises(HTTPException) as e:
        _authorize(_request(cap=BIRTH))
    assert e.value.status_code == 403 and "counterparty_not_allowlisted" in e.value.detail


# ── settle ───────────────────────────────────────────────────────────────────────────────────────────────────────

class _SettleDB:
    def __init__(self, auth):
        self.auth = auth
        self.n = 0

    async def execute(self, stmt, *a, **k):
        self.n += 1
        if self.n == 1:  # the SELECT of the authorization
            return types.SimpleNamespace(scalar_one_or_none=lambda: self.auth)
        return types.SimpleNamespace(rowcount=1)  # the atomic claim

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _settle(monkeypatch, request):
    fired = []

    async def _body(**kw):
        fired.append(kw)
    monkeypatch.setattr(a2a, "_process_settlement_async", _body)
    monkeypatch.setattr(a2a._rb, "bond_mode", lambda: "off")
    monkeypatch.setattr(a2a._ep, "propagation_mode", lambda: "off")
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    auth = types.SimpleNamespace(id="tok-0001", caller_did=CHILD, target_agent_did=SELLER, amount=Decimal("2.041529"),
                                 status="consumed", settlement_tx_id=None, contract_id=None, task_id=None)
    out = _run(a2a.settle_payment(a2a.SettleRequest(token="apt_x", success=True), request,
                                  current_agent=child, db=_SettleDB(auth), idempotency_key=None))
    return out, fired


def test_an_anchored_hands_settlement_moves_the_money_as_its_purse(monkeypatch):
    _wire_anchor(monkeypatch)
    out, fired = _settle(monkeypatch, _request(cap=BIRTH))
    assert out.status == "settling" and len(fired) == 1
    import jwt
    claims = jwt.decode(fired[0]["caller_jwt"], security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert claims["sub"] == PARENT and claims["agent_id"] == "3" and claims["type"] == "agent"
    assert claims["act"] == {"sub": "service:a2a-settle", "reason": "anchored-hand", "hand": CHILD}
    assert fired[0]["receiver_did"] == SELLER and fired[0]["amount"] == Decimal("2.041529")


def test_the_buy_rail_forwards_the_capability_token_to_its_inner_calls():
    h = a2a._caller_headers(_request(cap=BIRTH), "child-jwt")
    assert h == {"Authorization": "Bearer child-jwt", "X-Capability-Token": "att_birth"}


# ── on the way: the birth token's counterparty_allow binds the money rails ─────────────────────────────────────

def _spend(monkeypatch, *, counterparty, caveats):
    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce")
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")

    async def _ok(*a, **k):
        return True, None

    async def _org(db, did):
        return {}

    async def _audit(*a, **k):
        return None
    monkeypatch.setattr(authz, "check_spend_policy", _ok)
    import agentvault_registry.services.org_policy as op
    monkeypatch.setattr(op, "get_org_settings", _org)
    import agentvault_registry.services.admin_audit as aa
    monkeypatch.setattr(aa, "log_ironkey_action", _audit)
    req = types.SimpleNamespace(state=types.SimpleNamespace(ironkey_capability={"id": 41, "caveats": caveats}))
    db = types.SimpleNamespace(execute=_budget_ok)
    return _run(security.enforce_agent_spend(db, CHILD, "1", counterparty_did=counterparty, request=req))


async def _budget_ok(*a, **k):
    return types.SimpleNamespace(rowcount=1)


def test_a_counterparty_bound_token_cannot_pay_anyone_else(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _spend(monkeypatch, counterparty="did:theprotocol:eu.theprotocol.cloud:someone-else",
               caveats={"counterparty_allow": [SELLER]})
    assert e.value.status_code == 403 and "counterparty_allow" in e.value.detail


def test_a_counterparty_bound_token_cannot_make_a_spend_that_names_no_counterparty(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _spend(monkeypatch, counterparty=None, caveats={"counterparty_allow": [SELLER]})
    assert e.value.status_code == 403 and "names no counterparty" in e.value.detail


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_an_ordinary_payer_still_needs_its_own_balance(monkeypatch):
    _wire_authorize(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _authorize(_request(cap=None))
    assert e.value.status_code == 402 and "spends from" not in e.value.detail


def test_control_an_ordinary_payers_settlement_uses_its_own_bearer(monkeypatch):
    out, fired = _settle(monkeypatch, _request(cap=None, bearer="own-jwt"))
    assert out.status == "settling" and fired[0]["caller_jwt"] == "own-jwt"


def test_control_the_allowed_counterparty_is_paid(monkeypatch):
    assert _spend(monkeypatch, counterparty=SELLER, caveats={"counterparty_allow": [SELLER]}) is None


def test_control_a_token_without_the_caveat_is_unchanged(monkeypatch):
    assert _spend(monkeypatch, counterparty=None, caveats={"max_per_tx": "5"}) is None

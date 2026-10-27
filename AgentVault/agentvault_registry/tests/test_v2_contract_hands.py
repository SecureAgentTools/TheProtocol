"""D6-274 (§SUBAGENT-LIABILITY): on the contracts v2 routes a walletless HAND acts for its wallet-holding principal.

The legacy create and accept (routers/contracts.py) and the v2 release book and compare the PRINCIPAL a hand acts for
(services/spawn_anchor.resolve_spend_purse_agent) and ask the liability gate for it when a hand binds it. The other v2
routes compared and booked the hand itself: create, accept and engage made the walletless hand the client or the provider
of record and asked no liability gate for the principal; offer, submit, reject and cancel compared the caller with a
party as the hand. Now each resolves the caller's party of record through the same seam (byte-inert when the anchor is
off or no anchored hand acted); a contract booked under the hand before the change stays operable by that hand.

RED on the pre-change router: every test but the two controls at the end (the hand-booked contract's test fails there
only on the request parameter the routes now take: its behaviour, the hand still acting on it, is the old one, kept).
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

import pytest
from fastapi import HTTPException

ctr = importlib.import_module("agentvault_registry.routers.contracts_v2")
anchor = importlib.import_module("agentvault_registry.services.spawn_anchor")

CID = "ctr_hands"
PRINCIPAL = "did:theprotocol:sbx-alpha:principal-0000"
HAND = "did:theprotocol:sbx-alpha:hand-0000"
OTHER = "did:theprotocol:sbx-alpha:other-0000"
STRANGER = "did:theprotocol:sbx-alpha:stranger-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _agent(did):
    return types.SimpleNamespace(did=did, id=1)


class _Rec:
    """The calls each patched seam received."""
    def __init__(self):
        self.calls = {}

    def add(self, name, *a, **kw):
        self.calls.setdefault(name, []).append((a, kw))

    def __getitem__(self, name):
        return self.calls.get(name, [])


@pytest.fixture
def wired(monkeypatch):
    """Every seam the routes touch, patched; `hand_of` maps a hand's DID to its principal (the anchored redirect)."""
    rec = _Rec()
    state = {"hand_of": {}, "contract": None, "replica": None}

    async def _resolve(db, agent, request):
        p = state["hand_of"].get(agent.did)
        return (types.SimpleNamespace(did=p), p) if p else (agent, agent.did)

    async def _gate(db, agent_did, needed, **kw):
        rec.add("liability_gate", agent_did, needed, **kw)

    async def _mint(db, **kw):
        rec.add("mint", **kw)
        return {"id": CID, "status": "offered", "total_amount": kw.get("total_amount"), "client_did": kw["client_did"]}

    async def _must_load(db, cid):
        return dict(state["contract"])

    async def _replica_row(db, cid):
        return dict(state["replica"]) if state["replica"] else None

    async def _rb_gate(db, did, site=None):
        rec.add("bond_gate", did, site=site)

    async def _ep_gate(db, did, site=None):
        rec.add("enforcement_gate", did, site=site)

    async def _accept_as(db, cid, provider_did):
        rec.add("accept_as", cid, provider_did)
        return {"id": cid, "status": "agreed", "provider_did": provider_did}

    async def _submit_as(db, cid, seq, provider_did, deliverable):
        rec.add("submit_as", cid, seq, provider_did)
        return {"ok": True}

    async def _cancel_as(db, cid, actor_did):
        rec.add("cancel_as", cid, actor_did)
        return {"ok": True}

    async def _relay(db, rep, actor_did, action, *, cid, payload=None):
        rec.add("relay", actor_did, action)
        return {"ok": True, "relayed_to": rep["home_registry"]}

    async def _load_card(db, did):
        return {}, "provider", None, None   # a local provider: no foreign home

    async def _load_engagement(db, did):
        return {"terms": {}}, "provider"

    monkeypatch.setattr(anchor, "resolve_spend_purse_agent", _resolve)
    monkeypatch.setattr(ctr.liab, "check_liability_gate", _gate)
    monkeypatch.setattr(ctr.liab, "presence_from_request", lambda request: None)
    monkeypatch.setattr(ctr, "_require_enabled", lambda: None)
    monkeypatch.setattr(ctr, "mint_contract", _mint)
    monkeypatch.setattr(ctr, "_must_load", _must_load)
    monkeypatch.setattr(ctr, "_replica_row", _replica_row)
    monkeypatch.setattr(ctr._rb, "gate", _rb_gate)
    monkeypatch.setattr(ctr._ep, "gate", _ep_gate)
    monkeypatch.setattr(ctr, "accept_as", _accept_as)
    monkeypatch.setattr(ctr, "submit_as", _submit_as)
    monkeypatch.setattr(ctr, "cancel_as", _cancel_as)
    monkeypatch.setattr(ctr, "_relay_to_home", _relay)
    monkeypatch.setattr(ctr, "_load_card", _load_card)
    monkeypatch.setattr(ctr, "_load_engagement", _load_engagement)
    monkeypatch.setattr(ctr, "_engagement_to_draft",
                        lambda eng, did: {"title": "a service", "total_amount": "5", "contract_type": "service"})
    return rec, state


def _contract(client=PRINCIPAL, provider=OTHER, status="offered"):
    return {"id": CID, "client_did": client, "provider_did": provider, "status": status, "total_amount": "7",
            "currency": "SBXA", "counterparty_home_registry": None}


# ── create, offer, engage: the client of record ──────────────────────────────────────────────────────────────────

def test_a_hands_create_books_its_principal_and_gates_it(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    body = ctr.ContractCreateIn(title="t", contract_type="work_order", total_amount="7", provider_did=OTHER)
    _run(ctr.create_contract_v2(body, None, agent=_agent(HAND), db=None))
    (_, mint), = rec["mint"]
    assert mint["client_did"] == PRINCIPAL and mint["actor_did"] == HAND
    (args, kw), = rec["liability_gate"]
    assert args == (PRINCIPAL, "contracts.engage") and kw["acting_hand_did"] == HAND
    assert kw["counterparty_did"] == OTHER and Decimal(str(kw["amount"])) == Decimal("7")


def test_a_hand_offers_its_principals_draft(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    state["contract"] = _contract(status="draft")

    class _DB:
        async def execute(self, *a, **k):
            return types.SimpleNamespace(rowcount=0)
    with pytest.raises(HTTPException) as e:     # past the party check: the draft UPDATE matched nothing (409)
        _run(ctr.offer_contract(CID, None, agent=_agent(HAND), db=_DB()))
    assert e.value.status_code == 409


def test_a_hands_engage_books_its_principal_and_gates_it(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    _run(ctr.engage_agent(OTHER, ctr.EngageIn(), None, agent=_agent(HAND), db=None))
    (_, mint), = rec["mint"]
    assert mint["client_did"] == PRINCIPAL and mint["actor_did"] == HAND and mint["provider_did"] == OTHER
    (args, kw), = rec["liability_gate"]
    assert args == (PRINCIPAL, "contracts.engage") and kw["acting_hand_did"] == HAND and kw["counterparty_did"] == OTHER


def test_a_hand_cannot_engage_its_own_principal(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    with pytest.raises(HTTPException) as e:
        _run(ctr.engage_agent(PRINCIPAL, ctr.EngageIn(), None, agent=_agent(HAND), db=None))
    assert e.value.status_code == 400 and rec["mint"] == []


# ── accept: the provider of record ───────────────────────────────────────────────────────────────────────────────

def test_a_hands_accept_names_its_principal_and_gates_it(wired):
    rec, state = wired
    state["hand_of"][HAND] = OTHER                    # the hand works for the provider OTHER
    state["contract"] = _contract(client=PRINCIPAL, provider=None)
    _run(ctr.accept_contract_v2(CID, None, agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["accept_as"]] == [(CID, OTHER)]
    assert [a for a, _ in rec["bond_gate"]] == [(OTHER,)] and [a for a, _ in rec["enforcement_gate"]] == [(OTHER,)]
    (args, kw), = rec["liability_gate"]
    assert args == (OTHER, "contracts.engage") and kw["acting_hand_did"] == HAND and kw["counterparty_did"] == PRINCIPAL


def test_a_hand_cannot_accept_its_own_principals_contract(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    state["contract"] = _contract(client=PRINCIPAL, provider=None)
    with pytest.raises(HTTPException) as e:
        _run(ctr.accept_contract_v2(CID, None, agent=_agent(HAND), db=None))
    assert e.value.status_code == 400 and rec["accept_as"] == []


def test_a_hands_accept_of_a_replica_relays_its_principal(wired):
    rec, state = wired
    state["hand_of"][HAND] = OTHER
    state["replica"] = {"cid": CID, "home_registry": "sbx-beta", "client_did": PRINCIPAL, "provider_did": OTHER,
                        "status": "offered", "seq": 1, "currency": "SBXB", "total_amount": "9"}
    _run(ctr.accept_contract_v2(CID, None, agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["relay"]] == [(OTHER, "offer.accept")]
    (args, kw), = rec["liability_gate"]
    assert args[0] == OTHER and kw["amount"] == "9" and kw["currency"] == "SBXB" and kw["counterparty_did"] == PRINCIPAL


# ── submit, reject, cancel: the party of record (a contract booked under the hand stays the hand's) ─────────────

def test_a_hands_delivery_is_its_principals(wired):
    rec, state = wired
    state["hand_of"][HAND] = OTHER
    state["contract"] = _contract(client=PRINCIPAL, provider=OTHER, status="agreed")
    _run(ctr.submit_milestone(CID, 1, ctr.SubmitIn(deliverable={}), None, agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["submit_as"]] == [(CID, 1, OTHER)]


def test_a_contract_booked_under_the_hand_stays_the_hands(wired):
    rec, state = wired
    state["hand_of"][HAND] = OTHER
    state["contract"] = _contract(client=PRINCIPAL, provider=HAND, status="agreed")   # booked before D6-274
    _run(ctr.submit_milestone(CID, 1, ctr.SubmitIn(deliverable={}), None, agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["submit_as"]] == [(CID, 1, HAND)]


def test_a_hand_rejects_for_its_principal_and_a_stranger_cannot(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    state["contract"] = _contract(client=PRINCIPAL, provider=OTHER, status="in_progress")

    class _DB:
        async def execute(self, *a, **k):
            return types.SimpleNamespace(rowcount=0)
    with pytest.raises(HTTPException) as e:     # past the party check: no submitted milestone (409)
        _run(ctr.reject_milestone(CID, 1, ctr.RejectIn(), None, agent=_agent(HAND), db=_DB()))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        _run(ctr.reject_milestone(CID, 1, ctr.RejectIn(), None, agent=_agent(STRANGER), db=_DB()))
    assert e.value.status_code == 403


def test_a_hands_cancel_is_its_principals(wired):
    rec, state = wired
    state["hand_of"][HAND] = PRINCIPAL
    state["contract"] = _contract(client=PRINCIPAL, provider=OTHER, status="offered")
    _run(ctr.cancel_contract_v2(CID, None, agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["cancel_as"]] == [(CID, PRINCIPAL)]


def test_a_hands_cancel_of_a_replica_relays_its_principal(wired):
    rec, state = wired
    state["hand_of"][HAND] = OTHER
    state["replica"] = {"cid": CID, "home_registry": "sbx-beta", "client_did": PRINCIPAL, "provider_did": OTHER,
                        "status": "agreed", "seq": 2, "currency": "SBXB", "total_amount": "9"}
    _run(ctr.cancel_contract_v2(CID, None, agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["relay"]] == [(OTHER, "contract.cancel")]


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_an_agent_that_is_no_hand_creates_as_itself_with_no_gate(wired):
    rec, state = wired
    body = ctr.ContractCreateIn(title="t", contract_type="work_order", total_amount="7", provider_did=OTHER)
    _run(ctr.create_contract_v2(body, None, agent=_agent(PRINCIPAL), db=None))
    (_, mint), = rec["mint"]
    assert mint["client_did"] == PRINCIPAL and rec["liability_gate"] == []


def test_control_an_agent_that_is_no_hand_accepts_as_itself_with_no_gate(wired):
    rec, state = wired
    state["contract"] = _contract(client=PRINCIPAL, provider=None)
    _run(ctr.accept_contract_v2(CID, None, agent=_agent(OTHER), db=None))
    assert [a for a, _ in rec["accept_as"]] == [(CID, OTHER)] and rec["liability_gate"] == []

"""§TWOAGENT G2 (2026-09-23) — a provider on ANOTHER frame can accept, deliver and cancel a contract, and nothing else.

Measured in the two-agent trial (entry 28): an offer EU → ASIA replicated to ASIA, but the provider could never accept
it. Its registry held only a read-only replica (`/contracts/v2/{cid}/accept` answered 404 there), nothing SENT the
relayed command that `/federation/contract-command` receives, and that receiver in enforce only AUDITED
(`xframe_offer_accept`, applied:true, no transition, no escrow). V0428 kept the door shut with that sentence.

Now: the provider's own registry authenticates and gates its agent and couriers the command; the home applies it
through the local routes' own cores (accept-with-escrow, submit, cancel) — only for the provider named on the contract,
only when the relaying registry is that provider's own, never a client act (`milestone.accept` releases money and was
relayable). The door opens only in enforce and only for a provider whose registry answers the courier capability.
And R-16: a direct create to a DID with no card and no agent here is refused instead of minting an unreachable offer.

RED on the pre-change tree: every test except the three controls at the end.
"""
from __future__ import annotations

import asyncio
import importlib
import types

import pytest
from fastapi import HTTPException

cf = importlib.import_module("agentvault_registry.routers.contract_federation")
ctr = importlib.import_module("agentvault_registry.routers.contracts_v2")
xf = importlib.import_module("agentvault_registry.services.contract_xframe")
cset = importlib.import_module("agentvault_registry.services.contract_settlement")

CID = "ctr_g2test"
CLIENT = "did:theprotocol:eu.theprotocol.cloud:client-0000"
PROVIDER = "did:theprotocol:asia.theprotocol.cloud:provider-0000"
ASIA_SVID = "spiffe://asia.theprotocol.cloud/service/asia-registry"
EVIL_SVID = "spiffe://evil.example/service/evil-registry"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Res:
    def __init__(self, row=None, rows=None, scalar=None, rowcount=1):
        self._row, self._rows, self._scalar, self.rowcount = row, rows, scalar, rowcount

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows or ([] if self._row is None else [self._row])

    def scalar(self):
        return self._scalar


class _DB:
    """Answers by SQL fragment, first match wins; records every statement."""
    def __init__(self, answers):
        self.answers = answers
        self.sql = []
        self.commits = 0

    async def execute(self, clause, params=None):
        q = str(clause)
        self.sql.append(q)
        for frag, res in self.answers:
            if frag in q:
                return res() if callable(res) else res
        return _Res()

    async def commit(self):
        self.commits += 1


def _contract_row(**kw):
    d = {"id": CID, "status": "offered", "client_did": CLIENT, "provider_did": PROVIDER,
         "counterparty_home_registry": "asia"}
    d.update(kw)
    return d


def _wire_receiver(monkeypatch, *, mode="enforce", row=None, already=None):
    audits = []

    async def _resolve(db, v):
        v = (v or "").lower()
        return "asia" if ("asia" in v) else None

    async def _audit(db, cid, seq, ev, actor, payload):
        audits.append((ev, actor, payload))

    async def _seq(db, cid):
        return 7
    monkeypatch.setattr(xf, "enabled", lambda: True)
    monkeypatch.setattr(xf, "mode", lambda: mode)
    monkeypatch.setattr(xf, "resolve_peer_name", _resolve)
    monkeypatch.setattr(cset, "audit", _audit)
    monkeypatch.setattr(cset, "next_seq", _seq)
    db = _DB([
        ("payload->>'relay_key'", _Res(row=already)),
        ("FROM contracts WHERE id", _Res(row=row or _contract_row())),
    ])
    return db, audits


def _cmd(action="offer.accept", actor=PROVIDER, payload=None):
    return cf.ContractCommand(cid=CID, action=action, actor_did=actor, seq=3, payload=payload,
                              idempotency_key=f"xfr-{CID}-{action}")


def _applied_calls(monkeypatch):
    calls = []

    async def _accept(db, cid, did):
        calls.append(("accept", cid, did))
        return {"id": cid, "status": "agreed", "escrow_ref": f"ctrref:{cid}"}

    async def _submit(db, cid, seq, did, deliverable):
        calls.append(("submit", cid, seq, did, deliverable))
        return {"ok": True, "contract_id": cid, "seq": seq, "status": "submitted"}

    async def _gate(db, did, *, site, **k):
        calls.append(("gate", site, did))
        return {"decision": "allow"}
    monkeypatch.setattr(ctr, "accept_as", _accept, raising=False)
    monkeypatch.setattr(ctr, "submit_as", _submit, raising=False)
    import agentvault_registry.services.reputation_bond as rb
    import agentvault_registry.services.enforcement_propagation as ep
    monkeypatch.setattr(rb, "gate", _gate)
    monkeypatch.setattr(ep, "gate", _gate)
    return calls


# ── the receiver (the contract's home) ─────────────────────────────────────────────────────────────────────────

def test_a_relay_from_a_registry_that_is_not_the_providers_is_refused(monkeypatch):
    db, audits = _wire_receiver(monkeypatch)
    _applied_calls(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _run(cf.contract_command(body=_cmd(), peer_spiffe=EVIL_SVID, db=db))
    assert e.value.status_code == 403 and "own registry" in e.value.detail
    assert audits == []


def test_the_client_cannot_be_relayed_it_acts_at_home(monkeypatch):
    db, audits = _wire_receiver(monkeypatch)
    _applied_calls(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _run(cf.contract_command(body=_cmd(actor=CLIENT), peer_spiffe=ASIA_SVID, db=db))
    assert e.value.status_code == 403 and "provider" in e.value.detail


def test_a_client_act_is_not_relayable(monkeypatch):
    db, _ = _wire_receiver(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _run(cf.contract_command(body=_cmd(action="milestone.accept"), peer_spiffe=ASIA_SVID, db=db))
    assert e.value.status_code == 400


def test_enforce_APPLIES_the_accept_with_the_gates_and_audits_it(monkeypatch):
    db, audits = _wire_receiver(monkeypatch)
    calls = _applied_calls(monkeypatch)
    out = _run(cf.contract_command(body=_cmd(), peer_spiffe=ASIA_SVID, db=db))
    assert ("accept", CID, PROVIDER) in calls
    assert ("gate", "contract_accept", PROVIDER) in calls, "the bond/enforcement gates run at the home too"
    assert out["applied"] is True and out["status"] == "agreed" and out["escrowed"] is True
    assert [a[0] for a in audits] == ["xframe_offer_accept"] and audits[0][2]["relay_key"] == f"xfr-{CID}-offer.accept"


def test_enforce_applies_a_delivery_with_its_milestone(monkeypatch):
    db, _ = _wire_receiver(monkeypatch, row=_contract_row(status="agreed"))
    calls = _applied_calls(monkeypatch)
    out = _run(cf.contract_command(body=_cmd(action="milestone.submit", payload={"seq": 1, "deliverable": {"url": "x"}}),
                                   peer_spiffe=ASIA_SVID, db=db))
    assert ("submit", CID, 1, PROVIDER, {"url": "x"}) in calls
    assert out["applied"] is True and out["seq"] == 1 and "event_seq" in out


def test_the_courier_capability_answers(monkeypatch):
    monkeypatch.setattr(xf, "enabled", lambda: True)
    out = _run(cf.contract_courier(peer_spiffe=ASIA_SVID))
    assert out["relay"] is True and set(out["actions"]) == {"offer.accept", "milestone.submit", "contract.cancel"}


# ── the courier (the provider's own registry) ─────────────────────────────────────────────────────────────────

REP = {"cid": CID, "home_registry": "eu", "client_did": CLIENT, "provider_did": PROVIDER, "status": "offered", "seq": 3}


def test_the_courier_relays_the_providers_own_act_to_the_home(monkeypatch):
    sent, refreshed = [], []
    ep = importlib.import_module("agentvault_registry.services.exchange_passport")

    async def _peer(db, name, method, path, json_body=None):
        sent.append((name, method, path, json_body))
        return 200, {"ok": True, "applied": True, "status": "agreed"}

    async def _refresh(db, home, cid):
        refreshed.append((home, cid))
    monkeypatch.setattr(ep, "peer_request", _peer)
    monkeypatch.setattr(ctr, "_refresh_replica", _refresh, raising=False)
    monkeypatch.setattr(xf, "enabled", lambda: True)
    out = _run(ctr._relay_to_home(None, dict(REP), PROVIDER, "offer.accept", cid=CID))
    name, method, path, body = sent[0]
    assert (name, method, path) == ("eu", "POST", "/api/v1/federation/contract-command")
    assert body["actor_did"] == PROVIDER and body["action"] == "offer.accept" and body["idempotency_key"] == f"xfr-{CID}-offer.accept"
    assert out["relayed_to"] == "eu" and out["status"] == "agreed" and refreshed == [("eu", CID)]


def test_the_courier_refuses_anyone_but_the_named_provider(monkeypatch):
    monkeypatch.setattr(xf, "enabled", lambda: True)
    with pytest.raises(HTTPException) as e:
        _run(ctr._relay_to_home(None, dict(REP), CLIENT, "offer.accept", cid=CID))
    assert e.value.status_code == 403


def test_the_homes_refusal_reaches_the_provider_unchanged(monkeypatch):
    ep = importlib.import_module("agentvault_registry.services.exchange_passport")

    async def _peer(db, name, method, path, json_body=None):
        return 402, {"detail": "Escrow failed (client has insufficient balance?): x"}
    monkeypatch.setattr(ep, "peer_request", _peer)
    monkeypatch.setattr(xf, "enabled", lambda: True)
    with pytest.raises(HTTPException) as e:
        _run(ctr._relay_to_home(None, dict(REP), PROVIDER, "offer.accept", cid=CID))
    assert e.value.status_code == 402 and "Escrow failed" in e.value.detail


# ── the door (the client's frame, where the offer would mint) ───────────────────────────────────────────────────

def _door(monkeypatch, *, mode, carries):
    async def _resolve(db, v):
        return "asia"

    async def _carries(db, peer):
        return carries
    monkeypatch.setattr(xf, "enabled", lambda: True)
    monkeypatch.setattr(xf, "mode", lambda: mode)
    monkeypatch.setattr(xf, "resolve_peer_name", _resolve)
    monkeypatch.setattr(ctr, "_peer_carries_contract_commands", _carries, raising=False)
    return _run(ctr._foreign_contract_home(None, "spiffe://asia.theprotocol.cloud/registry/asia", "ASIA"))


def test_the_door_opens_in_enforce_for_a_provider_whose_registry_carries_it(monkeypatch):
    assert _door(monkeypatch, mode="enforce", carries=True) == ("asia", None)


def test_the_door_stays_shut_for_a_registry_without_the_courier(monkeypatch):
    home, reason = _door(monkeypatch, mode="enforce", carries=False)
    assert home is None and "courier" in reason


def test_the_door_stays_shut_in_shadow_and_says_so(monkeypatch):
    home, reason = _door(monkeypatch, mode="shadow", carries=True)
    assert home is None and "shadow" in reason and "would not be applied" in reason


# ── R-16 and the replica notice ────────────────────────────────────────────────────────────────────────────────

def test_a_direct_create_to_an_unknown_did_is_refused_not_minted(monkeypatch):
    minted = []

    async def _no_card(db, did):
        raise HTTPException(404, "Agent card not found")

    async def _mint(db, **kw):
        minted.append(kw)
        return {"id": "ctr_x", "status": "offered", "total_amount": "1"}
    monkeypatch.setattr(ctr, "_require_enabled", lambda: None)
    monkeypatch.setattr(ctr, "_load_card", _no_card)
    monkeypatch.setattr(ctr, "mint_contract", _mint)
    db = _DB([("FROM agents WHERE did", _Res(row=None))])
    body = ctr.ContractCreateIn(title="t", contract_type="work_order", total_amount="1",
                                provider_did="did:theprotocol:nowhere:0000")
    with pytest.raises(HTTPException) as e:
        _run(ctr.create_contract_v2(body, None, agent=types.SimpleNamespace(did=CLIENT, id=1), db=db))
    assert e.value.status_code == 404 and "No agent with this DID" in e.value.detail and minted == []


def test_a_new_replica_tells_the_providers_owner(monkeypatch):
    told = []
    monkeypatch.setattr(cset, "webhook", lambda ev, c, extra=None: told.append((ev, c.get("provider_did"), (extra or {}).get("replica"))))
    db = _DB([("SELECT status FROM contract_replicas", _Res(scalar=None)), ("INSERT INTO contract_replicas", _Res(rowcount=1))])
    env = {"payload": {"cid": CID, "home_registry": "eu", "client_did": CLIENT, "provider_did": PROVIDER,
                       "status": "offered", "seq": 1}, "digest": "d", "signature": {"value": "s"}}
    assert _run(xf.upsert_replica(db, env, verified=True)) is True
    assert told == [("contract.offered", PROVIDER, True)]


# ── on the way: the signed digest is the counterparty's business only ───────────────────────────────────────────

def _digest(monkeypatch, caller_svid):
    async def _resolve(db, v):
        v = (v or "").lower()
        return "asia" if "asia" in v else ("evil" if "evil" in v else None)

    async def _sign(db, snap):
        return {"digest": "d", "payload": snap, "signature": {"value": "s"}}
    monkeypatch.setattr(xf, "enabled", lambda: True)
    monkeypatch.setattr(xf, "resolve_peer_name", _resolve)
    monkeypatch.setattr(xf, "sign_snapshot", _sign)
    monkeypatch.setattr(xf, "self_federation_name", lambda: "eu")
    db = _DB([("COALESCE(MAX(seq)", _Res(scalar=4)), ("FROM contracts WHERE id", _Res(row=_contract_row()))])
    return _run(cf.contract_digest(cid=CID, peer_spiffe=caller_svid, db=db))


def test_a_third_frame_cannot_read_another_pairs_contract_digest(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _digest(monkeypatch, EVIL_SVID)
    assert e.value.status_code == 404


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_non_party_is_refused(monkeypatch):
    db, _ = _wire_receiver(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _run(cf.contract_command(body=_cmd(actor="did:theprotocol:asia.theprotocol.cloud:stranger"),
                                 peer_spiffe=ASIA_SVID, db=db))
    assert e.value.status_code == 403


def test_control_an_unchanged_replica_tells_nobody(monkeypatch):
    told = []
    monkeypatch.setattr(cset, "webhook", lambda *a, **k: told.append(a))
    db = _DB([("SELECT status FROM contract_replicas", _Res(scalar="offered")), ("INSERT INTO contract_replicas", _Res(rowcount=0))])
    env = {"payload": {"cid": CID, "status": "offered", "seq": 1}, "digest": "d", "signature": {"value": "s"}}
    _run(xf.upsert_replica(db, env, verified=True))
    assert told == []


def test_control_a_local_agent_without_a_card_still_mints(monkeypatch):
    minted = []

    async def _no_card(db, did):
        raise HTTPException(404, "Agent card not found")

    async def _mint(db, **kw):
        minted.append(kw)
        return {"id": "ctr_x", "status": "offered", "total_amount": "1"}
    monkeypatch.setattr(ctr, "_require_enabled", lambda: None)
    monkeypatch.setattr(ctr, "_load_card", _no_card)
    monkeypatch.setattr(ctr, "mint_contract", _mint)
    db = _DB([("FROM agents WHERE did", _Res(row=(1,)))])
    body = ctr.ContractCreateIn(title="t", contract_type="work_order", total_amount="1", provider_did="did:theprotocol:local:1")
    _run(ctr.create_contract_v2(body, None, agent=types.SimpleNamespace(did=CLIENT, id=1), db=db))
    assert len(minted) == 1


def test_control_the_counterpartys_registry_reads_the_digest(monkeypatch):
    out = _digest(monkeypatch, ASIA_SVID)
    assert out["cid"] == CID and out["seq"] == 4 and out["envelope"]["digest"] == "d"

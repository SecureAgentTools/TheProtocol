"""D6-274 (V0639): the v2 contract routes that ask no permission resolve the hand's own X-Capability-Token.

V0638 books a hand's principal. create, accept and engage go through require_agent_permission, which resolves the
presented token onto request.state.ironkey_capability, the state spawn_anchor reads. offer, submit, release, reject,
cancel and the detail read ask no permission (get_current_agent, get_current_actor_for_read), so nothing resolved the
token there and the hand was itself. Measured on sbx-alpha 2026-10-24 19:45Z (scratchpad/deps/probe_d6274_hand_v2.py):
the hand's create answered 200 and booked the principal, then its cancel and its read answered 403 "Not a party to this
contract"; and the release's hand path (§SUBAGENT-LIABILITY P1/P2, with its liability gate) had never run.
test_v2_contract_hands.py could not see it: it patches resolve_spend_purse_agent by DID, above the state the live
routes never set.

Here nothing above the token table is patched: each request carries the X-Capability-Token header and an empty state,
and the real _party_of_record, spawn_anchor.resolve_spend_purse_agent and the route bodies run. Stand-ins: the modes,
resolve_capability (the token table), the wallet walk, the agent row, and the seams after the party check.
RED on V0638's router: the six hand tests and the structural one (the read on its 403: V0638's detail route
took no request at all). The controls hold on both.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import types

import pytest
from fastapi import HTTPException

ctr = importlib.import_module("agentvault_registry.routers.contracts_v2")
anchor = importlib.import_module("agentvault_registry.services.spawn_anchor")
authz = importlib.import_module("agentvault_registry.agent_authz")
deleg = importlib.import_module("agentvault_registry.agent_delegation")
crud_agent = importlib.import_module("agentvault_registry.crud.agent")
liability = importlib.import_module("agentvault_registry.services.liability")

CID = "ctr_handtoken"
PRINCIPAL = "did:theprotocol:sbx-alpha:principal-0001"
PROVIDER = "did:theprotocol:sbx-alpha:provider-0001"
HAND = "did:theprotocol:sbx-alpha:hand-0001"
STRANGER = "did:theprotocol:sbx-alpha:stranger-0001"
TOKEN = "att_" + "h" * 40


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _agent(did):
    return types.SimpleNamespace(did=did, id=1)


def _request(token=TOKEN, path="/api/v1/contracts/v2/x"):
    """What a live route receives from FastAPI: the headers and an EMPTY state (no permission dependency ran)."""
    headers = {"X-Capability-Token": token} if token else {}
    return types.SimpleNamespace(headers=headers, state=types.SimpleNamespace(), url=types.SimpleNamespace(path=path))


class _Rec:
    def __init__(self):
        self.calls = {}

    def add(self, name, *a, **kw):
        self.calls.setdefault(name, []).append((a, kw))

    def __getitem__(self, name):
        return self.calls.get(name, [])


class _Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    """A session whose every statement matches nothing (an UPDATE's rowcount 0, a SELECT's empty result)."""
    async def execute(self, *a, **k):
        r = _Rows()
        r.rowcount = 0
        return r


@pytest.fixture
def chain(monkeypatch):
    rec = _Rec()
    state = {"rbac": "enforce", "deleg": "enforce", "perms": ["contracts.engage"], "issuer": PRINCIPAL,
             "resolves": True, "contract": None}

    async def _resolve_capability(db, token_plain, holder_did):
        rec.add("resolve_capability", token_plain, holder_did)
        if not state["resolves"] or token_plain != TOKEN or holder_did != HAND:
            return None, "unknown_token"
        return {"id": 77, "permissions": list(state["perms"]), "caveats": {anchor.ANCHOR_CAVEAT: True, "birth": True},
                "budget_remaining": None, "currency": None, "issuer_did": state["issuer"]}, None

    async def _walk(db, start_did):
        return start_did            # the issuer holds a wallet: one hop

    async def _get_agent_by_did(db, did):
        return _agent(did)

    async def _record_hand_action(db, **kw):
        rec.add("hand_action", **kw)

    async def _gate(db, agent_did, needed, **kw):
        rec.add("liability_gate", agent_did, needed, **kw)
        raise HTTPException(418, detail="stop after the liability gate")   # the escrow legs are not under test here

    async def _must_load(db, cid):
        return dict(state["contract"])

    async def _replica_row(db, cid):
        return None

    async def _cancel_as(db, cid, actor_did):
        rec.add("cancel_as", cid, actor_did)
        return {"ok": True}

    async def _submit_as(db, cid, seq, provider_did, deliverable):
        rec.add("submit_as", cid, seq, provider_did)
        return {"ok": True}

    async def _load_milestone(db, cid, seq):
        return {"seq": seq, "amount": "7", "status": "submitted"}

    monkeypatch.setattr(authz, "agent_rbac_mode", lambda: state["rbac"])
    monkeypatch.setattr(authz, "agent_delegation_mode", lambda: state["deleg"])
    monkeypatch.setattr(deleg, "resolve_capability", _resolve_capability)
    monkeypatch.setattr(anchor, "anchor_enabled", lambda: True)
    monkeypatch.setattr(anchor, "_walk_to_wallet_holder", _walk)
    monkeypatch.setattr(crud_agent, "get_agent_by_did", _get_agent_by_did)
    monkeypatch.setattr(liability, "record_hand_action", _record_hand_action)
    monkeypatch.setattr(ctr.liab, "check_liability_gate", _gate)
    monkeypatch.setattr(ctr.liab, "presence_from_request", lambda request: None)
    monkeypatch.setattr(ctr.cs, "load_milestone", _load_milestone)
    monkeypatch.setattr(ctr, "_require_enabled", lambda: None)
    monkeypatch.setattr(ctr, "_must_load", _must_load)
    monkeypatch.setattr(ctr, "_replica_row", _replica_row)
    monkeypatch.setattr(ctr, "cancel_as", _cancel_as)
    monkeypatch.setattr(ctr, "submit_as", _submit_as)
    return rec, state


def _read(actor, req):
    """The detail route as FastAPI calls it; V0638's took no request (the reason a hand could not read), so it is
    passed only where the route has the parameter: a hand's read then fails there on the 403 itself."""
    kw = {"actor": actor, "db": _DB()}
    if "request" in inspect.signature(ctr.get_contract_v2).parameters:
        kw["request"] = req
    return _run(ctr.get_contract_v2(CID, **kw))


def _contract(client=PRINCIPAL, provider=PROVIDER, status="offered"):
    return {"id": CID, "client_did": client, "provider_did": provider, "status": status, "total_amount": "7",
            "currency": "SBXA", "counterparty_home_registry": None}


# ── the hand, through the routes, with nothing but its token ─────────────────────────────────────────────────────

def test_the_party_of_record_resolves_the_hands_own_token(chain):
    rec, state = chain
    req = _request()
    assert _run(ctr._party_of_record(None, _agent(HAND), req)) == PRINCIPAL
    assert req.state.ironkey_capability["id"] == 77
    assert [a for a, _ in rec["resolve_capability"]] == [(TOKEN, HAND)]


def test_a_hand_cancels_its_principals_offer(chain):
    rec, state = chain
    state["contract"] = _contract(status="offered")
    _run(ctr.cancel_contract_v2(CID, _request(), agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["cancel_as"]] == [(CID, PRINCIPAL)]


def test_a_hand_publishes_its_principals_draft(chain):
    rec, state = chain
    state["contract"] = _contract(status="draft")
    with pytest.raises(HTTPException) as e:      # past the party check: the draft UPDATE matched nothing (409)
        _run(ctr.offer_contract(CID, _request(), agent=_agent(HAND), db=_DB()))
    assert e.value.status_code == 409


def test_a_hand_submits_for_its_principal_provider(chain):
    rec, state = chain
    state["issuer"] = PROVIDER                    # the hand works for the provider
    state["contract"] = _contract(status="agreed")
    _run(ctr.submit_milestone(CID, 1, ctr.SubmitIn(deliverable={}), _request(), agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["submit_as"]] == [(CID, 1, PROVIDER)]


def test_a_hands_release_asks_the_liability_gate_for_its_principal(chain):
    rec, state = chain
    state["contract"] = _contract(status="in_progress")
    with pytest.raises(HTTPException) as e:
        _run(ctr.release_milestone(CID, 1, ctr.ReleaseIn(), _request(), agent=_agent(HAND), db=_DB()))
    assert e.value.status_code == 418              # stopped by the stand-in gate, past the client check
    (args, kw), = rec["liability_gate"]
    assert args == (PRINCIPAL, "contracts.engage") and kw.get("acting_hand_did") == HAND


def test_a_hand_reads_its_principals_contract(chain):
    rec, state = chain
    state["contract"] = _contract(status="agreed")
    out = _read({"kind": "agent", "agent_did": HAND}, _request())
    assert out["id"] == CID and out["client_did"] == PRINCIPAL and out["milestones"] == []


def test_every_v2_route_reaches_the_purse_through_the_party_of_record():
    """No v2 route asks spawn_anchor itself: the one seam that resolves the token first is _party_of_record."""
    src = inspect.getsource(ctr)
    tree = ast.parse(src)
    callers = sorted({fn.name for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                      for node in ast.walk(fn) if isinstance(node, ast.Call)
                      and getattr(node.func, "id", getattr(node.func, "attr", None)) == "resolve_spend_purse_agent"})
    assert callers == ["_party_of_record"], callers
    body = inspect.getsource(ctr._party_of_record)
    assert body.index("_hand_capability(") < body.index("resolve_spend_purse_agent(")


# ── controls: the same on V0638 and here ─────────────────────────────────────────────────────────────────────────

def test_control_a_token_without_contracts_engage_leaves_the_hand_itself(chain):
    rec, state = chain
    state["perms"] = ["exchange.trade"]
    state["contract"] = _contract(status="offered")
    _run(ctr.cancel_contract_v2(CID, _request(), agent=_agent(HAND), db=None))
    assert [a for a, _ in rec["cancel_as"]] == [(CID, HAND)]       # cancel_as then answers 403: no party


def test_control_a_token_that_does_not_resolve_leaves_the_hand_itself(chain):
    rec, state = chain
    state["resolves"] = False
    assert _run(ctr._party_of_record(None, _agent(HAND), _request())) == HAND


@pytest.mark.parametrize("rbac,dmode", [("off", "enforce"), ("enforce", "off")])
def test_control_no_token_is_resolved_where_the_permission_dependency_resolves_none(chain, rbac, dmode):
    rec, state = chain
    state["rbac"], state["deleg"] = rbac, dmode
    assert _run(ctr._party_of_record(None, _agent(HAND), _request())) == HAND
    assert rec["resolve_capability"] == []


def test_control_an_agent_without_a_token_is_itself(chain):
    rec, state = chain
    assert _run(ctr._party_of_record(None, _agent(PRINCIPAL), _request(token=None))) == PRINCIPAL
    assert rec["resolve_capability"] == []


def test_control_a_capability_the_permission_dependency_resolved_is_kept(chain):
    rec, state = chain
    req = _request()
    req.state.ironkey_capability = {"id": 5, "permissions": ["contracts.engage"], "issuer_did": PRINCIPAL,
                                    "caveats": {anchor.ANCHOR_CAVEAT: True}}
    assert _run(ctr._party_of_record(None, _agent(HAND), req)) == PRINCIPAL
    assert rec["resolve_capability"] == [] and req.state.ironkey_capability["id"] == 5


def test_control_a_stranger_cannot_read_and_a_party_can(chain):
    rec, state = chain
    state["contract"] = _contract(status="agreed")
    with pytest.raises(HTTPException) as e:
        _read({"kind": "agent", "agent_did": STRANGER}, _request(token=None))
    assert e.value.status_code == 403
    out = _read({"kind": "agent", "agent_did": PROVIDER}, _request(token=None))
    assert out["provider_did"] == PROVIDER

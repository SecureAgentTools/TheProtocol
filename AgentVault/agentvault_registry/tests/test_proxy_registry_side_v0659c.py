"""V0659 (c): the registry's side of TheProtocol Proxy's money path and A2A task.

- An agent reads its own roles, permissions and spend cap (GET /agents/me/authz), registered before /agents/{did}/authz
  so "me" is not read as a DID; and the mandate that underwrites it (GET /liability/mandates/{mid}/for-agent), answered
  only to that agent: another agent's mandate and a missing one answer the same 404.
- A caller that names its mandate (X-Liability-Mandate on /a2a-payment/authorize) is held to it for the call, as if
  liability were enforced, whatever the registry's mode: the mandate must underwrite it and cover a2a.pay, and its own
  max_per_tx and currency clamp the amount. Without the header nothing changes (the registry's mode decides).
- /a2a-payment/buy keeps its answer under the caller's Idempotency-Key (a repeat ran the agent's task, and for a paid
  agent authorized and paid, again); an answer that proves nothing moved gives the key back; free_only refuses an agent
  that charges before anything is authorized.
Red on 13d2011ac: none of the routes, parameters or clamps exist.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from agentvault_registry.services import liability as liab
from agentvault_registry.services.idempotency import cache
from tests.test_idempotency_per_caller import FakeRedis

DID = "did:theprotocol:proxy-payer-0001"
MID = "lm_" + "ab" * 20


def _run(coro):
    return asyncio.run(coro)


# ── the agent's own reads ────────────────────────────────────────────────────────────────────────────────────────────

def test_an_agent_reads_its_own_authz_and_the_route_comes_before_the_owners(monkeypatch):
    from agentvault_registry.routers import agent_authz_api as api

    async def roles(db, did):
        return ["attestor", "client"]

    async def perms(db, did):
        return {"a2a.pay", "reputation.signal"}

    async def spend(db, did):
        return {"max_per_tx": "25", "max_per_day": "200"}
    monkeypatch.setattr(api, "resolve_agent_roles", roles)
    monkeypatch.setattr(api, "resolve_agent_permissions", perms)
    monkeypatch.setattr(api, "_spend_policy", spend)
    out = _run(api.get_my_authz(current_agent=SimpleNamespace(did=DID), db=None))
    assert out["agent_did"] == DID and out["roles"] == ["attestor", "client"]
    assert out["effective_permissions"] == ["a2a.pay", "reputation.signal"]
    assert out["spend_policy"] == {"max_per_tx": "25", "max_per_day": "200"}
    paths = [r.path for r in api.router.routes]
    assert paths.index("/agents/me/authz") < paths.index("/agents/{did}/authz")


class _MandateDB:
    def __init__(self, mandate):
        self.mandate, self.asked = mandate, []

    async def execute(self, stmt, params=None):
        compiled = stmt.compile()
        self.asked.append(dict(compiled.params))
        p = compiled.params
        hit = self.mandate if (self.mandate is not None and self.mandate.id in p.values()
                               and self.mandate.agent_did in p.values()) else None
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: hit))

    async def get(self, model, pk):
        return SimpleNamespace(id=pk)


def _mandate(**kw):
    from datetime import datetime, timedelta, timezone
    return SimpleNamespace(**{"id": MID, "agent_did": DID, "developer_id": 6, "tier": "T1", "status": "signed",
                              "scope": ["a2a.pay"], "limits": {"max_per_tx": "50", "currency": "ECU"},
                              "expires_at": datetime.now(timezone.utc) + timedelta(days=30), **kw})


def test_the_mandate_is_read_by_its_own_agent_only(monkeypatch):
    from agentvault_registry.routers import liability as router
    monkeypatch.setattr(router, "liability_mode", lambda: "shadow")

    async def resolved(db, m, dev):
        return {"valid": True, "effective_scope": ["a2a.pay"], "reasons": [], "authority_now": ["admin"]}
    monkeypatch.setattr(router.liab, "resolve_mandate", resolved)
    db = _MandateDB(_mandate())
    out = _run(router.get_mandate_for_agent(MID, agent=SimpleNamespace(did=DID), db=db))
    assert out["valid"] is True and out["effective_scope"] == ["a2a.pay"] and out["limits"]["max_per_tx"] == "50"
    assert "developer_id" not in out and "authority_now" not in out, "nothing about the human behind it"
    for agent in ("did:theprotocol:someone-else", DID):
        db2 = _MandateDB(_mandate() if agent != DID else None)
        with pytest.raises(HTTPException) as e:
            _run(router.get_mandate_for_agent(MID, agent=SimpleNamespace(did=agent), db=db2))
        assert e.value.status_code == 404 and e.value.detail == f"No mandate {MID} underwrites this agent"
    monkeypatch.setattr(router, "liability_mode", lambda: "off")
    with pytest.raises(HTTPException) as e:
        _run(router.get_mandate_for_agent(MID, agent=SimpleNamespace(did=DID), db=db))
    assert e.value.status_code == 404 and "not enabled" in e.value.detail


# ── the named mandate on the gate ────────────────────────────────────────────────────────────────────────────────────

class _GateDB:
    """Answers the gate's mandate read; records what it was asked."""

    def __init__(self, row):
        self.row, self.sql, self.commits = row, [], 0

    async def execute(self, stmt, params=None):
        self.sql.append((" ".join(str(stmt).split()), dict(params or {})))
        row = self.row
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))

    async def get(self, model, pk):
        return SimpleNamespace(id=pk)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def gate(monkeypatch):
    from agentvault_registry.config import settings
    from agentvault_registry.services import org_policy
    evidence = []

    async def org(db, did):
        return {}

    async def resolved(db, m, dev):
        return {"valid": m.status == "signed", "effective_scope": list(m.scope) if m.status == "signed" else [],
                "reasons": [] if m.status == "signed" else ["mandate_revoked"], "authority_now": []}

    async def ev(db, mid, event_type, payload, **kw):
        evidence.append((event_type, payload))
    monkeypatch.setattr(settings, "LIABILITY_MODE", "off", raising=False)
    monkeypatch.setattr(org_policy, "get_org_settings", org)
    monkeypatch.setattr(liab, "resolve_mandate", resolved)
    monkeypatch.setattr(liab, "append_evidence", ev)
    monkeypatch.setattr(liab, "presence_threshold", lambda: 0.0)
    return evidence


def _row(**kw):
    return {"id": MID, "developer_id": 6, "agent_did": DID, "tier": "T1", "scope": ["a2a.pay"],
            "limits": {"max_per_tx": "50", "currency": "ECU"}, "status": "signed", "expires_at": None, **kw}


def _gate(db, **kw):
    return _run(liab.check_liability_gate(db, DID, "a2a.pay", action_ref="a2a-pay:tpx-1", **kw))


def test_without_a_named_mandate_a_registry_with_liability_off_asks_nothing(gate):
    db = _GateDB(None)
    assert _gate(db, amount="12.5", currency="ECU") is None and db.sql == []


def test_a_named_mandate_is_enforced_with_liability_off_and_passes_with_its_evidence(gate):
    db = _GateDB(_row())
    _gate(db, mandate_id=MID, amount="12.5", currency="ECU")
    sql, params = db.sql[0]
    assert "WHERE id = CAST(:m AS VARCHAR) AND agent_did = CAST(:a AS VARCHAR)" in sql
    assert params == {"m": MID, "a": DID}
    assert gate and gate[-1][0] == "gate_pass" and gate[-1][1]["needed"] == "a2a.pay"


@pytest.mark.parametrize("row,amount,currency,why", [
    (None, "1", "ECU", "no_mandate"),
    (_row(status="revoked"), "1", "ECU", "mandate_revoked"),
    (_row(scope=["contracts.engage"]), "1", "ECU", "scope_missing:a2a.pay"),
    (_row(), "50.01", "ECU", "over_mandate_max_per_tx:50"),
    (_row(), "10", "ACU", "mandate_currency:ECU"),
])
def test_a_named_mandate_refuses_what_it_does_not_cover(gate, row, amount, currency, why):
    with pytest.raises(HTTPException) as e:
        _gate(_GateDB(row), mandate_id=MID, amount=amount, currency=currency)
    assert e.value.status_code == 403 and why in e.value.detail and "a2a.pay" in e.value.detail


def test_the_authorize_route_holds_a_caller_to_the_mandate_it_names_before_any_replay(monkeypatch):
    from agentvault_registry.routers import a2a_payment as ap
    called = {}

    async def no_gate(*a, **k):
        return None

    async def refuse(db, did, needed, **kw):
        called.update(kw, did=did, needed=needed)
        raise HTTPException(403, detail="Liability mandate required for 'a2a.pay' (over_mandate_max_per_tx:50)")

    async def lookup(*a, **k):
        raise AssertionError("the replay is not reached: the mandate refuses first")
    monkeypatch.setattr(ap._rb, "gate", no_gate)
    monkeypatch.setattr(ap._ep, "gate", no_gate)
    monkeypatch.setattr(liab, "check_liability_gate", refuse)
    monkeypatch.setattr("agentvault_registry.services.idempotency.idempotency_lookup", lookup)
    req = ap.AuthorizeRequest(target_agent_did="did:theprotocol:payee", amount="60")
    request = SimpleNamespace(headers={"X-Presence-Proof": '{"method": "challenge", "challenge_id": "lch_1"}'})
    with pytest.raises(HTTPException) as e:
        _run(ap.authorize_payment(req, request, current_agent=SimpleNamespace(did=DID, id=1), db=None,
                                  idempotency_key="tpx-1", liability_mandate=MID))
    assert e.value.status_code == 403
    assert called["mandate_id"] == MID and called["needed"] == "a2a.pay" and called["action_ref"] == "a2a-pay:tpx-1"
    assert called["amount"] == "60" and called["counterparty_did"] == "did:theprotocol:payee"
    assert called["presence"] == {"method": "challenge", "challenge_id": "lch_1"}


# ── /buy: free_only and a kept answer ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def buy(monkeypatch):
    from agentvault_registry.background_tasks import leader
    from agentvault_registry.routers import a2a_payment as ap
    r = FakeRedis()

    async def _get():
        return r
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setenv("IDEMPOTENCY_DURABLE", "off")
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.005)
    state = {"runs": 0, "posts": [], "paid": False}

    async def quote(db, request, did):
        return ap.QuoteResponse(target_agent_did=did, payment_required=state["paid"], can_buy=True,
                                price="5" if state["paid"] else None, price_currency="ECU",
                                endpoint="https://agent.example/a2a", issuer="https://registry.example",
                                recommended_amount="5.5" if state["paid"] else None)

    class _Client:
        async def post(self, url, json=None, headers=None, timeout=None):
            state["posts"].append((url, headers))
            raise AssertionError("no authorize for a free_only buy")

    async def call(client, endpoint, payload, token, issuer):
        state["runs"] += 1
        return {"ok": True, "http_status": 200,
                "body": {"jsonrpc": "2.0", "result": {"id": "task-1", "status": {"state": "completed"}}}}
    monkeypatch.setattr(ap, "_quote_for", quote)
    monkeypatch.setattr(ap, "_get_settle_client", lambda: _Client())
    from agentvault_registry.services import service_purchase as sp
    monkeypatch.setattr(sp, "call_agent", call)
    return ap, state


def _buy(ap, body, key):
    request = SimpleNamespace(headers={"Authorization": "Bearer agent-jwt"})
    resp = Response()

    async def go():
        out = await ap.buy_service(ap.BuyRequest(**body), request, current_agent=SimpleNamespace(did=DID, id=1),
                                   db=None, idempotency_key=key, http_response=resp)
        return out, resp
    return _run(go())


def test_a_repeated_buy_under_the_key_answers_the_first_answer_without_calling_the_agent_again(buy):
    ap, state = buy
    body = {"target_agent_did": "did:theprotocol:free-agent", "text": "hello", "free_only": True}
    first, _r1 = _buy(ap, body, "tpx-1")
    again, r2 = _buy(ap, body, "tpx-1")
    stage = lambda x: x["stage"] if isinstance(x, dict) else x.stage  # noqa: E731
    assert stage(first) == stage(again) == "called" and state["runs"] == 1
    assert r2.headers.get(cache.REPLAYED_HEADER) == "true"
    _buy(ap, body, "tpx-2")
    assert state["runs"] == 2, "another key is another task"


def test_free_only_refuses_an_agent_that_charges_before_anything_is_authorized_and_gives_the_key_back(buy):
    ap, state = buy
    state["paid"] = True
    body = {"target_agent_did": "did:theprotocol:paid-agent", "text": "hello", "free_only": True}
    out, _ = _buy(ap, body, "tpx-3")
    assert out.stage == "quoted" and "charges" in out.error and state["posts"] == [] and state["runs"] == 0
    state["paid"] = False                      # the agent made itself free: the same key runs, it was given back
    out, _ = _buy(ap, body, "tpx-3")
    assert (out["stage"] if isinstance(out, dict) else out.stage) == "called" and state["runs"] == 1




# ── session-lead, room seq 2439: under V0658 (o)'s rule, a caller still cannot be held to ANOTHER agent's mandate ──────
OTHER = "did:theprotocol:proxy-other-0002"


class _FilteringGateDB(_GateDB):
    """Holds one mandate, of OTHER, and answers the gate's read as its WHERE asks: the id, and the agent when the
    statement binds one. A gate that dropped its agent filter would be handed OTHER's mandate here."""

    async def execute(self, stmt, params=None):
        sql, p = " ".join(str(stmt).split()), dict(params or {})
        self.sql.append((sql, p))
        row = self.row
        hit = row is not None and p.get("m") in (None, row["id"])
        if "agent_did = CAST(:a AS VARCHAR)" in sql:
            hit = hit and p.get("a") == row["agent_did"]
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row if hit else None))


def test_a_mandate_of_another_agent_is_refused_and_never_underwrites_the_caller(gate):
    db = _FilteringGateDB(_row(agent_did=OTHER))       # signed, covers a2a.pay, within its limits: only the owner differs
    with pytest.raises(HTTPException) as e:
        _gate(db, mandate_id=MID, amount="1", currency="ECU")
    assert e.value.status_code == 403 and "no_mandate" in e.value.detail, e.value.detail
    assert db.sql and db.sql[0][1] == {"m": MID, "a": DID}, "the gate asks for this mandate of THIS agent"
    assert not [ev for ev in gate if ev[0] == "gate_pass"], "another agent's mandate never passes the gate"

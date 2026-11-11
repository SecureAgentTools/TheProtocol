"""D6-830 (V0658 (a)): a cloud operator asks its FX gateway before any money moves.

An operator's cross-registry transfer to a receiver it cannot place went up to its parent gateway's @fx_router first (the
ingress), and only the gateway then learned that nobody knew the receiver: the route returned the payment and the
operator answered 409, where a frame refuses the same transfer 400 up front. The operator now sends the route hop a dry
run first (the existing /fx/route-hop call, so no federation proxy needs a new path) and refuses 400, with nothing moved,
when the gateway says it cannot deliver. Everything else goes ahead as before, and the existing compensation stays the
fail-safe for a route that fails after the dry run said it could go.

Three surfaces, each through the real code with doubles only at the edges:
  the gateway   POST /api/v1/teg/fx/route-hop with dry_run, through FastAPI on the real TEG router (the database
                session, the receiver's home resolution and every leg are doubles; a leg reached is a sentinel)
  the origin    _fx_route_origin, with the gateway's answers, the ingress and the events as doubles
  the transfer  POST /api/v1/teg/cross-registry-transfer on an operator, the tester's made-up receiver

RED on v0657/cut (e70fb58b2): the gateway answers 422 to a dry-run body, the origin moves the ingress before it asks,
and the transfer to the made-up receiver reaches the ingress.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from agentvault_registry import security
from agentvault_registry.core import federation_auth
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import federation_license_gate as flg

TEG = pathlib.Path(ti.__file__)
ROUTER_DID = "did:theprotocol:fx-router-eu"
ROUTER = types.SimpleNamespace(id=12, did=ROUTER_DID, mtls_enabled=False, spiffe_id=None, status="active")
LOCAL_RECEIVER = types.SimpleNamespace(id=40, did="did:theprotocol:payee-on-eu", mtls_enabled=False, spiffe_id=None)
PAYER = types.SimpleNamespace(id=11, did="did:theprotocol:payer-amsterdam", mtls_enabled=False, spiffe_id=None,
                              status="active")
UNKNOWN = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-000000000000"
PRESENTER = "spiffe://eu.theprotocol.cloud/operator/amsterdam/registry"
GW = {"registry_id": "registry-eu", "router_did": ROUTER_DID, "teg_id": "teg-layer-eu", "url": "https://eu.example.test"}
RECEIVER_UNKNOWN = "receiver_unknown"   # ti.FX_ROUTE_RECEIVER_UNKNOWN (test_the_refusal_words_are_the_modules)


# ── the gateway: the route hop's dry run ────────────────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one

    def all(self):
        return []

    def first(self):
        return None

    def scalars(self):
        return types.SimpleNamespace(all=lambda: [], first=lambda: None)

    def scalar(self):
        return 0


class _GatewayDb:
    """The gateway's database: the @fx_router lookup answers the router, a lookup of the local receiver answers it when
    `receiver` is set, the compliance read answers no quarantine, anything else answers nothing."""

    def __init__(self, router=ROUTER, receiver=None):
        self.router, self.receiver, self.writes = router, receiver, 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            self.writes += 1
        if "federated_registry_compliance" in sql:
            return _Res()
        if "FROM agents" in sql:
            p = stmt.compile().params if hasattr(stmt, "compile") else {}
            did = next((v for v in p.values() if isinstance(v, str) and v.startswith("did:")), None)
            if did == ROUTER_DID:
                return _Res(one=self.router)
            if self.receiver is not None and did == self.receiver.did:
                return _Res(one=self.receiver)
        return _Res()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def legs(monkeypatch):
    """Sentinels on every step that moves money or reaches a TEG: a dry run reaches none of them."""
    out = []

    async def teg_token(agent_id, agent_did):
        out.append(("teg_token", agent_did))
        raise RuntimeError("sentinel: a TEG token was minted")

    async def refund(db, *a, **kw):
        out.append(("refund", a))
        return True

    async def egress(db, *a, **kw):
        out.append(("egress-local", a))
        return True, None, "1", "tx"

    async def two_pc(db, **kw):
        out.append(("2pc", kw.get("receiver_did")))
        return True, None, "1", "tx"

    async def swap(**kw):
        out.append(("swap", kw.get("dest_currency")))
        raise HTTPException(status_code=418, detail="sentinel: the FX core ran")

    async def dead_letter(db, **kw):
        out.append(("dead_letter", kw.get("phase")))

    monkeypatch.setattr(ti, "get_teg_token_for_agent", teg_token)
    monkeypatch.setattr(ti, "_fx_route_refund_to_origin", refund)
    monkeypatch.setattr(ti, "_fx_route_local_egress", egress)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", two_pc)
    monkeypatch.setattr(ti, "_fx_cross_currency_swap", swap)
    monkeypatch.setattr(ti, "_record_fx_dead_letter", dead_letter)
    monkeypatch.setattr(ti, "_emit_fx_route_event", lambda kind, **kw: out.append(("event", kind)))
    return out


@pytest.fixture
def gateway_env(monkeypatch):
    monkeypatch.setenv("FX_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTER_DID", ROUTER_DID)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "ECU")


def _home(monkeypatch, teg_id, registry_id, currency=None, peer=None):
    async def resolve(db, did):
        return teg_id, registry_id

    async def ccy(db, target_peer=None):
        return currency

    async def find_peer(db, registry_id):
        return peer
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)
    monkeypatch.setattr(ti, "_resolve_peer_currency", ccy)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", find_peer)


def _hop(db, body):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[federation_auth.require_peer_registry_identity] = lambda: PRESENTER
    return TestClient(app, raise_server_exceptions=False).post("/api/v1/teg/fx/route-hop", json=body)


def _dry(receiver):
    return {"dry_run": True, "final_receiver_did": receiver, "origin_did": PAYER.did,
            "origin_registry_id": "registry-amsterdam", "origin_teg_id": "teg-layer-amsterdam"}


def test_a_dry_run_for_a_receiver_nobody_knows_says_so_and_moves_nothing(monkeypatch, legs, gateway_env):
    _home(monkeypatch, None, None)
    db = _GatewayDb()
    r = _hop(db, _dry(UNKNOWN))
    assert r.status_code == 200, (r.status_code, r.text[:300])
    out = r.json()
    assert out["dry_run"] is True and out["routable"] is False and out["refusal"] == RECEIVER_UNKNOWN, out
    assert f"cannot resolve {UNKNOWN} from this frame" in out["detail"], out
    assert legs == [] and db.writes == 0, (legs, db.writes)


def test_a_dry_run_for_a_receiver_on_this_frame_can_go(monkeypatch, legs, gateway_env):
    _home(monkeypatch, None, None)   # the resolver answers None for one of the gateway's own agents
    r = _hop(_GatewayDb(receiver=LOCAL_RECEIVER), _dry(LOCAL_RECEIVER.did))
    assert r.status_code == 200 and r.json() == {"dry_run": True, "routable": True, "route": "egress-local",
                                                  "dest_currency": "ECU"}, r.text[:300]
    assert legs == [], legs


def test_a_dry_run_for_a_receiver_on_a_peer_of_this_unit_can_go(monkeypatch, legs, gateway_env):
    _home(monkeypatch, "teg-layer-lisbon", "registry-lisbon", currency="ECU",
          peer=types.SimpleNamespace(name="Lisbon", base_url="https://lisbon.example.test"))
    r = _hop(_GatewayDb(), _dry("did:theprotocol:payee-lisbon"))
    assert r.status_code == 200 and r.json()["routable"] is True and r.json()["route"] == "egress", r.text[:300]
    assert legs == [], legs


def test_a_dry_run_across_units_needs_a_gateway_for_that_unit(monkeypatch, legs, gateway_env):
    asia = types.SimpleNamespace(name="ASIA", base_url="https://asia.example.test")
    _home(monkeypatch, "teg-layer-asia", "registry-asia", currency="ACU", peer=asia)
    r = _hop(_GatewayDb(), _dry("did:theprotocol:payee-asia"))
    assert r.status_code == 200 and r.json()["routable"] is False and r.json()["refusal"] == "no_gateway", r.text[:300]
    monkeypatch.setenv("FX_ROUTE_PEERS", '[{"currency": "ACU", "registry_id": "registry-asia", '
                                         '"router_did": "did:theprotocol:fx-router-asia"}]')
    r = _hop(_GatewayDb(), _dry("did:theprotocol:payee-asia"))
    assert r.status_code == 200 and r.json()["routable"] is True and r.json()["route"] == "cross-currency", r.text[:300]
    assert legs == [], legs


@pytest.mark.parametrize("env,refusal", [({"FX_ROUTE_ENABLED": "false"}, "route_disabled"),
                                         ({"FX_ROUTER_DID": ""}, "no_router")])
def test_a_dry_run_on_a_gateway_that_could_not_route_at_all_says_so(monkeypatch, legs, gateway_env, env, refusal):
    _home(monkeypatch, None, None)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = _hop(_GatewayDb(), _dry(UNKNOWN))
    assert r.status_code == 200 and r.json()["routable"] is False and r.json()["refusal"] == refusal, r.text[:300]
    assert legs == [], legs


def test_a_dry_run_from_a_quarantined_presenter_is_refused_and_returns_nothing(monkeypatch, legs, gateway_env):
    _home(monkeypatch, None, None)

    async def quarantined(db, presenter):
        return ("Amsterdam", "quarantined")
    monkeypatch.setattr(flg, "quarantined_presenter", quarantined)
    r = _hop(_GatewayDb(), _dry(UNKNOWN))
    assert r.status_code == 200 and r.json()["refusal"] == "quarantined", r.text[:300]
    assert legs == [], legs   # nothing to return: nothing came in


def test_a_hop_that_moves_money_still_needs_its_route_and_amount(monkeypatch, legs, gateway_env):
    _home(monkeypatch, None, None)
    for body in ({"final_receiver_did": UNKNOWN},
                 {"final_receiver_did": UNKNOWN, "route_id": "r1"},
                 {"final_receiver_did": UNKNOWN, "amount": "1", "dry_run": False}):
        r = _hop(_GatewayDb(), body)
        assert r.status_code == 422, (body, r.status_code, r.text[:300])
    assert legs == [], legs


def test_control_a_hop_with_its_route_and_amount_still_runs_the_engine(monkeypatch, legs, gateway_env):
    """The same body as before V0658: the engine runs (here it cannot place the receiver and returns the ingress)."""
    _home(monkeypatch, None, None)
    r = _hop(_GatewayDb(), {"route_id": "6b1c0a58-1111-4b0e-9c3e-1d2a3b4c5d6e", "final_receiver_did": UNKNOWN,
                            "amount": "4.975", "origin_did": PAYER.did, "origin_registry_id": "registry-amsterdam",
                            "origin_teg_id": "teg-layer-amsterdam"})
    assert r.status_code == 409 and "cannot resolve" in r.json()["detail"], (r.status_code, r.text[:300])
    assert [k for k, _ in legs] == ["refund"], legs


def test_the_refusal_words_are_the_modules():
    assert ti.FX_ROUTE_RECEIVER_UNKNOWN == RECEIVER_UNKNOWN


class _HopBodyAtTheCut(BaseModel):
    """FxRouteHopRequest's required fields on v0657/cut (e70fb58b2), the image every gateway runs before V0658."""
    route_id: str
    final_receiver_did: str
    amount: str
    hop_budget: int = 4
    origin_did: str = ""


def test_an_older_gateway_refuses_the_dry_run_body_at_validation():
    body = ti._fx_route_dry_run_body(UNKNOWN, PAYER.did)
    assert tuple(body) == ti.FX_ROUTE_DRY_RUN_FIELDS
    assert "amount" not in body and "route_id" not in body
    with pytest.raises(ValidationError) as e:
        _HopBodyAtTheCut(**body)
    assert {err["loc"][0] for err in e.value.errors()} == {"route_id", "amount"}


# ── the origin: the operator asks before its ingress ────────────────────────────────────────────────────────────────

def _origin(monkeypatch, dry_answer, hop_answer=None, quarantined=None):
    """Run _fx_route_origin with the gateway answering the dry run `dry_answer` and the hop `hop_answer`. Returns
    (result or HTTPException, what was sent: ("dry", body) / ("hop", body) / ("ingress", receiver), the events)."""
    sent, events = [], []

    async def peer(db, reg):
        return types.SimpleNamespace(base_url="https://eu.example.test")

    async def ingress(db, **kw):
        sent.append(("ingress", kw.get("receiver_did")))
        return True, None, "9.95", "tx-ingress"

    async def delegate(url, body):
        if body.get("dry_run") is True:
            sent.append(("dry", dict(body)))
            return dry_answer
        sent.append(("hop", dict(body)))
        return hop_answer

    async def standing(db, registry_id):
        return quarantined

    async def resolve(db, did):
        return None, None

    async def ccy(db, target_peer=None):
        return None

    monkeypatch.setattr(ti, "_fx_route_my_gateway", lambda: dict(GW))
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", peer)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", ingress)
    monkeypatch.setattr(ti, "_fx_route_delegate", delegate)
    monkeypatch.setattr(flg, "quarantined_registry", standing)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)
    monkeypatch.setattr(ti, "_resolve_peer_currency", ccy)
    monkeypatch.setattr(ti, "_emit_fx_route_event", lambda kind, **kw: events.append(kind))
    req = ti.CrossRegistryTransferRequest(receiver_did=UNKNOWN, amount="10", message="")
    try:
        return asyncio.run(ti._fx_route_origin(None, PAYER, req)), sent, events
    except HTTPException as e:
        return e, sent, events


UNROUTABLE = {"dry_run": True, "routable": False, "refusal": RECEIVER_UNKNOWN,
              "detail": f"FX route egress: cannot resolve {UNKNOWN} from this frame (its card has not propagated here)"}
ROUTABLE = {"dry_run": True, "routable": True, "route": "egress", "dest_currency": "SBXB"}
SETTLED = {"status": "settled", "credited_amount": "9.90", "dest_currency": "SBXB", "dest_teg": "teg-layer-sbx-beta",
           "hops": [{"role": "egress"}]}


def test_a_receiver_the_gateway_cannot_place_is_refused_400_before_the_ingress(monkeypatch):
    e, sent, events = _origin(monkeypatch, UNROUTABLE)
    assert isinstance(e, HTTPException) and e.status_code == 400, e
    assert e.detail.startswith(f"Cannot resolve registry for receiver {UNKNOWN}") and "registry-eu" in e.detail
    assert e.detail.endswith(f"{ti.NO_FUNDS_MOVED}."), e.detail
    assert [k for k, _ in sent] == ["dry"] and events == [], (sent, events)   # no ingress, no hop, no event
    assert tuple(sent[0][1]) == ti.FX_ROUTE_DRY_RUN_FIELDS and sent[0][1]["final_receiver_did"] == UNKNOWN


def test_another_reason_the_gateway_gives_is_relayed_in_its_words(monkeypatch):
    e, sent, _ = _origin(monkeypatch, {"dry_run": True, "routable": False, "refusal": "route_disabled",
                                       "detail": "FX route disabled on this frame (FX_ROUTE_ENABLED=false)"})
    assert e.status_code == 400 and "FX route disabled on this frame" in e.detail and ti.NO_FUNDS_MOVED in e.detail
    assert [k for k, _ in sent] == ["dry"], sent


def test_the_refusal_says_nothing_moved_as_the_kept_attempt_reads_it():
    from agentvault_registry.services import payout_outcome as po
    detail = (f"Cannot resolve registry for receiver {UNKNOWN}: neither this registry nor its FX gateway registry-eu "
              f"knows it. For cross-registry transfers, the receiver must be a federated agent from an active peer "
              f"registry {ti.NO_FUNDS_MOVED}.")
    assert po.error_moved_nothing(400, detail)   # the Idempotency-Key is given back: the same key may run again


def test_a_real_foreign_receiver_still_settles(monkeypatch):
    out, sent, events = _origin(monkeypatch, ROUTABLE, SETTLED)
    assert not isinstance(out, HTTPException) and out.status == "completed", out
    assert [k for k, _ in sent] == ["dry", "ingress", "hop"], sent
    hop = sent[2][1]
    assert hop["amount"] == "9.95" and hop["route_id"] and hop["final_receiver_did"] == UNKNOWN
    assert events == ["FxRouteSettled"], events


@pytest.mark.parametrize("answer", [
    None,                                                                     # unreachable, or no gateway address
    {"status": "error", "http_status": 422, "detail": "Field required", "compensated": False, "not_delivered": False},
    {"status": "error", "http_status": 409, "detail": "FX route disabled on this frame", "compensated": False,
     "not_delivered": False},                                               # an older gateway, route off: no dry run
    {"routable": False, "detail": "no dry_run echo"},                        # not a dry-run answer
    {"dry_run": True, "routable": True},
])
def test_a_gateway_that_gives_no_dry_run_refusal_goes_ahead_as_before(monkeypatch, answer):
    out, sent, events = _origin(monkeypatch, answer, SETTLED)
    assert not isinstance(out, HTTPException) and out.status == "completed", out
    assert [k for k, _ in sent] == ["dry", "ingress", "hop"], sent
    assert events == ["FxRouteSettled"], events


def test_the_compensation_stays_the_fail_safe_after_a_dry_run_that_said_go(monkeypatch):
    """The receiver's card left the gateway between the dry run and the hop: the hop returns the ingress, as before."""
    returned = {"status": "error", "http_status": 409, "compensated": True, "not_delivered": True,
                "detail": f"FX route egress: cannot resolve {UNKNOWN} from this frame {ti._FX_COMPENSATED_MARK} "
                          f"{ti.NOT_DELIVERED}"}

    async def fee_back(route_id, payer_did, fees):
        return "tx-fee-back"
    monkeypatch.setattr(ti, "_fx_route_fee_back", fee_back)
    e, sent, events = _origin(monkeypatch, ROUTABLE, returned)
    assert isinstance(e, HTTPException) and e.status_code == 409, e
    assert ti._FX_COMPENSATED_MARK in e.detail and ti.NOT_DELIVERED in e.detail, e.detail
    assert [k for k, _ in sent] == ["dry", "ingress", "hop"] and events == ["FxRouteRefunded"], (sent, events)


def test_a_gateway_held_in_quarantine_is_not_asked(monkeypatch):
    out, sent, _ = _origin(monkeypatch, UNROUTABLE, SETTLED, quarantined=("EU", "quarantined"))
    assert "dry" not in [k for k, _ in sent], sent   # no request to it at all; the real ingress refuses it unsent
    assert [k for k, _ in sent][:1] == ["ingress"], sent


def test_the_origin_asks_before_its_first_leg():
    tree = ast.parse(TEG.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_fx_route_origin")
    lines = {name: min((c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                        and getattr(c.func, "id", "") == name), default=None)
             for name in ("_fx_route_gateway_refusal", "_fx_route_1to1_2pc", "_fx_route_delegate")}
    assert None not in lines.values(), lines
    assert lines["_fx_route_gateway_refusal"] < lines["_fx_route_1to1_2pc"] < lines["_fx_route_delegate"], lines


# ── the transfer: the tester's made-up receiver on an operator ──────────────────────────────────────────────────────

class _OperatorDb:
    """The operator's database: the receiver is no agent of this registry, nothing is quarantined."""

    async def execute(self, stmt, params=None):
        return _Res()

    async def commit(self):
        return None

    async def rollback(self):
        return None


def test_the_testers_made_up_receiver_gets_400_on_an_operator_and_nothing_moves(monkeypatch):
    monkeypatch.setenv("FX_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_REGISTRY_ID", "registry-eu")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_ROUTER_DID", ROUTER_DID)
    monkeypatch.setenv("FX_ROUTE_GATEWAY_URL", "https://eu.example.test")
    sent = []

    async def resolve(db, did):
        return None, None

    async def ingress(db, **kw):
        sent.append("ingress")
        raise AssertionError("the ingress ran")

    async def delegate(url, body):
        sent.append("dry" if body.get("dry_run") is True else "hop")
        return UNROUTABLE if body.get("dry_run") is True else SETTLED

    async def standing(db, registry_id):
        return None
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", ingress)
    monkeypatch.setattr(ti, "_fx_route_delegate", delegate)
    monkeypatch.setattr(flg, "quarantined_registry", standing)

    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield _OperatorDb()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_agent] = lambda: PAYER
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    r = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/teg/cross-registry-transfer", json={"receiver_did": UNKNOWN, "amount": "0.01"})
    assert r.status_code == 400, (r.status_code, r.text[:400])
    detail = r.json()["detail"]
    assert detail.startswith("Cannot resolve registry for receiver") and ti.NO_FUNDS_MOVED in detail, detail
    assert sent == ["dry"], sent

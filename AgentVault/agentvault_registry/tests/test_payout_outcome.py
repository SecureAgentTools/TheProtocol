"""§REPATLANE (V0603): what one AGORA gateway payout's answer proves about the money (services/payout_outcome.py).

His words 2026-10-12: "fix the two payout lane flaws too. but look into it properly so there is no confusion or fail
implementation" and "also fix this found flaw". Measured on the sandbox 2026-09-22 to 10-12: 28 FX routes from the two
operator gateways stranded after the payer's leg moved, the lane sent each again about 90 s later, and the FX keeper's
recovery delivered 14 of the stranded routes as well: 14 traders paid twice (146.1084 SBXA, 27.8151 SBXB). And a 200
whose body said "failed" was marked paid.

Pinned here: the classifier against every answer shape the rails give (a retry needs proof that the payout reached
nobody; anything else holds), and the rails' own sentences driven through the real code: the FX booth's two legs and its
refund (through the real retry helper, so a dropped connection that may have been delivered is seen), the route's 1:1
leg, the reserve frame's hop and its delegate read, the route origin, the dispatcher, and the 2PC branch's guards. The
review's three cases are here by name: a booth credit that timed out after the refund, a hop egress that timed out after
the refund, and an ingress that may still commit. RED control: the tree before §REPATLANE has no
services/payout_outcome (every test here errors), and each rail test fails on the first V0603 draft (it said "nothing
moved" after a refund whatever the paying leg had done).
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.services import payout_outcome as po

_HERE = pathlib.Path(__file__).resolve()
_PKG = _HERE.parents[1] / "src" / "agentvault_registry"
_RID = "6e062ba7-0f5e-4a3c-9d0e-6c1f2b3a4d5e"


class _Resp:
    def __init__(self, status_code, body=None, text=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _wrapped(code, inner):
    """The smart dispatcher's re-raise of an inner refusal, as the RFC 7807 layer puts it on the wire."""
    detail = json.dumps({"smart_send_method": "fx", "via": "/api/v1/teg/cross-registry-transfer", "inner": inner})
    return _Resp(code, {"detail": detail, "error": {"detail": detail}})


def _kind(code, detail):
    return po.classify(_wrapped(code, detail), None).kind


# ── the classifier ──────────────────────────────────────────────────────────────────────────────────────────────────

_STRANDED = (f"FX route did not settle (route_id={_RID}) and the gateway did not report a refund; the ingress is "
             f"parked at the gateway: Registry temporarily overloaded — please retry shortly.")
_POSTCONV = (f"FX route egress to sandbox-beta failed post-conversion; 18.955600 SBXA parked at "
             f"did:theprotocol:fx-router-sbxa (route_id={_RID})")
_COMPENSATED = (f"FX route did not settle (route_id={_RID}); the gateway compensates pre-conversion / dead-letters "
                f"post-conversion: it returned this payment (origin refunded).")
_COMPENSATED_UNDELIVERED = _COMPENSATED[:-1] + f" {po.NOT_DELIVERED}."


@pytest.mark.parametrize("resp,err,kind", [
    # paid: a 2xx whose status says the payout went out
    (_Resp(200, {"ok": True, "status": "completed", "transfer_id": _RID}), None, po.PAID),
    (_Resp(200, {"ok": True, "status": "settled", "transfer_id": _RID}), None, po.PAID),
    (_Resp(200, {"ok": True, "status": "locked", "transfer_id": _RID}), None, po.PAID),
    # flaw 3: a 200 whose body says failed is never paid; it retries only when the rail proved nothing moved
    (_Resp(200, {"ok": True, "status": "failed", "detail": {"status": "failed",
                 "error_message": "Partial commit - manual intervention required"}}), None, po.HOLD),
    (_Resp(200, {"ok": True, "status": "failed", "detail": {"status": "failed",
                 "error_message": "Target TEG rejected transfer (no funds moved)"}}), None, po.RETRY),
    (_Resp(200, {"ok": True, "status": "failed", "detail": {"status": "failed",
                 "error_message": "transfer x already in progress (no funds moved) (outcome not known)"}}), None, po.HOLD),
    (_Resp(200, {"ok": True, "status": "failed", "detail": {"status": "failed"}}), None, po.HOLD),
    (_Resp(200, {"ok": True}), None, po.HOLD),
    (_Resp(200, text="<html>ok</html>"), None, po.HOLD),
    # flaw 2: money moved into a route that parked or stranded: never sent again
    (_wrapped(409, _STRANDED), None, po.HOLD),
    (_wrapped(409, _POSTCONV), None, po.HOLD),
    (_wrapped(409, "FX route core swap did not complete"), None, po.HOLD),
    # a refund of the PAYER is not proof the payee was not paid (the review's cases 1 and 2)
    (_wrapped(409, _COMPENSATED), None, po.HOLD),
    (_wrapped(409, "FX swap refused at destination (source refunded): dest TEG unreachable: timed out"), None, po.HOLD),
    (_wrapped(409, "FX swap credit at destination failed (outcome not known) (credit key=k); the source was "
                   "refunded: dest TEG unreachable: timed out"), None, po.HOLD),
    (_wrapped(409, "FX route local egress failed: timed out (origin refunded) (outcome not known)"), None, po.HOLD),
    # ... an outcome nobody knows holds, whatever proof it quotes from the far side
    (_wrapped(409, "FX route ingress failed (outcome not known) (route_id=x): 2pc leg 503: ledger_unavailable: down"),
     None, po.HOLD),
    (_wrapped(502, "FX leg1 (source lock): the local TEG answered 500 (outcome not known) (key=k): (no funds moved)"),
     None, po.HOLD),
    # the rails' own proof that the payout reached nobody
    (_wrapped(409, _COMPENSATED_UNDELIVERED), None, po.RETRY),
    (_wrapped(409, "FX swap refused at destination (source refunded) (no funds moved): fx_reserve solvency gate"),
     None, po.RETRY),
    (_wrapped(402, "FX route ingress failed (no funds moved): 2pc leg 402: Insufficient balance"), None, po.RETRY),
    (_wrapped(409, "FX route ingress failed (no funds moved): 2pc leg 400: Failed to lock funds"), None, po.RETRY),
    (_Resp(503, {"detail": "ledger_unavailable: The ledger cannot record this right now. Nothing was moved."}), None,
     po.RETRY),
    (_wrapped(503, "The receiving frame's ledger cannot record this right now. Your payment came back to you."), None,
     po.RETRY),
    # ... and since V0605 /teg/send passes that answer on whole (the sentence alone)
    (_Resp(503, {"detail": "The receiving frame's ledger cannot record this right now. Your payment came back to you. "
                           "Try again shortly."}), None, po.RETRY),
    (_wrapped(503, "FX egress to sbx-beta is failing (3 consecutive post-conversion failures); route origination is "
                   "suspended and NO funds were moved."), None, po.RETRY),
    (_wrapped(400, "Cannot resolve registry for receiver did:x. If this is a local agent, use the normal transfer "
                   "endpoint. For cross-registry transfers, the receiver must be a federated agent from an active peer "
                   "registry (no funds moved)."), None, po.RETRY),
    (_wrapped(422, "FX size cap: amount_in 9 SBXA exceeds the per-swap cap 5 SBXA — split into smaller swaps "
                   "(no funds moved)."), None, po.RETRY),
    (_Resp(503, {"detail": "Registry temporarily overloaded — please retry shortly."},
           headers={"X-Admission-Shed": "internal"}), None, po.RETRY),
    (_Resp(502, {"detail": "smart-send dispatch failed (fx): All connection attempts failed (no funds moved)"}), None,
     po.RETRY),
    (_wrapped(409, "FX circuit breaker: spot price moved 40.0% > 25.0% within 60s — swaps paused (no funds moved). "
                   "Retry after the window or once the price stabilises."), None, po.RETRY),
    # refusals the dispatcher made before dispatching (no "smart_send_method" wrapper), and a 402
    (_Resp(402, {"detail": "Insufficient balance"}), None, po.RETRY),
    (_Resp(409, {"detail": "receiver is not reachable from this frame"}), None, po.RETRY),
    (_Resp(400, {"detail": "receiver_did is the sender"}), None, po.RETRY),
    (_Resp(401, {"detail": "Could not validate credentials"}), None, po.RETRY),
    (_Resp(429, {"detail": "Too Many Requests"}), None, po.RETRY),
    # an inner rail's refusal that does not say nothing moved holds (the review: booth leg 1 wrote a TEG 5xx as a 400)
    (_wrapped(400, "FX leg1 (source lock) failed: TEG 500"), None, po.HOLD),
    (_wrapped(400, "Transfer failed via stream: timed out"), None, po.HOLD),
    (_wrapped(404, "Not found"), None, po.HOLD),
    (_wrapped(409, "FX circuit breaker: spot price moved 40%"), None, po.HOLD),
    # unmarked server errors may have moved money
    (_Resp(500, {"detail": "Internal Server Error"}), None, po.HOLD),
    (_wrapped(503, "Cross-registry transfer service unavailable"), None, po.HOLD),
    (_wrapped(503, "Cross-registry transfer service unavailable (outcome not known): an earlier attempt may have "
                   "reached the TEG (transfer_id=x)"), None, po.HOLD),
    (_wrapped(503, "TEG cross-transfer service unreachable"), None, po.HOLD),
    (_Resp(502, {"detail": "smart-send dispatch failed (fx): timed out"}), None, po.HOLD),
    # the idempotency store's two 422s, and a validation 422
    (_wrapped(422, "Idempotency-Key 'repat-7' is claimed on this endpoint by an earlier request that has not stored a "
                   "result: it is still in progress, or it ended without one"), None, po.WAIT),
    (_wrapped(422, "Idempotency-Key 'repat-7' already used on this endpoint with a different request payload."), None,
     po.HOLD),
    (_Resp(422, {"detail": [{"loc": ["body", "amount"], "msg": "field required"}]}), None, po.RETRY),
    # the gateway itself refused (§GATEWAYROLE)
    (_wrapped(403, "Agent lacks required permission: teg.transfer_xreg"), None, po.SENDER_REFUSED),
    # transport: only a connection never made proves the registry saw nothing
    (None, httpx.ConnectError("refused"), po.RETRY),
    (None, httpx.ConnectTimeout("slow connect"), po.RETRY),
    (None, httpx.PoolTimeout("no slot"), po.RETRY),
    (None, httpx.ReadTimeout("45 s"), po.HOLD),
    (None, httpx.RemoteProtocolError("server disconnected"), po.HOLD),
    (None, httpx.ReadError("reset"), po.HOLD),
    (None, None, po.HOLD),
])
def test_every_answer_shape(resp, err, kind):
    assert po.classify(resp, err).kind == kind


def test_a_stranded_route_holds_even_when_it_quotes_a_refusal_that_says_nothing_moved():
    inner = _STRANDED.replace("Registry temporarily overloaded — please retry shortly.",
                              "FX route ingress failed (no funds moved): refused")
    o = po.classify(_wrapped(409, inner), None)
    assert (o.kind, o.tx) == (po.HOLD, _RID)


def test_a_paid_answer_names_its_transfer():
    o = po.classify(_Resp(200, {"ok": True, "status": "completed", "transfer_id": _RID}), None)
    assert (o.kind, o.tx) == (po.PAID, _RID)


def test_the_refund_sentences_are_not_proof():
    for s in ("(origin refunded)", "(source refunded)"):
        assert s not in po._NO_MOVE
    assert po.OUTCOME_UNKNOWN in po._MOVED and po.OUTCOME_UNKNOWN not in po._NO_MOVE


def test_the_stored_answer_is_read_like_the_inner_endpoints_answer():
    assert po.classify_stored({"status": "completed", "transfer_id": _RID}).kind == po.PAID
    assert po.classify_stored({"status": "locked", "transfer_id": _RID}).kind == po.PAID
    assert po.classify_stored({"status": "failed", "error_message": "Partial commit"}).kind == po.HOLD
    assert po.classify_stored(None).kind == po.HOLD


def test_a_hold_ref_round_trips_and_fits_the_column():
    ref = po.hold_ref("repagg-0123456789abcdef0123", "http 409: the ingress | is parked " + "x" * 200, now=1760000000)
    assert len(ref) <= 128
    key, why, at = po.parse_hold_ref(ref)
    assert (key, at) == ("repagg-0123456789abcdef0123", 1760000000) and "|" not in why
    assert po.parse_hold_ref("repat-7") == ("", "", None)
    assert po.parse_hold_ref(None) == ("", "", None)
    assert po.parse_hold_ref(po.hold_ref("", "legacy"))[0] == ""


def test_a_claim_and_a_retry_mark_are_told_apart():
    c = po.claim_ref("repat-7", "ab12cd34", now=1760000000)
    assert po.parse_hold_ref(c) == ("repat-7", "claim ab12cd34", 1760000000)
    r = po.retry_ref("http 402: the TEG refused before moving", now=1760000000)
    assert r.startswith(po.RETRY_PREFIX) and len(r) <= 128 and not c.startswith(po.RETRY_PREFIX)
    assert po.claim_nonce() != po.claim_nonce()


class _Redis:
    def __init__(self, store, fail=False):
        self.store, self.fail = store, fail

    async def get(self, k):
        if self.fail:
            raise ConnectionError("redis down")
        return self.store.get(k)


from agentvault_registry.services.idempotency import cache as _cache  # noqa: E402

_GW = _cache.agent_caller("did:theprotocol:agora-gateway")   # D6-777: the lane's records are the gateway's
_OTHER = _cache.agent_caller("did:theprotocol:someone-else")


def _at(scope, caller=_GW, key="repat-7"):
    return _cache._cache_key(scope, key, caller)


@pytest.mark.parametrize("store,fail,want", [
    ({_at("teg.cross-registry-transfer"): json.dumps(
        {"body_hash": "h", "response": {"status": "completed", "transfer_id": _RID}})}, False, "stored"),
    ({_at("teg.transfer"): json.dumps({"body_hash": "h", "response": {"status": "completed"}})}, False, "stored"),
    ({_at("teg.cross-registry-transfer"): json.dumps({"body_hash": "h", "pending": True})}, False, "claimed"),
    # D6-777: another caller's record under the lane's key is not the lane's answer
    ({_at("teg.transfer", _OTHER): json.dumps({"body_hash": "h", "response": {"status": "completed"}})}, False, "none"),
    # D6-777: a record kept before records were the caller's names no caller: never an answer, never "none"
    ({"idempotency:teg.transfer:repat-7": json.dumps({"body_hash": "h", "response": {"status": "completed"}})}, False,
     "unmatched"),
    ({}, False, "none"),
    ({}, True, "unknown"),
])
def test_the_store_is_read_without_claiming(monkeypatch, store, fail, want):
    import agentvault_registry.background_tasks.leader as leader
    r = _Redis(store, fail)

    async def _get_redis():
        return r
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    # _Redis has no `set`: a read that tried to claim the key would raise and come back "unknown"
    state, ans = asyncio.run(po.stored_answer("repat-7", callers=(_GW,)))
    assert state == want


def test_a_record_from_before_is_read_only_where_the_reader_says_so(monkeypatch):
    """D6-777: the A2A sweep's settlement key carries a digest only the token's parties hold, so its earlier records are
    read as they were written (unscoped_reads); the lane's keys are guessable, so its earlier records are never answers."""
    import agentvault_registry.background_tasks.leader as leader
    r = _Redis({"idempotency:teg.transfer:repat-7": json.dumps({"body_hash": "h", "response": {"status": "completed"}})})

    async def _get_redis():
        return r
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    assert asyncio.run(po.stored_answer("repat-7", callers=(_GW,)))[0] == "unmatched"
    assert asyncio.run(po.stored_answer("repat-7", callers=(_GW,), unscoped_reads=True)) == (
        "stored", {"status": "completed"})
    with pytest.raises(ValueError):
        asyncio.run(po.stored_answer("repat-7", callers=()))


def test_no_redis_is_unknown_never_none(monkeypatch):
    import agentvault_registry.background_tasks.leader as leader

    async def _none():
        return None
    monkeypatch.setattr(leader, "get_redis", _none)
    assert asyncio.run(po.stored_answer("repat-7", callers=(_GW,)))[0] == "unknown"


def test_the_permission_pattern_is_the_lanes():
    from agentvault_registry.services import exchange_service as svc
    assert svc._PERM_REFUSAL.pattern == po._PERM.pattern


# ── the TEG legs, through the real retry helper ─────────────────────────────────────────────────────────────────────

class _TegClient:
    """A TEG client whose answers come from a script keyed by the leg (the fx/move `reason`, or the URL's last part):
    each entry an exception to raise, a status (int) to answer, or (status, body), consumed per attempt. A leg asked
    more often than its script allows, or not scripted at all, fails the test by name."""

    def __init__(self, script):
        self.script, self.calls, self.keys = {k: list(v) for k, v in script.items()}, [], []

    async def post(self, url, json=None, headers=None, timeout=None):
        leg = (json or {}).get("reason") or url.rsplit("/", 1)[-1]
        self.calls.append(leg)
        self.keys.append((leg, (json or {}).get("idempotency_key")))
        if not self.script.get(leg):
            raise AssertionError(f"the booth asked {leg} beyond its script (asked: {self.calls})")
        step = self.script[leg].pop(0)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, tuple):
            return _Resp(step[0], step[1])
        body = ({"status": "completed", "transaction_id": f"tx-{leg}", "transaction_hash": f"h-{leg}"} if step == 200
                else {"detail": f"TEG {step}"})
        return _Resp(step, body)


@pytest.fixture(autouse=True)
def _nobody_in_quarantine(monkeypatch):
    """D6-801: the money paths read the compliance state before they move anything. The fakes here model no
    federated_registry_compliance table (the booth and the leg even run with db=None), so that read answers that this
    registry holds nobody in quarantine; tests/test_sec_quarantine_blocks_settlement.py drives the refusals."""
    from agentvault_registry.services import federation_license_gate as flg

    async def _nobody(db, registry_id):
        return None
    monkeypatch.setattr(flg, "quarantined_registry", _nobody, raising=False)


@pytest.fixture
def no_wait(monkeypatch):
    """Replays without the pauses: three replays after the first attempt (FX_LEG_RESOLVE_DELAYS)."""
    monkeypatch.setenv("FX_LEG_RESOLVE_DELAYS", "0,0,0")


def _booth(monkeypatch, script):
    """Drive the real FX booth (_fx_cross_currency_swap) with TEG legs answered by `script`. Returns its answer (the
    HTTPException it raised, or its response), the TEG client, and the held dead letters it recorded."""
    from agentvault_registry.routers import teg_integration as ti
    monkeypatch.setenv("FX_ENABLED", "true")
    monkeypatch.setenv("FX_RATE_MODE", "fixed")
    monkeypatch.setattr(ti, "_fx_rate", lambda a, b: Decimal("1"))

    async def _base(*a, **k):
        return "https://dest-teg.example:8443"

    async def _pct(*a, **k):
        return None
    held = []

    async def _dl(db, **kw):
        held.append(kw)
    monkeypatch.setattr(ti, "_resolve_dest_teg_mtls_base", _base)
    monkeypatch.setattr(ti, "_resolve_peer_fx_pool_pct", _pct)
    monkeypatch.setattr(ti, "_emit_fx_event", lambda *a, **k: None)
    monkeypatch.setattr(ti, "_record_fx_dead_letter", _dl)
    client = _TegClient(script)
    monkeypatch.setattr(ti, "_get_teg_client", lambda: client)
    req = ti.CrossRegistryTransferRequest(receiver_did="did:theprotocol:trader-1", amount="2.0")
    agent = SimpleNamespace(did="did:theprotocol:agora-gateway-sbxa")
    try:
        out = asyncio.run(ti._fx_cross_currency_swap(
            xfer_req=req, current_agent=agent, sender_did=agent.did, target_teg_id="teg-b",
            target_registry_id="sbx-beta", target_peer=None, source_currency="SBXA", dest_currency="SBXB", db=None))
    except HTTPException as e:
        return e, client, held
    return out, client, held


_DROP = httpx.RemoteProtocolError("server disconnected without sending a response")
_RT = httpx.ReadTimeout("20 s")
_CE = httpx.ConnectError("connection refused")
_IN_FLIGHT = (409, {"detail": "fx/move leg in flight for this idempotency key — retry shortly"})


@pytest.mark.parametrize("script,code,kind,refunds,held", [
    # leg 1 never connected, on every attempt (three connect tries per call, four calls): nothing moved
    ({"fx_swap_lock": [_CE] * 12}, 503, po.RETRY, 0, 0),
    # the TEG refused leg 1 on its first attempt: nothing moved
    ({"fx_swap_lock": [400]}, 400, po.RETRY, 0, 0),
    # leg 1 may have moved and stays unknown: nothing goes on, nothing is refunded, the swap is held
    ({"fx_swap_lock": [_RT, _IN_FLIGHT, _IN_FLIGHT, _IN_FLIGHT]}, 502, po.HOLD, 0, 1),
    ({"fx_swap_lock": [_DROP, 400, 400, 400, 400]}, 502, po.HOLD, 0, 1),
    # leg 2 refused on its first attempt, the sender's leg returned: nothing reached the receiver
    ({"fx_swap_lock": [200], "fx_swap_credit": [400], "fx_swap_refund": [200]}, 409, po.RETRY, 1, 0),
    ({"fx_swap_lock": [200], "fx_swap_credit": [_CE] * 12, "fx_swap_refund": [200]}, 409, po.RETRY, 1, 0),
    # ... the refund itself asked until known
    ({"fx_swap_lock": [200], "fx_swap_credit": [400], "fx_swap_refund": [500, 200]}, 409, po.RETRY, 2, 0),
    # the review's case 1: the credit may have landed, so nothing is refunded and the swap is held
    ({"fx_swap_lock": [200], "fx_swap_credit": [_RT, _IN_FLIGHT, _IN_FLIGHT, _IN_FLIGHT]}, 502, po.HOLD, 0, 1),
    ({"fx_swap_lock": [200], "fx_swap_credit": [504, 504, 504, 504]}, 502, po.HOLD, 0, 1),
    # a refusal after an answer that may have been the credit settles nothing (it can race the first attempt)
    ({"fx_swap_lock": [200], "fx_swap_credit": [_DROP, 400, 400, 400, 400]}, 502, po.HOLD, 0, 1),
    # a refused credit whose refund was refused or stays unknown: the sender's money sits in the reserve, held
    ({"fx_swap_lock": [200], "fx_swap_credit": [400], "fx_swap_refund": [400]}, 409, po.HOLD, 1, 1),
    ({"fx_swap_lock": [200], "fx_swap_credit": [400], "fx_swap_refund": [_RT, _IN_FLIGHT, _IN_FLIGHT, _IN_FLIGHT]},
     409, po.HOLD, 4, 1),
])
def test_the_booth_refunds_only_a_credit_that_provably_never_ran(monkeypatch, no_wait, script, code, kind, refunds,
                                                                  held):
    e, client, dl = _booth(monkeypatch, script)
    assert isinstance(e, HTTPException) and e.status_code == code, e
    assert _kind(e.status_code, e.detail) == kind, e.detail
    assert client.calls.count("fx_swap_refund") == refunds, client.calls
    assert len(dl) == held and all(d["phase"] == "swap_unknown" and d.get("note") for d in dl), dl
    if kind == po.HOLD:
        assert "(no funds moved)" not in e.detail
    assert all(not left for left in client.script.values()), f"answers the booth never asked for: {client.script}"
    for leg in {k for k, _ in client.keys}:
        assert len({key for k, key in client.keys if k == leg}) == 1, f"{leg} was asked again under another key"


@pytest.mark.parametrize("script", [
    {"fx_swap_lock": [200], "fx_swap_credit": [_RT, 200], "fx_swap_fee": [200]},            # it landed, or lands now
    {"fx_swap_lock": [200], "fx_swap_credit": [504, _IN_FLIGHT, 200], "fx_swap_fee": [200]},
    {"fx_swap_lock": [_RT, 200], "fx_swap_credit": [200], "fx_swap_fee": [200]},             # leg 1 settled by its replay
    {"fx_swap_lock": [200], "fx_swap_credit": [200], "fx_swap_fee": [200]},                  # control
])
def test_a_leg_whose_answer_was_lost_is_asked_again_and_the_swap_completes(monkeypatch, no_wait, script):
    out, client, dl = _booth(monkeypatch, script)
    assert getattr(out, "status", None) == "completed", out
    assert "fx_swap_refund" not in client.calls and dl == []


def _leg(monkeypatch, cross_teg):
    """Drive the route's real 1:1 leg (_fx_route_1to1_2pc) with the TEG's /cross-teg/transfer answered by `cross_teg`."""
    from agentvault_registry.routers import teg_integration as ti

    async def _token(*a, **k):
        return "Bearer t"

    async def _url(*a, **k):
        return "https://target-teg.example:8443"

    async def _events(*a, **k):
        return None
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _token)
    monkeypatch.setattr(ti, "_resolve_target_teg_url", _url)
    monkeypatch.setattr(ti, "_emit_cross_registry_events", _events)
    client = _TegClient({"add-partner": [200], "transfer": list(cross_teg)})
    monkeypatch.setattr(ti, "_get_teg_client", lambda: client)
    return asyncio.run(ti._fx_route_1to1_2pc(
        None, sender_agent=SimpleNamespace(id=1), sender_did="did:theprotocol:gw", receiver_did="did:theprotocol:r",
        amount="2.0", target_teg_id="teg-b", target_registry_id="sbx-beta", target_peer=None, memo="m"))


_LEDGER_503 = (503, {"detail": "ledger_unavailable: The ledger cannot record this right now. Nothing was moved.",
                     "code": "ledger_unavailable"})


@pytest.mark.parametrize("cross_teg,none", [
    ([httpx.ConnectError("x")] * 3, True),
    ([_DROP, httpx.ConnectError("x"), httpx.ConnectError("x")], False),
    ([httpx.ReadTimeout("30 s")], False),
    ([402], True),
    ([(400, {"detail": "Failed to lock funds"})], True),
    ([(400, {"detail": "Target TEG rejected transfer"})], True),
    ([(400, {"detail": "transfer 1234 already in progress"})], False),
    ([401], True),
    ([_LEDGER_503], True),
    ([500], False),
    ([_DROP, 402], False),
])
def test_the_routes_leg_says_whether_it_provably_moved_nothing(monkeypatch, cross_teg, none):
    from agentvault_registry.routers import teg_integration as ti
    ok, err, _cr, _tx = _leg(monkeypatch, cross_teg)
    assert ok is False and isinstance(err, str)
    assert ti._leg_moved_nothing(err) is none, err


def test_control_the_routes_leg_settles(monkeypatch):
    ok, err, credited, tx = _leg(monkeypatch, [200])
    assert ok is True and err is None and credited == "1.990000"


# ── the reserve frame's hop, its delegate read and the origin ───────────────────────────────────────────────────────

class _HopDB:
    """Answers the hop's agent lookups: the frame's @fx_router, and the receiver when it lives here."""

    def __init__(self, router_did, local_receiver=None):
        self.router_did, self.local_receiver = router_did, local_receiver

    async def execute(self, stmt, params=None):
        did = next(iter(stmt.compile().params.values()), None)
        if did == self.router_did:
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=9, did=did))
        if self.local_receiver and did == self.local_receiver:
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=10, did=did))
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _HopRun(SimpleNamespace):
    """What one hop drive produced: its answer (an HTTPException or its result), and what it did on the way."""


def _hop(monkeypatch, *, local, egress, refunded, post_conversion=False, amount="1.99"):
    """Drive the real hop's terminal branch on a reserve frame: the receiver lives here (`local`) or cannot be resolved;
    the local egress answers `egress` (a status, a tuple (status, body[, text]) or an exception, for every attempt; or
    a list consumed per attempt); the refund answers `refunded`."""
    from agentvault_registry.routers import teg_integration as ti
    router = "did:theprotocol:fx-router-sbxa"
    receiver = "did:theprotocol:trader-1"
    monkeypatch.setenv("FX_ROUTER_DID", router)
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")
    run = _HopRun(refunds=0, held=[], posts=[], answer=None)

    async def _resolve(db, did):
        return None, None

    async def _ccy(*a, **k):
        return None

    async def _token(*a, **k):
        return "Bearer t"

    async def _refund(*a, **k):
        run.refunds += 1
        return refunded

    async def _delivery(*a, **k):
        return None

    async def _dl(db, **kw):
        run.held.append(kw)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _token)
    monkeypatch.setattr(ti, "_fx_route_refund_to_origin", _refund)
    monkeypatch.setattr(ti, "_record_fx_delivery", _delivery)
    monkeypatch.setattr(ti, "_record_fx_dead_letter", _dl)
    seq = list(egress) if isinstance(egress, list) else None

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            run.posts.append(((headers or {}).get("Idempotency-Key"), (json or {}).get("amount")))
            step = seq.pop(0) if seq is not None else egress
            if isinstance(step, BaseException):
                raise step
            if isinstance(step, tuple):
                return _Resp(step[0], step[1], text=step[2] if len(step) > 2 else None)
            return _Resp(step, {"transaction_id": "tx-egress"} if step == 200 else {"detail": f"TEG {step}"})
    monkeypatch.setattr(ti.httpx, "AsyncClient", _C)
    db = _HopDB(router, receiver if local else None)
    try:
        run.answer = asyncio.run(ti._fx_route_hop_execute_inner(
            db, route_id=_RID, final_receiver_did=receiver, amount=amount, hop_budget=4,
            origin_did="did:theprotocol:agora-gateway-sbxalphaop-sbxa", origin_frame="sbxalphaop", memo="",
            post_conversion=post_conversion))
    except HTTPException as e:
        run.answer = e
    if seq is not None:
        assert not seq, f"egress answers the hop never asked for: {seq}"
    return run


def _through_the_origin(monkeypatch, hop_refusal):
    """The hop's refusal as the origin reads it (the real delegate read of the gateway's answer), and the origin's answer
    to the payer."""
    from agentvault_registry.routers import teg_integration as ti

    class _GwClient:
        async def post(self, *a, **k):
            return _Resp(hop_refusal.status_code, {"detail": hop_refusal.detail})
    monkeypatch.setattr(ti, "_get_teg_client", lambda: _GwClient())
    onward = asyncio.run(ti._fx_route_delegate("https://gw.example", {"origin_agent_spiffe": ""}))
    return onward, _origin_route(monkeypatch, onward)


@pytest.mark.parametrize("local,egress,refunded,kind,refunds,held,posts", [
    # nothing was posted to the receiver, or the TEG refused the first attempt, and the payer is refunded:
    # nothing reached the receiver
    (False, None, True, po.RETRY, 1, 0, 0),
    (True, 402, True, po.RETRY, 1, 0, 1),
    (True, (400, {"detail": "Insufficient balance"}), True, po.RETRY, 1, 0, 1),
    (True, httpx.ConnectError("x"), True, po.RETRY, 1, 0, 4),
    # the review's case 2: the egress may have paid the receiver, so nothing is refunded; the route is parked for the
    # keeper, which finishes it under the same key
    (True, httpx.ReadTimeout("15 s"), True, po.HOLD, 0, 1, 4),
    (True, 500, True, po.HOLD, 0, 1, 4),
    (True, 409, True, po.HOLD, 0, 1, 4),
    # a refusal after an answer that may have been the payment settles nothing (it can race the first attempt)
    (True, [httpx.ReadTimeout("15 s"), 402, 402, 402], True, po.HOLD, 0, 1, 4),
    # the refund itself failed: dead-lettered, the origin reads the ingress as stranded
    (False, None, False, po.HOLD, 1, 0, 0),
    (True, 402, False, po.HOLD, 1, 0, 1),
])
def test_the_hops_refusal_reaches_the_payer_as_what_it_proves(monkeypatch, no_wait, local, egress, refunded, kind,
                                                              refunds, held, posts):
    run = _hop(monkeypatch, local=local, egress=egress, refunded=refunded)
    e = run.answer
    assert isinstance(e, HTTPException) and e.status_code == 409, e
    assert (run.refunds, len(run.held), len(run.posts)) == (refunds, held, posts), (run.refunds, run.held, run.posts)
    assert all(h["phase"] == "egress_unknown" and h["receiver_did"] and h.get("note") for h in run.held)
    assert {k for k, _ in run.posts} <= {f"fxroute:{_RID}:egress-local"}, "every attempt carries the route's own key"
    onward, origin = _through_the_origin(monkeypatch, e)
    assert onward["compensated"] is (refunds == 1 and refunded)
    assert onward["not_delivered"] is (kind == po.RETRY)
    assert _kind(origin.status_code, origin.detail) == kind, origin.detail


@pytest.mark.parametrize("egress", [[httpx.ReadTimeout("15 s"), 200], [500, (409, {"detail": "already processed"}), 200],
                                    [httpx.RemoteProtocolError("dropped"), 200]])
def test_an_egress_whose_answer_was_lost_is_asked_again_and_the_route_settles(monkeypatch, no_wait, egress):
    run = _hop(monkeypatch, local=True, egress=egress, refunded=True)
    assert isinstance(run.answer, dict) and run.answer["status"] == "settled", run.answer
    assert run.refunds == 0 and run.held == []
    assert len({k for k, _ in run.posts}) == 1, "one key for every attempt"


def test_the_egress_amount_is_spelled_one_way_so_a_replay_carries_the_same_request(monkeypatch, no_wait):
    a = _hop(monkeypatch, local=True, egress=200, refunded=True, amount="1.990000000000000000")
    b = _hop(monkeypatch, local=True, egress=200, refunded=True, amount="1.99")
    assert a.posts == b.posts == [(f"fxroute:{_RID}:egress-local", "1.99")]


def test_after_a_conversion_an_unknown_egress_is_parked_by_the_frame_that_converted(monkeypatch, no_wait):
    run = _hop(monkeypatch, local=True, egress=httpx.ReadTimeout("15 s"), refunded=True, post_conversion=True)
    assert isinstance(run.answer, HTTPException) and po.OUTCOME_UNKNOWN in run.answer.detail
    assert run.refunds == 0 and run.held == [], "the gateway that converted records post_conversion_remote"


def test_a_200_from_the_egress_is_a_payment_whatever_its_body_says(monkeypatch, no_wait):
    run = _hop(monkeypatch, local=True, egress=(200, None, "<html>not json</html>"), refunded=True)
    assert isinstance(run.answer, dict) and run.answer["status"] == "settled"


def _hop_core(monkeypatch, booth_detail, refunded=True, answer=None):
    """Drive the hop's cross-currency branch with a core swap that refuses with `booth_detail` (or answers `answer`)."""
    from agentvault_registry.routers import teg_integration as ti
    monkeypatch.setenv("FX_ROUTER_DID", "did:theprotocol:fx-router-sbxa")
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")
    calls = {"refunds": 0}

    async def _resolve(db, did):
        return "teg-b", "sbx-beta"

    async def _peer(db, rid):
        return SimpleNamespace(base_url="https://sbx-beta.example", trust_domain="sbx-beta")

    async def _ccy(*a, **k):
        return "SBXB"

    async def _no_refusal(*a, **k):
        return None

    async def _swap(**kw):
        if answer is not None:
            return answer
        raise HTTPException(status_code=409, detail=booth_detail)

    async def _refund(*a, **k):
        calls["refunds"] += 1
        return refunded
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_fx_route_gateway_for_currency",
                        lambda ccy: {"router_did": "did:theprotocol:fx-router-sbxb", "registry_id": "sbx-beta",
                                     "teg_id": "teg-b", "url": ""})
    monkeypatch.setattr(ti, "_fx_route_gd_ledger_refusal", _no_refusal)
    monkeypatch.setattr(ti, "_fx_cross_currency_swap", _swap)
    monkeypatch.setattr(ti, "_fx_route_refund_to_origin", _refund)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ti._fx_route_hop_execute_inner(
            _HopDB("did:theprotocol:fx-router-sbxa"), route_id=_RID, final_receiver_did="did:theprotocol:trader-2",
            amount="1.99", hop_budget=4, origin_did="did:theprotocol:agora-gateway-sbxalphaop-sbxa",
            origin_frame="sbxalphaop", memo=""))
    return e.value, calls["refunds"]


@pytest.mark.parametrize("booth_detail,refunds,kind", [
    # the swap refused before its first leg, or its credit was refused and its own refund made: the money is here
    (f"FX size cap: amount_in 9 SBXA exceeds the per-swap cap 5 SBXA — split into smaller swaps {po.NO_FUNDS_MOVED}.", 1,
     po.RETRY),
    (f"FX swap refused at destination (source refunded) {po.NO_FUNDS_MOVED}: fx_reserve solvency gate", 1, po.RETRY),
    # a leg whose outcome is not known, or a refund that failed: the money is in the reserves, nothing is refunded
    (f"FX swap credit at destination {po.OUTCOME_UNKNOWN}: held for a ledger read, nothing refunded (swap s)", 0, po.HOLD),
    (f"FX leg1 (source lock) {po.OUTCOME_UNKNOWN}: held for a ledger read, nothing refunded (swap s)", 0, po.HOLD),
    ("FX swap refused at destination; the source refund FAILED: held for a ledger read (swap s)", 0, po.HOLD),
])
def test_a_core_swap_refunds_the_origin_only_when_it_proves_the_money_is_here(monkeypatch, booth_detail, refunds, kind):
    e, n = _hop_core(monkeypatch, booth_detail)
    assert n == refunds, (n, e.detail)
    onward, origin = _through_the_origin(monkeypatch, e)
    assert _kind(origin.status_code, origin.detail) == kind, origin.detail


def _hop_2pc(monkeypatch, result, *, refunded=True, post_conversion=False):
    """Drive the hop's same-currency egress to a receiver on a leaf operator (the two-phase leg), answering `result`
    (ok, err, credited, transfer_id). Returns the hop's answer, the refunds attempted, the held rows and deliveries."""
    from agentvault_registry.routers import teg_integration as ti
    router = "did:theprotocol:fx-router-sbxa"
    monkeypatch.setenv("FX_ROUTER_DID", router)
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")
    run = _HopRun(refunds=0, held=[], deliveries=[], legs=[], answer=None)

    async def _resolve(db, did):
        return "teg-sbxalphaop", "registry-sbxalphaop"

    async def _peer(db, rid):
        return SimpleNamespace(base_url="https://sbxalphaop.example", trust_domain="sbxalphaop")

    async def _ccy(*a, **k):
        return None   # the same currency as this frame: the terminal 1:1 egress

    async def _two_pc(db, **kw):
        run.legs.append(kw)
        return result

    async def _refund(*a, **k):
        run.refunds += 1
        return refunded

    async def _dl(db, **kw):
        run.held.append(kw)

    async def _delivery(db, **kw):
        run.deliveries.append(kw)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_fx_route_refund_to_origin", _refund)
    monkeypatch.setattr(ti, "_record_fx_dead_letter", _dl)
    monkeypatch.setattr(ti, "_record_fx_delivery", _delivery)
    try:
        run.answer = asyncio.run(ti._fx_route_hop_execute_inner(
            _HopDB(router), route_id=_RID, final_receiver_did="did:theprotocol:trader-on-a-leaf", amount="1.99",
            hop_budget=4, origin_did="did:theprotocol:agora-gateway-sbxbetaop-sbxb", origin_frame="sbxbetaop", memo="",
            post_conversion=post_conversion))
    except HTTPException as e:
        run.answer = e
    assert [leg["memo"] for leg in run.legs] == [f"fxroute:{_RID}:egress"], "one two-phase leg, never asked again"
    return run


def _le(text, nothing_moved):
    from agentvault_registry.routers import teg_integration as ti
    return ti._LegError(text, nothing_moved=nothing_moved)


@pytest.mark.parametrize("err,refunded,kind,refunds,held", [
    # refused at prepare (the coordinator's own clean abort), or never connected: the origin is refunded
    (lambda: _le("2pc leg 400: Target TEG rejected transfer", True), True, po.RETRY, 1, 0),
    (lambda: _le("local TEG unreachable: ConnectError: refused", True), True, po.RETRY, 1, 0),
    # ... and the refund failed: the origin reads it as stranded
    (lambda: _le("2pc leg 400: Target TEG rejected transfer", True), False, po.HOLD, 1, 0),
    # the egress may have paid the receiver: nothing is refunded, the route is held under its transfer id
    (lambda: _le("local TEG unreachable: ReadTimeout: 30 s", False), True, po.HOLD, 0, 1),
    (lambda: _le("2pc leg 500: internal error", False), True, po.HOLD, 0, 1),
    (lambda: "2pc leg 504: an error nobody classified", True, po.HOLD, 0, 1),
])
def test_the_two_phase_egress_refunds_the_origin_only_after_a_provable_refusal(monkeypatch, err, refunded, kind,
                                                                               refunds, held):
    run = _hop_2pc(monkeypatch, (False, err(), "0", "tid-2pc-1"), refunded=refunded)
    e = run.answer
    assert isinstance(e, HTTPException) and e.status_code == 409, e
    assert (run.refunds, len(run.held)) == (refunds, held), (run.refunds, run.held, e.detail)
    assert run.deliveries == []
    for h in run.held:
        assert h["phase"] == "egress_2pc_unknown" and h["receiver_did"] == "did:theprotocol:trader-on-a-leaf"
        assert "transfer_id=tid-2pc-1" in h["note"]
    if held:
        assert po.OUTCOME_UNKNOWN in e.detail and "transfer_id=tid-2pc-1" in e.detail
    onward, origin = _through_the_origin(monkeypatch, e)
    assert onward["compensated"] is (refunds == 1 and refunded)
    assert _kind(origin.status_code, origin.detail) == kind, origin.detail


def test_after_a_conversion_an_unknown_two_phase_egress_is_still_held_here(monkeypatch):
    # the converting frame parks the route for this frame's keeper to re-deliver; this row is what stops it
    run = _hop_2pc(monkeypatch, (False, _le("local TEG unreachable: ReadTimeout", False), "0", "tid-2pc-2"),
                   post_conversion=True)
    assert run.refunds == 0 and [h["phase"] for h in run.held] == ["egress_2pc_unknown"]
    assert po.OUTCOME_UNKNOWN in run.answer.detail


def test_after_a_conversion_a_refused_two_phase_egress_refunds_nobody(monkeypatch):
    run = _hop_2pc(monkeypatch, (False, _le("2pc leg 400: Target TEG rejected transfer", True), "0", "tid-2pc-3"),
                   post_conversion=True)
    assert run.refunds == 0 and run.held == [], "after a conversion the converting frame parks it for re-delivery"
    assert "re-delivery" in run.answer.detail


def test_control_a_two_phase_egress_that_settles_is_recorded_as_delivered(monkeypatch):
    run = _hop_2pc(monkeypatch, (True, None, "1.98005", "tid-2pc-ok"))
    assert isinstance(run.answer, dict) and run.answer["status"] == "settled"
    assert run.refunds == 0 and run.held == [] and [d["kind"] for d in run.deliveries] == ["egress"]


def test_a_core_swap_that_answers_without_completing_refunds_nothing(monkeypatch):
    # either leg may have moved: the money is in the reserves or with GD's @fx_router, never provably here
    e, n = _hop_core(monkeypatch, None, answer=SimpleNamespace(status="pending", credited_amount="0", transfer_id="s"))
    assert n == 0 and po.OUTCOME_UNKNOWN in e.detail, (n, e.detail)
    onward, origin = _through_the_origin(monkeypatch, e)
    assert onward["compensated"] is False
    assert _kind(origin.status_code, origin.detail) == po.HOLD, origin.detail


def test_the_delegate_reads_its_verdicts_from_the_whole_refusal(monkeypatch):
    from agentvault_registry.routers import teg_integration as ti
    long = "FX route local egress failed: " + "x" * 300 + f" (origin refunded) {po.NOT_DELIVERED}"

    class _GwClient:
        async def post(self, *a, **k):
            return _Resp(409, {"detail": long})
    monkeypatch.setattr(ti, "_get_teg_client", lambda: _GwClient())
    onward = asyncio.run(ti._fx_route_delegate("https://gw.example", {}))
    assert len(onward["detail"]) <= 200 and onward["compensated"] is True and onward["not_delivered"] is True


def _origin_route(monkeypatch, onward, ingress=(True, None, "1.990000", "tx-ingress"), fee_backs=None):
    """Drive the operator gateway's FX route origin (the path every sandbox repatriation took) with the ingress answer
    and the gateway's answer `onward`, and return what the origin answers. The fees it gives back (§REPATLANE-4) are
    recorded in `fee_backs` (route_id, payer, fees), never sent to a TEG."""
    from agentvault_registry.routers import teg_integration as ti

    async def _fee_back(route_id, payer_did, fees):
        if fee_backs is not None:
            fee_backs.append((route_id, payer_did, fees))
        return "tx-fee-back"
    monkeypatch.setattr(ti, "_fx_route_fee_back", _fee_back)
    monkeypatch.setenv("FX_ROUTE_GATEWAY_REGISTRY_ID", "sbx-alpha")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_ROUTER_DID", "did:theprotocol:fx-router-sbxa")
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")

    async def _peer(db, rid):
        return SimpleNamespace(base_url="https://sbx-alpha.example")

    async def _two_pc(db, **kw):
        return ingress

    async def _delegate(url, body):
        return onward

    async def _resolve(db, did):
        return ("teg-sbx-beta", "sbx-beta")

    async def _ccy(db, target_peer=None, trust_domain=None):
        return "SBXB"
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_fx_route_delegate", _delegate)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_emit_fx_route_event", lambda *a, **k: None)
    agent = SimpleNamespace(did="did:theprotocol:agora-gateway-sbxalphaop-sbxa", spiffe_id="", mtls_enabled=False)
    req = ti.CrossRegistryTransferRequest(receiver_did="did:theprotocol:sandbox-b.theprotocol.cloud:2c4395ad-4def-45fa-b379-cee1548af6db",
                                          amount="2.0", message="AGORA repatriation (refund) ref r1")
    with pytest.raises(HTTPException) as e:
        asyncio.run(ti._fx_route_origin(None, agent, req))
    return e.value


def test_a_compensated_route_without_the_gateways_proof_holds(monkeypatch):
    e = _origin_route(monkeypatch, {"status": "error", "http_status": 409, "compensated": True,
                                    "detail": "FX route local egress failed: timed out (origin refunded) (outcome not known)"})
    assert e.status_code == 409 and "(origin refunded)" in e.detail and po.NOT_DELIVERED not in e.detail
    assert _kind(409, e.detail) == po.HOLD


def test_a_compensated_route_that_reached_nobody_retries(monkeypatch):
    e = _origin_route(monkeypatch, {"status": "error", "http_status": 409, "compensated": True, "not_delivered": True,
                                    "detail": f"FX route core swap failed (origin refunded) {po.NOT_DELIVERED}: x"})
    assert "compensates pre-conversion" in e.detail and e.detail.endswith(f"{po.NOT_DELIVERED}.")
    assert _kind(409, e.detail) == po.RETRY


def test_a_stranded_route_holds(monkeypatch):
    e = _origin_route(monkeypatch, None)  # the gateway never answered: the ingress moved, nobody said where it went
    assert e.status_code == 409 and "the ingress is parked at the gateway" in e.detail
    o = po.classify(_wrapped(409, e.detail), None)
    assert o.kind == po.HOLD and o.tx


def test_a_route_parked_after_the_conversion_holds(monkeypatch):
    e = _origin_route(monkeypatch, {"status": "error", "http_status": 409, "compensated": False, "detail": _POSTCONV})
    assert _kind(409, e.detail) == po.HOLD


@pytest.mark.parametrize("nothing_moved,text,code,kind", [
    (True, "2pc leg 402: Insufficient balance", 402, po.RETRY),
    (True, "local TEG unreachable: All connection attempts failed", 409, po.RETRY),
    # the review's MAJOR: an ingress that may still commit is not "no funds moved"
    (False, "2pc leg 500: Failed to process transfer", 409, po.HOLD),
    (False, "local TEG unreachable: timed out", 409, po.HOLD),
    (False, "2pc leg 402: Insufficient balance", 409, po.HOLD),
    (None, "2pc leg 400: refused", 409, po.HOLD),   # a plain string nobody classified
])
def test_the_ingress_says_no_funds_moved_only_when_its_leg_proved_it(monkeypatch, nothing_moved, text, code, kind):
    from agentvault_registry.routers import teg_integration as ti
    err = text if nothing_moved is None else ti._LegError(text, nothing_moved=nothing_moved)
    e = _origin_route(monkeypatch, None, ingress=(False, err, "0", "tx"))
    assert e.status_code == code and _kind(code, e.detail) == kind, e.detail
    assert ("FX route ingress failed (no funds moved)" in e.detail) is (kind == po.RETRY)


# ── the dispatcher ──────────────────────────────────────────────────────────────────────────────────────────────────

def _dispatch(monkeypatch, exc):
    """Drive the smart dispatcher with an inner call that raises `exc`; return its 502."""
    from agentvault_registry.routers import teg_send as ts

    async def _route(db, **kw):
        return SimpleNamespace(method="fx", refusal_detail="", target_registry="sbx-beta", currency_sent="SBXA",
                               currency_received="SBXB", currency_source="card", notes=[],
                               endpoint="/api/v1/teg/cross-registry-transfer", body={})

    class _Client:
        async def post(self, *a, **k):
            raise exc
    monkeypatch.setattr(ts, "derive_route", _route)
    monkeypatch.setattr(ts, "_get_send_client", lambda: _Client())
    req = ts.SmartSendRequest(receiver_did="did:theprotocol:receiver-x", amount="2.0")
    request = SimpleNamespace(headers={"authorization": "Bearer jwt"})
    with pytest.raises(HTTPException) as e:
        asyncio.run(ts.smart_send(req, request, current_agent=SimpleNamespace(did="did:theprotocol:gw"), db=None,
                                  idempotency_key="repat-7"))
    return e.value


def test_a_dispatch_that_never_connected_says_nothing_moved(monkeypatch):
    e = _dispatch(monkeypatch, httpx.ConnectError("All connection attempts failed"))
    assert e.status_code == 502 and e.detail.endswith(po.NO_FUNDS_MOVED)
    assert po.classify(_Resp(502, {"detail": e.detail}), None).kind == po.RETRY


def test_control_a_dispatch_that_timed_out_says_nothing_about_what_moved(monkeypatch):
    e = _dispatch(monkeypatch, httpx.ReadTimeout("timed out"))
    assert e.status_code == 502 and po.NO_FUNDS_MOVED not in e.detail
    assert po.classify(_Resp(502, {"detail": e.detail}), None).kind == po.HOLD


# ── the plain 2PC branch: no proof after an attempt that may have reached the TEG ───────────────────────────────────

def _fn(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(name)


def _mentions(node, name):
    return any(isinstance(x, ast.Name) and x.id == name for x in ast.walk(node))


def twopc_guards(src):
    """In _cross_registry_transfer_run (the route's work), after `_maybe_reached = False`: every NO_FUNDS_MOVED sits under
    a condition that reads `_maybe_reached` (an IfExp's test or an If's test on the way down), the 402 raise is preceded
    by a raise of OUTCOME_UNKNOWN under `if _maybe_reached`, and the ledger refusal is raised only under
    `not _maybe_reached`.
    Returns the list of what is wrong (empty when every guard holds)."""
    fn = _fn(ast.parse(src), "_cross_registry_transfer_run")  # §REPATLANE-5: the route's work, under its attempt
    start = next(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_maybe_reached" for t in n.targets)
                 and isinstance(n.value, ast.Constant) and n.value.value is False)
    wrong, guarded = [], set()

    def walk(node, conds):
        if isinstance(node, ast.IfExp):
            walk(node.test, conds)
            for b in (node.body, node.orelse):
                walk(b, conds + [node.test])
            return
        if isinstance(node, (ast.If, ast.While)):
            walk(node.test, conds)
            for b in node.body + node.orelse:
                walk(b, conds + [node.test])
            return
        if isinstance(node, ast.Name) and node.id == "NO_FUNDS_MOVED" and node.lineno > start:
            if any(_mentions(c, "_maybe_reached") for c in conds):
                guarded.add(node.lineno)
            else:
                wrong.append(f"line {node.lineno}: NO_FUNDS_MOVED with no _maybe_reached guard")
        for ch in ast.iter_child_nodes(node):
            walk(ch, conds)
    walk(fn, [])
    if len(guarded) < 3:
        wrong.append(f"only {len(guarded)} guarded NO_FUNDS_MOVED after the TEG call (expected the 400, 401, transport)")
    raises_402 = [n for n in ast.walk(fn) if isinstance(n, ast.If) and _mentions(n.test, "_maybe_reached")
                  and any(isinstance(b, ast.Raise) and _mentions(b, "OUTCOME_UNKNOWN") for b in n.body)]
    if not raises_402:
        wrong.append("no OUTCOME_UNKNOWN raise under `if _maybe_reached` (the 402 after a reached attempt)")
    ledger = [n for n in ast.walk(fn) if isinstance(n, ast.If) and _mentions(n.test, "_refusal")
              and any(isinstance(b, ast.Raise) and isinstance(b.exc, ast.Name) and b.exc.id == "_refusal"
                      for b in n.body)]
    if not ledger or not all(_mentions(n.test, "_maybe_reached") for n in ledger):
        wrong.append("the ledger refusal is raised without a _maybe_reached guard")
    return wrong


def test_the_2pc_branch_proves_nothing_after_an_attempt_that_may_have_reached_the_teg():
    src = (_PKG / "routers" / "teg_integration.py").read_text(encoding="utf-8")
    assert twopc_guards(src) == []


@pytest.mark.parametrize("old,new", [
    ("if not _maybe_reached and any(str(error_msg).startswith(_m) for _m in _TEG_CLEAN_ABORTS):",
     "if any(str(error_msg).startswith(_m) for _m in _TEG_CLEAN_ABORTS):"),
    ("if _refusal is not None and not _maybe_reached:", "if _refusal is not None:"),
    ('+ ("" if _maybe_reached else f" {NO_FUNDS_MOVED}")', '+ f" {NO_FUNDS_MOVED}"'),
])
def test_control_each_guard_removed_is_seen(old, new):
    src = (_PKG / "routers" / "teg_integration.py").read_text(encoding="utf-8")
    assert old in src, old
    assert twopc_guards(src.replace(old, new, 1)) != []


def test_the_clean_aborts_are_the_coordinators_own_sentences():
    from agentvault_registry.routers import teg_integration as ti
    teg = _HERE.parents[2] / "agentvault_teg_layer_mvp" / "src" / "teg_core_service"
    coord = (teg / "core" / "cross_teg" / "coordinator.py").read_text(encoding="utf-8")
    router = (teg / "api" / "cross_teg_router.py").read_text(encoding="utf-8")
    assert '"Failed to lock funds", "PREPARE_FAILED"' in coord
    assert '"Target TEG rejected transfer", "REMOTE_PREPARE_FAILED"' in coord
    assert 'f"This TEG ({settings.teg_id}) is not the source TEG"' in router
    assert ti._TEG_CLEAN_ABORTS == ("Failed to lock funds", "Target TEG rejected transfer", "This TEG (")
    # what a 2PC failure that may have moved money says is not a clean abort
    for moved in ("Partial commit - manual intervention required", "Transfer coordination timeout"):
        assert not any(moved.startswith(m) for m in ti._TEG_CLEAN_ABORTS)
        assert f'"{moved}"' in coord


def test_fx_move_answers_409_while_a_leg_is_in_flight():
    # _leg_refused excludes 409 because the TEG's fx/move answers it while another attempt under the key may complete
    teg = _HERE.parents[2] / "agentvault_teg_layer_mvp" / "src" / "teg_core_service"
    src = (teg / "api" / "v1" / "endpoints_treasury.py").read_text(encoding="utf-8")
    assert src.count('message="fx/move leg in flight for this idempotency key — retry shortly"') == 2
    assert src.count("status_code=HTTP_409_CONFLICT") >= 2

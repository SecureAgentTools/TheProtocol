"""§DOCSFIX D6-441 (2026-10-16): an automatic cross-registry slash is reported only when the TEG moved it.

POST /federation/disputes/slash-request (this registry is the defendant's home) marked the settlement SLASHED, emitted
DisputeSlash for the full amount and told the complainant's registry "slashed" whenever the defendant's cached balance
covered the amount, even when its own TEG refused the treasury receive (or never answered): the complainant's registry
then paid compensation for a slash that never moved. A slash the TEG did not confirm is now a failed slash: the
settlement is FAILED with the reason, nothing is reported slashed, and the origin is told "failed".

§DOCSFIX review: an answer other than a confirmation is not a refusal once the request reached the TEG. A lost answer
(a timeout after the request went out, a 5xx) says nothing, and /treasury/receive answers 400 "Treasury receive failed"
for an error after its transfer committed. The TEG is asked once more under the same Idempotency-Key: its record
answers a slash it already made (it never debits twice), it refuses again what it refused, and a slash that never ran
runs. Only a slash still unconfirmed after that is failed, and a lost answer's reason says the outcome is not known. A
connection never made is not asked again.

RED on the pre-change tree: the two unconfirmed cases. RED before the review: the three answers the second ask turns
into the slash the TEG made, and the reasons of the lost answers it cannot (a second ask that never reaches the TEG
learns nothing, so the first answer stays unknown). The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import httpx

from agentvault_registry.routers import federation_disputes as fd
from tests._doubles import StrictEmitter

ORIGIN = "http://registry-a.peer.example"
DEFENDANT = "did:theprotocol:asia.theprotocol.cloud:defendant-0000"
COMPLAINANT = "did:theprotocol:eu.theprotocol.cloud:complainant-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self, defendant, peer):
        self.results = [
            types.SimpleNamespace(all=lambda: [(ORIGIN,)]),                    # the active peers' base URLs
            types.SimpleNamespace(scalar_one_or_none=lambda: defendant),       # the defendant
            types.SimpleNamespace(scalar_one_or_none=lambda: peer),            # the origin peer's row
        ]
        self.added = []

    async def execute(self, stmt, *a, **k):
        if "federated_registry_compliance" in str(stmt):   # D6-801 wave 6: no registry is held in quarantine here
            return types.SimpleNamespace(all=lambda: [])
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        self.text = str(body)

    def json(self):
        return self.body


def _wire(monkeypatch, teg):
    """teg: a _Resp the TEG answers, or an exception it raises; a list: one answer per ask, in order."""
    answers = list(teg) if isinstance(teg, list) else None
    posted = {"teg": [], "callback": [], "keys": []}
    emitter = StrictEmitter()

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            if "/treasury/receive" in url:
                posted["teg"].append(json)
                posted["keys"].append((headers or {}).get("Idempotency-Key"))
                answer = answers.pop(0) if answers is not None else teg
                if isinstance(answer, Exception):
                    raise answer
                return answer
            posted["callback"].append(json)
            return _Resp(200, {"ok": True})

    async def _no_operator(db, peer):
        return None
    import agentvault_registry.input_validators as iv
    import agentvault_registry.services.federation_license_gate as flg
    monkeypatch.setattr(iv, "validate_webhook_url", lambda url, **kw: url)   # D6-760 added resolve=
    monkeypatch.setattr(flg, "resolve_peer_operator_did", _no_operator)
    monkeypatch.setattr(fd.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fd, "get_event_emitter", lambda: emitter)
    return posted, emitter


def _slash(monkeypatch, teg, *, balance="50"):
    posted, emitter = _wire(monkeypatch, teg)
    defendant = types.SimpleNamespace(did=DEFENDANT, liquid_balance=Decimal(balance))
    # the origin's peer row, the registry presenting the request (spiffe://peer/service/registry): a slash request
    # names its own registry as the origin (routers/federation_disputes._bind_slash_request_to_caller, 2026-10-17)
    peer = types.SimpleNamespace(name="registry-a", auto_slash_enabled=True, auto_slash_max_avt=Decimal("100"),
                                 base_url=ORIGIN, trust_domain="peer", peer_type="frame", spiffe_id=None)
    db = _Db(defendant, peer)
    req = fd.SlashRequest(settlement_id="set-1", dispute_id=7, ruling="IN_FAVOR_OF_COMPLAINANT", amount=10,
                          complainant_did=COMPLAINANT, defendant_did=DEFENDANT, origin_registry_url=ORIGIN,
                          callback_url=f"{ORIGIN}/api/v1/federation/disputes/slash-confirmation")
    out = _run(fd.receive_slash_request(req, federation_identity="spiffe://peer/service/registry", db=db))
    [settlement] = db.added
    return out, settlement, posted, emitter


def _nothing_reported_slashed(out, settlement, posted, emitter):
    assert out["status"] == "failed" and out["slashed_amount"] == 0
    assert (settlement.status, settlement.slashed_amount, settlement.slash_tx_id) == ("FAILED", 0, "")
    assert "TEG" in settlement.error_message
    assert [(c["status"], c["amount"]) for c in posted["callback"]] == [("failed", 0)]
    assert [r["amount"] for r in emitter.received] == [0]   # the DisputeSlash of a failed slash, as for an empty balance


def test_a_slash_the_teg_refused_is_no_slash(monkeypatch):
    # refused, and refused again when asked under the same key: the TEG's record holds no slash
    out, settlement, posted, emitter = _slash(monkeypatch, _Resp(400, {"detail": "Insufficient agent balance"}))
    assert len(posted["teg"]) == 2
    _nothing_reported_slashed(out, settlement, posted, emitter)
    assert "outcome not known" not in settlement.error_message


def test_a_slash_the_teg_never_answered_is_no_slash(monkeypatch):
    # the connection was never made: nothing reached the TEG, so it is not asked again
    out, settlement, posted, emitter = _slash(monkeypatch, httpx.ConnectError("teg unreachable"))
    assert len(posted["teg"]) == 1
    _nothing_reported_slashed(out, settlement, posted, emitter)
    assert "outcome not known" not in settlement.error_message


def test_a_lost_answer_is_asked_again_under_the_same_key_and_a_slash_the_teg_made_is_reported(monkeypatch):
    # the first answer timed out after the request went out; the TEG had moved the units and answers from its record
    out, settlement, posted, emitter = _slash(monkeypatch, [httpx.ReadTimeout("read timed out"),
                                                            _Resp(200, {"new_source_balance": "40"})])
    assert posted["keys"] == ["dispute-slash-set-1", "dispute-slash-set-1"]
    assert out["status"] == "slashed" and out["slashed_amount"] == 10
    assert settlement.status == "SLASHED" and settlement.slashed_amount == 10
    assert [(c["status"], c["amount"]) for c in posted["callback"]] == [("slashed", 10)]
    assert [r["amount"] for r in emitter.received] == [10]


def test_a_400_the_teg_gave_after_its_transfer_committed_is_reported_slashed(monkeypatch):
    # /treasury/receive answers 400 "Treasury receive failed" for an error after the transfer committed, and caches the
    # completed answer under the key: the second ask gets it
    out, settlement, posted, _ = _slash(monkeypatch, [
        _Resp(400, {"error_code": "SYS_INTERNAL_ERROR", "message": "Treasury receive failed"}),
        _Resp(200, {"new_source_balance": "40"})])
    assert posted["keys"] == ["dispute-slash-set-1", "dispute-slash-set-1"]
    assert out["status"] == "slashed" and settlement.status == "SLASHED" and settlement.slashed_amount == 10
    assert [(c["status"], c["amount"]) for c in posted["callback"]] == [("slashed", 10)]


def test_a_server_error_is_asked_again(monkeypatch):
    out, settlement, posted, _ = _slash(monkeypatch, [_Resp(503, {"message": "upstream"}),
                                                      _Resp(200, {"new_source_balance": "40"})])
    assert len(posted["teg"]) == 2 and out["status"] == "slashed" and settlement.status == "SLASHED"


def test_an_answer_still_lost_after_the_second_ask_is_failed_and_says_its_outcome_is_not_known(monkeypatch):
    out, settlement, posted, emitter = _slash(monkeypatch, [httpx.ReadTimeout("read timed out"),
                                                            httpx.ReadTimeout("read timed out")])
    assert len(posted["teg"]) == 2
    _nothing_reported_slashed(out, settlement, posted, emitter)
    assert "outcome not known" in settlement.error_message
    assert "outcome not known" in posted["callback"][0]["error_message"]


def test_a_second_ask_that_never_reaches_the_teg_leaves_the_first_answer_unknown(monkeypatch):
    out, settlement, posted, emitter = _slash(monkeypatch, [httpx.ReadTimeout("read timed out"),
                                                            httpx.ConnectError("teg unreachable")])
    _nothing_reported_slashed(out, settlement, posted, emitter)
    assert "ReadTimeout" in settlement.error_message and "outcome not known" in settlement.error_message


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_slash_the_teg_moved_is_reported_slashed(monkeypatch):
    out, settlement, posted, emitter = _slash(monkeypatch, _Resp(200, {"new_source_balance": "40"}))
    assert out["status"] == "slashed" and out["slashed_amount"] == 10
    assert settlement.status == "SLASHED" and settlement.slashed_amount == 10
    assert [(c["status"], c["amount"]) for c in posted["callback"]] == [("slashed", 10)]
    assert [r["amount"] for r in emitter.received] == [10]


def test_control_a_defendant_with_nothing_is_failed_without_asking_the_teg(monkeypatch):
    out, settlement, posted, emitter = _slash(monkeypatch, _Resp(200, {}), balance="0")
    assert out["status"] == "failed" and settlement.status == "FAILED" and posted["teg"] == []

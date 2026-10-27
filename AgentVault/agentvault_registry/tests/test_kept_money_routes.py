"""§REPATLANE-5 (V0606): /teg/cross-registry-transfer and /teg/transfer run under a kept attempt.

Driven through the routes themselves (their limiter unwrapped), with the attempt's store a fake Redis
(tests/test_idempotency_kept_attempt.FakeRedis) and every rail behind the route a stub that counts its calls: a held answer
is kept and answered again without a second send; an answer that proves nothing moved gives the key back; a local
transfer's batch failure says nobody knows instead of "failed"; a transfer that may be in the stream is never sent again
through the memory proxy.
"""
import ast
import asyncio
import inspect
import textwrap
import types
from decimal import Decimal

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import payout_outcome as po
from agentvault_registry.services.idempotency import cache

from tests.test_idempotency_kept_attempt import FakeRedis

A = "did:theprotocol:9cf2b8c5-50cd-4b45-9f4b-d78edf87937b"
B = "did:theprotocol:2c1f0a6e-8d3b-4e5f-9a7c-1b2d3e4f5a6b"
HELD = "FX route egress (outcome not known): nothing refunded, held for a ledger read (route_id=r1, transfer_id=t1)"


@pytest.fixture
def redis(monkeypatch):
    from agentvault_registry.background_tasks import leader
    r = FakeRedis()

    async def _get():
        return r
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.005)
    return r


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _nobody_in_quarantine(monkeypatch):
    """D6-801: the money paths read the compliance state before they move anything. The fakes here model no
    federated_registry_compliance table (the booth and the leg even run with db=None), so that read answers that this
    registry holds nobody in quarantine; tests/test_sec_quarantine_blocks_settlement.py drives the refusals."""
    from agentvault_registry.services import federation_license_gate as flg

    async def _nobody(db, registry_id):
        return None
    monkeypatch.setattr(flg, "quarantined_registry", _nobody, raising=False)


async def _none(*a, **k):
    return None


AGENT = types.SimpleNamespace(did=A, id=7, spiffe_id=None, mtls_enabled=False)


class _DB:
    # every read answers nothing: the receiver is no agent of this registry (V0639's native-agent read, `first`)
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: []),
                                     scalar_one_or_none=lambda: None, first=lambda: None)


def _common(monkeypatch):
    from agentvault_registry.services import jurisdiction, spawn_anchor

    async def _purse(db, agent, request):
        return agent, agent.did
    monkeypatch.setattr(jurisdiction, "check_jurisdiction", _none)
    monkeypatch.setattr(ti, "enforce_agent_spend", _none)
    monkeypatch.setattr(spawn_anchor, "resolve_spend_purse_agent", _purse)


def _xfer(key="k1"):
    route = inspect.unwrap(ti.cross_registry_transfer)
    req = ti.CrossRegistryTransferRequest(receiver_did=B, amount="0.5")
    return _run(route(xfer_req=req, request=types.SimpleNamespace(headers={}), backend=None, current_agent=AGENT,
                      db=_DB(), idempotency_key=key))


# ── the cross-registry route ─────────────────────────────────────────────────────────────────────────────────────────

def _fx_route(monkeypatch, answers):
    """The receiver resolves nowhere and the FX route delegates to the gateway: _fx_route_origin answers in turn."""
    _common(monkeypatch)
    calls = []

    async def _unresolved(db, did):
        return None, None

    async def _origin(db, agent, xfer_req):
        calls.append(xfer_req.receiver_did)
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _unresolved)
    monkeypatch.setattr(ti, "_fx_route_enabled", lambda: True)
    monkeypatch.setattr(ti, "_fx_route_my_gateway", lambda: {"registry_id": "registry-gw", "teg_id": "teg-layer-gw",
                                                              "router_did": "did:theprotocol:gw", "url": ""})
    monkeypatch.setattr(ti, "_fx_route_origin", _origin)
    return calls


def test_a_held_fx_route_is_answered_again_and_never_routed_twice(redis, monkeypatch):
    calls = _fx_route(monkeypatch, [HTTPException(409, detail=HELD)])
    for n in range(3):
        with pytest.raises(HTTPException) as e:
            _xfer()
        assert (e.value.status_code, e.value.detail) == (409, HELD)
        assert (cache.REPLAYED_HEADER in (e.value.headers or {})) == (n > 0)
    assert len(calls) == 1, "the payer's second and third press sent nothing"


def test_a_routed_payment_is_answered_again(redis, monkeypatch):
    done = ti.CrossRegistryTransferResponse(transfer_id="r1", status="completed", sender_did=A, receiver_did=B,
                                            amount="0.5", source_teg="teg-layer-a", target_teg="teg-layer-gw",
                                            timestamp="2026-10-12T00:00:00+00:00")
    calls = _fx_route(monkeypatch, [done])
    first, again = _xfer(), _xfer()
    assert first == done and again["transfer_id"] == "r1" and again["status"] == "completed" and len(calls) == 1


def test_a_route_refused_before_anything_moved_runs_again_under_the_same_key(redis, monkeypatch):
    calls = _fx_route(monkeypatch, [HTTPException(409, detail=f"FX route ingress refused {po.NO_FUNDS_MOVED}"),
                                    HTTPException(409, detail=HELD)])
    with pytest.raises(HTTPException) as e:
        _xfer()
    assert po.NO_FUNDS_MOVED in e.value.detail
    with pytest.raises(HTTPException) as e:
        _xfer()
    assert e.value.detail == HELD and len(calls) == 2


def test_a_route_with_no_gateway_after_all_refuses_and_gives_the_key_back(redis, monkeypatch):
    calls = _fx_route(monkeypatch, [None])
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _xfer()
        assert e.value.status_code == 400
    assert len(calls) == 2, "an origin that returned before sending anything leaves the key free"


def test_a_route_whose_origin_returned_before_sending_frees_the_key_for_a_refusal_without_a_proof(redis, monkeypatch):
    """The receiver's frame resolves but not its currency: the route is asked and returns None (no gateway after all),
    and a 409 follows. Nothing was sent, so the key is free again.

    §DOCSFIX D6-776: that refusal says so now (no funds moved), so the proof reader is taken out here: the key is freed
    because the attempt was never dispatched, whatever the refusal says."""
    _common(monkeypatch)
    monkeypatch.setattr(po, "error_moved_nothing", lambda status_code, detail: False)
    from agentvault_registry.routers import agent_locations
    calls = []

    async def _resolved(db, did):
        return "teg-layer-b", "registry-b"

    async def _bfs(db):
        return [{"name": "registry-b"}]

    async def _no_ccy(db, target_peer=None):
        return None

    async def _origin(db, agent, xfer_req):
        calls.append(1)
        return None
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolved)
    monkeypatch.setattr(agent_locations, "_compute_trusted_registries", _bfs)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _no_ccy)
    monkeypatch.setattr(ti, "_fx_route_enabled", lambda: True)
    monkeypatch.setattr(ti, "_fx_route_my_gateway", lambda: {"registry_id": "registry-gw", "teg_id": "teg-layer-gw",
                                                              "router_did": "did:theprotocol:gw", "url": ""})
    monkeypatch.setattr(ti, "_fx_route_origin", _origin)
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _xfer()
        assert e.value.status_code == 409 and po.NO_FUNDS_MOVED in e.value.detail
    assert len(calls) == 2


def _booth(monkeypatch, answers):
    """A cross-currency receiver on a peer frame: the FX booth answers in turn."""
    _common(monkeypatch)
    from agentvault_registry.routers import agent_locations
    calls = []

    async def _resolved(db, did):
        return "teg-layer-b", "registry-b"

    async def _bfs(db):
        return [{"name": "registry-b"}]

    async def _ccy(db, target_peer=None):
        return "SBXB"

    async def _swap(**kw):
        calls.append(kw["xfer_req"].receiver_did)
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolved)
    monkeypatch.setattr(agent_locations, "_compute_trusted_registries", _bfs)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "SBXA")
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_fx_enabled", lambda: True)
    monkeypatch.setattr(ti, "_fx_leaf_gateway", lambda ccy, reg: None)
    monkeypatch.setattr(ti, "_fx_cross_currency_swap", _swap)
    return calls


def test_a_held_booth_swap_is_answered_again(redis, monkeypatch):
    held = f"FX swap leg 2 (outcome not known): held for a ledger read, nothing refunded (swap s1, key=k)"
    calls = _booth(monkeypatch, [HTTPException(502, detail=held)])
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _xfer()
        assert e.value.detail == held
    assert len(calls) == 1


def _twopc(monkeypatch, statuses):
    """A same-currency receiver on a peer frame: the TEG's 2PC answers each POST with the next status."""
    _common(monkeypatch)
    from agentvault_registry.routers import agent_locations
    from agentvault_registry.services import spiffe_canonical
    posts = []

    async def _resolved(db, did):
        return "teg-layer-b", "registry-b"

    async def _bfs(db):
        return [{"name": "registry-b"}]

    async def _ccy(db, target_peer=None):
        return "SBXA"

    async def _td(*a, **k):
        return "other.example"

    async def _tok(*a, **k):
        return "tok"

    async def _url(*a, **k):
        return "https://teg-b.example:8443"

    class _Resp:
        def __init__(self, code):
            self.status_code, self.text, self.headers = code, "{}", {}

        def json(self):
            return {"detail": "Insufficient balance"} if self.status_code == 402 else {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            posts.append(url)
            return _Resp(statuses[min(len(posts), len(statuses)) - 1])

    real_sleep = asyncio.sleep

    async def _fast(*a, **k):
        await real_sleep(0)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolved)
    monkeypatch.setattr(agent_locations, "_compute_trusted_registries", _bfs)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "SBXA")
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_runtime_partner_cache", {"teg-layer-b"})
    monkeypatch.setattr(spiffe_canonical, "resolve_target_trust_domain", _td)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _tok)
    monkeypatch.setattr(ti, "_resolve_target_teg_url", _url)
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(asyncio, "sleep", _fast)
    monkeypatch.delenv("TEG_CROSS_FRAME_BACKEND", raising=False)
    return posts


def test_a_2pc_whose_teg_failed_after_it_may_have_reached_it_is_answered_again(redis, monkeypatch):
    posts = _twopc(monkeypatch, [500, 500])
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _xfer()
        assert e.value.status_code == 503
    assert len(posts) == 2, "two attempts of the first request, none of the second"


def test_a_2pc_the_teg_refused_runs_again_under_the_same_key(redis, monkeypatch):
    posts = _twopc(monkeypatch, [402])
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _xfer()
        assert e.value.status_code == 402
    assert len(posts) == 2


def test_every_send_of_the_cross_registry_route_is_marked_dispatched_first():
    """In the route's work, each call that may move money comes right after attempt.mark_dispatched() (a send before
    the mark would give its key back for a held answer)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(ti._cross_registry_transfer_run)))
    sends = {"_fx_route_origin", "_fx_route_origin_reserve", "_fx_cross_currency_swap", "_cross_registry_transfer_async"}
    seen = set()
    for node in ast.walk(tree):
        for field in ("body", "orelse"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for i, st in enumerate(stmts):
                names = {getattr(c.func, "id", None) for c in ast.walk(st) if isinstance(c, ast.Call)}
                hit = names & sends
                if not hit or hasattr(st, "body"):  # a compound statement: its own statements are walked
                    continue
                prev = ast.unparse(stmts[i - 1]) if i else ""
                assert prev == "attempt.mark_dispatched()", f"{hit} is not marked dispatched first: {prev!r}"
                seen |= hit
    assert seen == sends, f"not found: {sends - seen}"
    src = ast.unparse(tree)
    assert src.index("attempt.mark_dispatched()\n    async with httpx.AsyncClient") > 0, "the 2PC POST is marked"


# ── the local transfer route ─────────────────────────────────────────────────────────────────────────────────────────

class _Bulk:
    def __init__(self, answers):
        self.answers, self.calls = answers, 0

    async def submit(self, **kw):
        self.calls += 1
        a = self.answers[min(self.calls, len(self.answers)) - 1]
        if isinstance(a, BaseException):
            raise a
        return a


DONE = {"transaction_id": "tx1", "status": "completed", "sender_agent_id": A, "receiver_agent_id": B, "amount": "0.5",
        "new_sender_balance": "9.5", "timestamp": "2026-10-12T00:00:00+00:00"}


def _local(monkeypatch, bulk, stream=None):
    _common(monkeypatch)
    from agentvault_registry.crud import agent as crud_agent
    from agentvault_registry.services import teg_stream_proxy, transaction_fee_service

    async def _tok(*a, **k):
        return "tok"

    async def _found(db, did):
        return types.SimpleNamespace(did=did)

    class _Fees:
        async def get_fee_for_transfer(self, **k):
            return Decimal("0"), 0.0
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _tok)
    monkeypatch.setattr(crud_agent, "get_agent_by_did", _found)
    monkeypatch.setattr(transaction_fee_service, "get_transaction_fee_service", lambda: _Fees())
    monkeypatch.setattr(ti, "_get_teg_client", lambda: object())
    monkeypatch.setattr(ti, "get_teg_bulk_proxy", lambda: bulk)
    monkeypatch.setattr(ti, "_sync_balances_after_transfer", _none)
    monkeypatch.setattr(ti, "_record_transfer_ancillary", _none)
    if stream is None:
        monkeypatch.delenv("TEG_BULK_PROXY_BACKEND", raising=False)
    else:
        monkeypatch.setenv("TEG_BULK_PROXY_BACKEND", "stream")
        monkeypatch.setattr(teg_stream_proxy, "get_teg_stream_proxy", lambda: stream)


def _send(key="k1"):
    route = inspect.unwrap(ti.transfer_teg_tokens)
    return _run(route(transfer_request=ti.TEGTransferRequest(receiver_agent_id=B, amount="0.5"),
                      request=types.SimpleNamespace(headers={}), current_agent=AGENT, db=_DB(), idempotency_key=key))


def test_a_local_transfer_is_answered_again(redis, monkeypatch):
    bulk = _Bulk([DONE])
    _local(monkeypatch, bulk)
    first, again = _send(), _send()
    assert first.transaction_id == "tx1" and again["transaction_id"] == "tx1" and bulk.calls == 1


def test_a_batch_the_teg_failed_says_nobody_knows_and_is_answered_again(redis, monkeypatch):
    bulk = _Bulk([ValueError("TEG bulk endpoint returned 500: Internal Server Error")])
    _local(monkeypatch, bulk)
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _send()
        assert e.value.status_code == 503 and po.OUTCOME_UNKNOWN in e.value.detail
    assert bulk.calls == 1


@pytest.mark.parametrize("err", [ValueError("Insufficient balance: have 0.1"), ValueError("Sender suspended: x"),
                                 ValueError("TEG bulk endpoint returned 403: forbidden")])
def test_the_tegs_refusal_of_a_local_transfer_gives_the_key_back(redis, monkeypatch, err):
    bulk = _Bulk([err])
    _local(monkeypatch, bulk)
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _send()
        assert e.value.status_code in (400, 403)
    assert bulk.calls == 2


def test_a_timed_out_batch_says_nobody_knows_and_one_never_sent_says_nothing_moved(redis, monkeypatch):
    import httpx
    bulk = _Bulk([httpx.ReadTimeout("read timed out")])
    _local(monkeypatch, bulk)
    with pytest.raises(HTTPException) as e:
        _send()
    assert e.value.status_code == 503 and po.OUTCOME_UNKNOWN in e.value.detail
    never = _Bulk([httpx.ConnectError("refused"), DONE])
    _local(monkeypatch, never)
    with pytest.raises(HTTPException) as e:
        _send(key="k2")
    assert po.NO_FUNDS_MOVED in e.value.detail
    assert _send(key="k2").transaction_id == "tx1" and never.calls == 2


class _Stream:
    def __init__(self, err):
        self.err, self.calls = err, 0

    async def submit(self, **kw):
        self.calls += 1
        raise self.err


def test_a_transfer_that_may_be_in_the_stream_is_never_sent_again_through_memory(redis, monkeypatch):
    from agentvault_registry.services.teg_stream_proxy import StreamUnavailableError
    bulk, stream = _Bulk([DONE]), _Stream(StreamUnavailableError("No result within 30.0s (req_id=x)", enqueued=True))
    _local(monkeypatch, bulk, stream)
    with pytest.raises(HTTPException) as e:
        _send()
    assert e.value.status_code == 503 and po.OUTCOME_UNKNOWN in e.value.detail
    assert bulk.calls == 0, "the memory proxy was not asked to send it a second time"
    with pytest.raises(HTTPException):
        _send()
    assert stream.calls == 1, "and the same key answers again without a send"


def test_a_transfer_the_stream_never_took_falls_back_to_memory(redis, monkeypatch):
    from agentvault_registry.services.teg_stream_proxy import StreamUnavailableError
    bulk, stream = _Bulk([DONE]), _Stream(StreamUnavailableError("Redis or stream proxy not available"))
    _local(monkeypatch, bulk, stream)
    assert _send().transaction_id == "tx1" and bulk.calls == 1 and stream.calls == 1


def test_the_stream_says_which_failures_may_be_in_the_stream():
    src = inspect.getsource(__import__("agentvault_registry.services.teg_stream_proxy", fromlist=["x"]))
    assert 'StreamUnavailableError("Stream proxy stopping", enqueued=True)' in src
    assert "enqueued=not isinstance(e, aioredis.ResponseError)" in src
    assert 'f"No result within {STREAM_SETTLE_TIMEOUT_S}s (req_id={req_id})", enqueued=True' in src
    assert 'raise StreamUnavailableError("Redis or stream proxy not available")' in src


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

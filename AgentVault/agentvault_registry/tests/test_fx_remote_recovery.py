"""§FXSELFHEAL — self-healing recovery of FX routes parked at a REMOTE frame's @fx_router.

The class this encodes (recovered by hand 2026-08-10, 3,258 routes / ~1.39M units): a
post-conversion egress failure parks converted funds at the DESTINATION frame's @fx_router.
The ORIGIN frame owns the dead-letter row but genuinely cannot refund it — the money is on
the far side. Until now clearing the class required a human running scratchpad/fx_recover.py.

Three guards, each earned that day:
  1. claim CAS on the origin row — the sweep rail has NO per-route idempotency, and a PEER
     session was observed sweeping ~219 routes concurrently with the manual runbook.
  2. local delivery ledger — TWO routes had already been paid, their egress COMPLETING 4-6 s
     AFTER the origin wrote its dead-letter row. An age gate cannot see that class.
  3. single-writer Redis lock — and it FAILS CLOSED, because this path moves money (unlike
     the §FXEGRESS breaker, which only ever refuses).

These tests drive the keeper against fakes so they run offline like the rest of the suite.
Each guard has a paired mutation check in the mutation-verification block at the bottom of
this docstring's companion run (see SESSION_LOG_2026-08-10): neutering any one guard must
turn at least one test RED, or the test is measuring nothing.
"""
import os
import pytest

from agentvault_registry.background_tasks import fx_router_keeper as krp


# ── fakes ────────────────────────────────────────────────────────────────────────────
class FakeRedis:
    def __init__(self, *, broken: bool = False, held_by: str | None = None):
        self.store: dict = {}
        self.broken = broken
        if held_by:
            self.store[krp._RR_LOCK_KEY] = held_by

    async def set(self, k, v, nx=False, ex=None):
        if self.broken:
            raise RuntimeError("redis down")
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def delete(self, k):
        self.store.pop(k, None)
        return 1


class FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakePeerClient:
    """Stands in for the origin frame. Records every call so the test can assert on the
    ORDER of operations (claim before sweep, record before resolve)."""

    def __init__(self, rows, *, claim_status=200):
        self.rows = rows
        self.claim_status = claim_status
        self.calls: list = []
        self.resolves: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.calls.append(("list", params))
        return FakeResp(200, {"rows": self.rows})

    async def post(self, url, json=None):
        if url.endswith("parked-claim"):
            self.calls.append(("claim", json["route_id"]))
            return FakeResp(self.claim_status, {"claimed": True})
        if url.endswith("parked-resolve"):
            self.resolves.append(dict(json))
            self.calls.append(("resolve", json["route_id"], json["outcome"],
                               json.get("resolution_tx")))
            return FakeResp(200, {"resolved": True})
        raise AssertionError(f"unexpected POST {url}")


class FakePeer:
    name = "frame-b"
    base_url = "http://frame-b-registry:8100"


@pytest.fixture
def keeper(monkeypatch):
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MODE", "keeper")
    monkeypatch.setenv("FX_ROUTER_DID", "did:theprotocol:router-local")
    monkeypatch.setenv("FX_ENABLED", "true")
    k = krp.FxRouterKeeper()
    return k


def _wire(monkeypatch, keeper, *, rows, redis, delivered=None, deliver_result=None,
          client_holder=None, held=None):
    """Patch the keeper's collaborators. `delivered` is the local delivery ledger, `held` this frame's own held dead
    letters by route (§REPATLANE-3: a route whose egress from here may already have paid)."""
    from agentvault_registry.routers import teg_integration as ti

    client = FakePeerClient(rows)
    if client_holder is not None:
        client_holder.append(client)

    async def _get_redis():
        return redis

    monkeypatch.setattr(krp, "get_redis", _get_redis, raising=False)
    monkeypatch.setattr("agentvault_registry.background_tasks.leader.get_redis",
                        _get_redis, raising=False)

    async def _peers(self, db):
        return [FakePeer()]

    async def _client(self, peer):
        return client, "http://frame-b-registry:8100"

    monkeypatch.setattr(krp.FxRouterKeeper, "_origin_peers", _peers, raising=False)
    monkeypatch.setattr(krp.FxRouterKeeper, "_peer_client", _client, raising=False)

    recorded: list = []
    held_rows: list = []
    client.held_rows = held_rows

    async def _already(db, rid):
        if delivered and rid in delivered:
            return delivered[rid]
        return None

    async def _record(db, **kw):
        recorded.append(kw)

    held = held if held is not None else {}

    async def _held(db, rid):
        return held.get(rid)

    async def _hold(db, **kw):
        # the recorder: one row per route; a held phase is what GUARD 2b reads on the next pass
        held_rows.append(kw)
        held.setdefault(kw["route_id"], {"route_id": kw["route_id"], "phase": kw["phase"], "status": "pending"})

    monkeypatch.setattr(ti, "_fx_route_already_delivered", _already, raising=False)
    monkeypatch.setattr(ti, "_fx_route_held_here", _held, raising=False)
    monkeypatch.setattr(ti, "_record_fx_dead_letter", _hold, raising=False)
    monkeypatch.setattr(ti, "_record_fx_delivery", _record, raising=False)
    monkeypatch.setattr(ti, "_fx_route_local_router_did",
                        lambda: "did:theprotocol:router-local", raising=False)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "BVT", raising=False)

    async def _deliver(self, db, router_agent, router_did, rid, receiver, amount):
        if deliver_result is not None:
            return deliver_result
        return (True, None, amount, f"tx-{rid[:6]}")

    monkeypatch.setattr(krp.FxRouterKeeper, "_deliver_one", _deliver, raising=False)
    return client, recorded


class FakeScalar:
    def __init__(self, val):
        self._val = val

    def scalar_one_or_none(self):
        return self._val


class FakeDb:
    async def execute(self, *a, **kw):
        return FakeScalar(object())  # the @fx_router agent row


ROW = {"route_id": "aaaaaaaa-1111-2222-3333-444444444444",
       "receiver_did": "did:theprotocol:payee-1", "amount": "10.5", "currency": "BVT"}


# ── the guards ───────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_happy_path_claims_before_sweeping_and_records_before_resolving(monkeypatch, keeper):
    """Order is the safety property: claim → deliver → record locally → resolve."""
    client, recorded = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis())
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["recovered"] == 1, stats
    kinds = [c[0] for c in client.calls]
    assert kinds == ["list", "claim", "resolve"], client.calls
    assert client.calls[-1][2] == "swept"
    assert recorded and recorded[0]["kind"] == "recovery"


@pytest.mark.asyncio
async def test_already_delivered_route_is_marked_delivered_and_never_swept(monkeypatch, keeper):
    """GUARD 2 — the photo-finish class. Two live cases on 2026-08-10; sweeping either
    would have paid the receiver twice."""
    delivered = {ROW["route_id"]: {"tx_id": "orig-tx-9", "kind": "egress",
                                   "receiver_did": ROW["receiver_did"], "amount": "10.5"}}
    calls: list = []

    async def _must_not_run(self, *a, **kw):
        calls.append("DELIVERED-AGAIN")
        return (True, None, "10.5", "double-pay")

    client, recorded = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis(),
                             delivered=delivered)
    monkeypatch.setattr(krp.FxRouterKeeper, "_deliver_one", _must_not_run, raising=False)

    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert calls == [], "delivery was attempted on an already-paid route (DOUBLE PAY)"
    assert stats["already_delivered"] == 1 and stats["recovered"] == 0, stats
    outcome = [c for c in client.calls if c[0] == "resolve"][0]
    assert outcome[2] == "delivered" and outcome[3] == "orig-tx-9"


@pytest.mark.asyncio
async def test_delivery_guard_failure_fails_closed(monkeypatch, keeper):
    """A guard that cannot answer must STOP the sweep, not wave it through."""
    from agentvault_registry.routers import teg_integration as ti
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis())

    async def _boom(db, rid):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(ti, "_fx_route_already_delivered", _boom, raising=False)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["recovered"] == 0 and stats["skipped"] == 1, stats
    assert not any(c[0] == "claim" for c in client.calls), "claimed despite a blind guard"


@pytest.mark.asyncio
async def test_a_route_this_frame_holds_is_never_claimed_nor_re_delivered(monkeypatch, keeper):
    """GUARD 2b (§REPATLANE-3) — this frame's own two-phase egress for the route may already have paid (its outcome
    was not known, so it holds the route): re-delivering could pay twice. Skipped before the claim."""
    calls: list = []

    async def _must_not_run(self, *a, **kw):
        calls.append("DELIVERED-AGAIN")
        return (True, None, "10.5", "double-pay")

    held = {ROW["route_id"]: {"route_id": ROW["route_id"], "phase": "egress_2pc_unknown", "status": "pending"}}
    client, recorded = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis(), held=held)
    monkeypatch.setattr(krp.FxRouterKeeper, "_deliver_one", _must_not_run, raising=False)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert calls == [], "a held route was re-delivered (DOUBLE PAY)"
    assert stats["held"] == 1 and stats["recovered"] == 0, stats
    assert [c[0] for c in client.calls] == ["list"], "a held route is not even claimed: the origin row stays as it is"
    assert recorded == []


@pytest.mark.asyncio
async def test_the_held_route_guard_fails_closed(monkeypatch, keeper):
    from agentvault_registry.routers import teg_integration as ti
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis())

    async def _boom(db, rid):
        raise RuntimeError("dead letters unreadable")

    monkeypatch.setattr(ti, "_fx_route_held_here", _boom, raising=False)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["recovered"] == 0 and stats["skipped"] == 1, stats
    assert not any(c[0] == "claim" for c in client.calls), "claimed despite a blind guard"


@pytest.mark.asyncio
async def test_a_route_already_delivered_is_marked_delivered_even_while_held(monkeypatch, keeper):
    """The delivery ledger wins: a route this frame paid is resolved as delivered, whatever else it holds."""
    delivered = {ROW["route_id"]: {"tx_id": "orig-tx-7", "kind": "egress",
                                   "receiver_did": ROW["receiver_did"], "amount": "10.5"}}
    held = {ROW["route_id"]: {"route_id": ROW["route_id"], "phase": "egress_2pc_unknown", "status": "pending"}}
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis(), delivered=delivered, held=held)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["already_delivered"] == 1 and stats["held"] == 0, stats
    assert [c for c in client.calls if c[0] == "resolve"][0][2:] == ("delivered", "orig-tx-7")


@pytest.mark.asyncio
async def test_lost_claim_race_skips_the_row(monkeypatch, keeper):
    """GUARD 1 — a 409 means someone else owns it (peer keeper or the manual runbook)."""
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis())
    client.claim_status = 409
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["recovered"] == 0 and stats["skipped"] == 1, stats
    assert not any(c[0] == "resolve" for c in client.calls)


def _le(text, nothing_moved):
    from agentvault_registry.routers import teg_integration as ti
    return ti._LegError(text, nothing_moved=nothing_moved)


@pytest.mark.asyncio
async def test_failed_delivery_releases_for_retry(monkeypatch, keeper):
    # §REPATLANE-3: a delivery that provably never ran (the leg's own verdict) is released for the next pass, as before
    client, recorded = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis(),
                             deliver_result=(False, _le("local TEG unreachable: ConnectError", True), None, None))
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["released"] == 1 and stats["recovered"] == 0, stats
    assert [c for c in client.calls if c[0] == "resolve"][0][2] == "released"
    assert client.held_rows == [] and stats["held_now"] == 0
    assert recorded == [], "a failed delivery must not write a delivery ledger row"


@pytest.mark.asyncio
@pytest.mark.parametrize("err", [lambda: _le("2pc leg 504: gateway timeout", False),
                                 lambda: "an error nobody classified"])
async def test_a_re_delivery_whose_outcome_is_not_known_is_held_here_and_never_sent_again(monkeypatch, keeper, err):
    """§REPATLANE-3 — the re-delivery may have paid the receiver: sending it again under a fresh 2PC transfer id could
    pay twice. This frame holds the route (redelivery_unknown, the transfer named) and the next pass skips it."""
    sends: list = []

    async def _deliver(self, db, router_agent, router_did, rid, receiver, amount):
        sends.append(rid)
        return (False, err(), "0", "tid-redeliver-1")

    client, recorded = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis())
    monkeypatch.setattr(krp.FxRouterKeeper, "_deliver_one", _deliver, raising=False)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["held_now"] == 1 and stats["released"] == 1, stats
    (h,) = client.held_rows
    assert h["phase"] == "redelivery_unknown" and h["receiver_did"] == ROW["receiver_did"]
    assert "tid-redeliver-1" in h["note"] and h["route_id"] == ROW["route_id"]
    assert "outcome not known" in client.resolves[-1]["error"]
    # the next pass: the origin offers the row again (released = pending) and this frame skips it, unclaimed
    stats2 = await keeper._process_remote_parked(FakeDb(), None)
    assert sends == [ROW["route_id"]], "the route was sent a second time (DOUBLE PAY)"
    assert stats2["held"] == 1 and stats2["recovered"] == 0, stats2
    assert [c[0] for c in client.calls].count("claim") == 1


@pytest.mark.asyncio
async def test_a_hold_that_did_not_land_leaves_the_origin_row_claimed(monkeypatch, keeper):
    """If the hold cannot be written, releasing the row would let the next pass send it again: it stays claimed."""
    from agentvault_registry.routers import teg_integration as ti
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis(),
                      deliver_result=(False, _le("2pc leg 500: internal error", False), "0", "tid-x"))

    async def _lost(db, **kw):
        return None   # the write failed (the recorder logs it and never raises)

    monkeypatch.setattr(ti, "_record_fx_dead_letter", _lost, raising=False)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats["released"] == 0 and stats["skipped"] == 1 and stats["held_now"] == 0, stats
    assert not any(c[0] == "resolve" for c in client.calls), "released a route nothing holds"


@pytest.mark.asyncio
async def test_a_receiver_that_cannot_be_resolved_is_a_refusal_that_moved_nothing(monkeypatch, keeper):
    from agentvault_registry.routers import teg_integration as ti

    async def _nowhere(db, did):
        return None, None

    class _NoAgent:
        async def execute(self, *a, **kw):
            return FakeScalar(None)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _nowhere, raising=False)
    ok, err, _c, _t = await keeper._deliver_one(_NoAgent(), object(), "did:theprotocol:router-local",
                                                ROW["route_id"], ROW["receiver_did"], "10.5")
    assert ok is False and ti._leg_moved_nothing(err) and "cannot resolve receiver" in err


@pytest.mark.asyncio
async def test_single_writer_lock_blocks_a_second_keeper(monkeypatch, keeper):
    """GUARD 3 — the concurrent-sweeper lesson, encoded."""
    client, _ = _wire(monkeypatch, keeper, rows=[ROW],
                      redis=FakeRedis(held_by="other-frame"))
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert "skipped" in stats and "another writer" in str(stats["skipped"]), stats
    assert client.calls == [], "worked the queue without holding the writer lock"


@pytest.mark.asyncio
async def test_no_redis_fails_closed(monkeypatch, keeper):
    """No lock ⇒ no single-writer guarantee ⇒ refuse. This path MOVES MONEY, so unlike the
    §FXEGRESS breaker it must fail CLOSED."""
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=None)

    async def _none():
        return None

    monkeypatch.setattr(krp, "get_redis", _none, raising=False)
    monkeypatch.setattr("agentvault_registry.background_tasks.leader.get_redis",
                        _none, raising=False)
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert "redis unavailable" in str(stats.get("skipped", "")), stats
    assert client.calls == []


@pytest.mark.asyncio
async def test_mode_off_is_byte_inert(monkeypatch, keeper):
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MODE", "off")
    client, _ = _wire(monkeypatch, keeper, rows=[ROW], redis=FakeRedis())
    stats = await keeper._process_remote_parked(FakeDb(), None)

    assert stats == {"enabled": False, "mode": "off"}, stats
    assert client.calls == []


# ── gating helpers ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode,keeper_on", [
    ("off", False), ("endpoints", False), ("keeper", True), ("on", True), ("", False),
])
def test_mode_gate_matrix(monkeypatch, mode, keeper_on):
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MODE", mode)
    assert krp._rr_keeper_enabled() is keeper_on


def test_min_age_floors_at_300s(monkeypatch):
    """The photo-finish class is seconds wide; the floor keeps a misconfiguration from
    handing the keeper rows whose egress may still be in flight."""
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MIN_AGE_SEC", "5")
    assert krp._rr_min_age_sec() == 300
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MIN_AGE_SEC", "not-a-number")
    assert krp._rr_min_age_sec() == 900


def test_batch_is_bounded(monkeypatch):
    monkeypatch.setenv("FX_REMOTE_RECOVERY_BATCH", "9999")
    assert krp._rr_batch() == 100
    monkeypatch.setenv("FX_REMOTE_RECOVERY_BATCH", "0")
    assert krp._rr_batch() == 1


def test_worker_runs_when_only_remote_recovery_is_enabled(monkeypatch):
    """A frame can hold OTHER frames' parked funds while its own float manager is off —
    frame-c is exactly that shape, so the worker must not be gated on the liquidity flag."""
    monkeypatch.setenv("FX_ROUTER_DID", "did:theprotocol:router-local")
    monkeypatch.setenv("FX_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTER_KEEPER_ENABLED", "false")
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MODE", "keeper")
    assert krp.FxRouterKeeper()._should_run() is True
    monkeypatch.setenv("FX_REMOTE_RECOVERY_MODE", "off")
    assert krp.FxRouterKeeper()._should_run() is False


@pytest.mark.asyncio
async def test_the_parked_listing_names_each_rows_origin(monkeypatch):
    """§REPATLANE-3 — the far keeper records a route it holds under the payer the origin parked it for, so the
    listing carries origin_did beside the receiver (an older origin omits it; the keeper then names the peer)."""
    import datetime
    import inspect
    from agentvault_registry.routers import federation_sync as fs
    seen: list = []

    class _Rows:
        def mappings(self):
            return self

        def all(self):
            return [{"route_id": ROW["route_id"], "receiver_did": ROW["receiver_did"], "amount": "10.5",
                     "currency": "BVT", "origin_did": "did:theprotocol:payer-1",
                     "created_at": datetime.datetime(2026, 10, 12, 12, 0, tzinfo=datetime.timezone.utc)}]

    class _Db:
        async def execute(self, stmt, params=None):
            seen.append(str(stmt))
            return _Rows()

    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(fs, "_fxsh_require_enabled", lambda: None)
    monkeypatch.setattr(fs, "_fxsh_validate_router", _ok)
    listing = inspect.unwrap(fs.fx_parked_at)
    out = await listing(router_did="did:theprotocol:router-local", min_age_sec=900, limit=25, db=_Db(),
                        spiffe_id="spiffe://frame-b/service/registry")
    assert out["rows"][0]["origin_did"] == "did:theprotocol:payer-1"
    assert "origin_did" in seen[0] and "phase = 'post_conversion_remote'" in seen[0]

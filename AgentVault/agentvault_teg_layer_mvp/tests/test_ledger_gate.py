"""§LEDGERGATE (2026-10-11) — no new value movement while the ledger cannot record it.

His ask 2026-10-11: "we also have to make actions fail that have event emissions while cqrs outbox to evenstore is
unhealthy". Pinned here:
  1. the census: every write route of the TEG is in exactly one class (starting, finishing, decided in the handler,
     moving no value), and every classified row names a route the TEG serves. A new write route fails this until
     someone decides what it is;
  2. the health tracker: an outage escalates at once and comes down only below half of each threshold for two cycles;
     a group the store REJECTS (422) is stuck, never an outage, so one bad event cannot hold every transfer behind it;
  3. the verdict: the leader's when published; unknown in a worker's first minute; after that the journal's own state,
     never "healthy by silence";
  4. the gate: shadow counts and refuses nothing; enforce answers 503 + Retry-After with the TEG's RFC 7807 body and
     the sentence; finishing work, readers and a TEG without the outbox always pass.

RED control: run with PYTHONPATH naming the tree before the fix: core/ledger_gate.py does not exist there.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import textwrap

import pytest

for _k, _v in (("AVTP_SYSTEM_API_KEY", "x" * 40), ("TEG_TOKEN_SIGNING_KEY", "y" * 64)):
    os.environ.setdefault(_k, _v)  # the two secrets Settings refuses to start without (dummies, as CI's)


def _ast_of(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))

from teg_core_service.core import ledger_gate as lg  # noqa: E402
from teg_core_service.core import ledger_health as lh  # noqa: E402


# ------------------------------------------------------------------------------------------------ 1. the census
def _walk(routes, prefix=""):
    """(method, path) of every route, through FastAPI's included-router wrappers (0.14x keeps them)."""
    for r in routes:
        orig = getattr(r, "original_router", None)
        if orig is not None:
            ctx = getattr(r, "include_context", None)
            yield from _walk(orig.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            continue
        path, methods = getattr(r, "path", None), getattr(r, "methods", None)
        if path and methods:
            for m in methods:
                yield m.upper(), prefix + path


def _write_routes():
    from teg_core_service.main import app
    from teg_core_service.api.cross_teg_router import router as cross_teg_router  # included in the lifespan
    rows = set(_walk(app.routes)) | set(_walk(cross_teg_router.routes))
    return {(m, lg._norm(p)) for (m, p) in rows if m in lg.WRITE_METHODS}


def test_every_write_route_is_in_exactly_one_class():
    seen = {}
    for cls, m, p in lg.all_rows():
        key = (m, lg._norm(p))
        assert key not in seen, f"{m} {p} is in two classes: {seen[key]} and {cls}"
        seen[key] = cls
    served = _write_routes()
    assert len(served) >= 80, f"the census read only {len(served)} write routes: the walk is broken, not the TEG"
    missing = sorted(served - set(seen))
    stale = sorted(set(seen) - served)
    assert not missing, ("write routes in no class (decide: does it START a value movement, FINISH one, decide in "
                         f"its handler, or move nothing?): {missing}")
    assert not stale, f"classified rows that name no route this TEG serves: {stale}"


def test_the_gate_is_the_innermost_middleware():
    """Added first, so it runs last: the Host check runs before it and its 503 passes back through the security headers."""
    from teg_core_service.main import app
    classes = [m.cls for m in app.user_middleware]
    assert classes and classes[-1] is lg.LedgerGate, [getattr(c, "__name__", c) for c in classes]


def test_the_movers_decide_in_the_handler_and_call_the_gate():
    from teg_core_service.api.v1 import endpoints_exchange_admin as ex, endpoints_treasury as tr
    for fn, account in ((ex.exchange_move, "EXCHANGE_ESCROW_DID"), (tr.fx_move, "_FX_RESERVE_DID")):
        tree = _ast_of(fn)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "require_ledger"]
        assert len(calls) == 1, f"{fn.__name__} calls require_ledger {len(calls)} times"
        guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and any(isinstance(c, ast.Name) and c.id == account for c in ast.walk(n.test))
                  and any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "require_ledger"
                          for c in ast.walk(n))]
        assert guards, f"{fn.__name__}: the gate is not behind `to_did == {account}` (money INTO the account starts)"


def test_the_welcome_bonus_cannot_come_back_unclassified():
    """/agent/initialize is NO_VALUE because its welcome bonus reads a setting the TEG does not define."""
    from teg_core_service.core.config import Settings
    fields = getattr(Settings, "model_fields", None) or getattr(Settings, "__fields__", {})
    assert "welcome_bonus_amount" not in fields, (
        "Settings gained welcome_bonus_amount: /agent/initialize now writes a balance, so it must move from "
        "NO_VALUE to STARTING in core/ledger_gate.py")


def test_starting_route_matching():
    assert lg.starting_route("POST", "/api/v1/token/transfer") == "/api/v1/token/transfer"
    assert lg.starting_route("POST", "/api/v1/token/transfer/") == "/api/v1/token/transfer"
    assert lg.starting_route("POST", "/api/v1/cross-teg/prepare/abc-123") == "/api/v1/cross-teg/prepare/{transfer_id}"
    assert lg.starting_route("POST", "/api/v1/disputes/42/resolve") == "/api/v1/disputes/{dispute_id}/resolve"
    assert lg.starting_route("GET", "/api/v1/token/transfer") is None, "a reader is never gated"
    assert lg.starting_route("POST", "/api/v1/cross-teg/commit/abc") is None, "finishing work is not starting"
    assert lg.starting_route("POST", "/api/v1/cross-teg/prepare/a/b") is None, "a parameter is one segment"
    assert lg.starting_route("POST", "/api/v1/admin/exchange/move") is None, "the movers decide in the handler"
    assert lg.starting_route("POST", "/api/v1/token/transferx") is None


# ------------------------------------------------------------------------------------------------ 2. the tracker
def _t(**kw):
    base = dict(unhealthy_age_s=30.0, unhealthy_backlog=5000, unhealthy_failed_cycles=3, degraded_age_s=10.0,
                degraded_backlog=500, recovery_cycles=2)
    base.update(kw)
    return lh.Thresholds(**base)


class _Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def _tracker():
    c = _Clock()
    return lh.HealthTracker(thresholds=_t(), interval_s=5.0, clock=c), c


def _ok(**kw):
    d = dict(waiting_rows=0, oldest_waiting_age_s=None, attempted=1, emitted=1)
    d.update(kw)
    return lh.Observation(**d)


def test_failure_classes():
    for s in (413, 415, 422):
        assert lh.classify_failure(s) == "rejected", s
    for s in (None, 400, 401, 403, 404, 405, 408, 429, 500, 502, 503, 504, 0, 999):
        assert lh.classify_failure(s) == "unreachable", s


def test_three_unreachable_cycles_make_it_unhealthy_and_it_comes_down_slowly():
    h, c = _tracker()
    down = lh.Observation(waiting_rows=3, oldest_waiting_age_s=6.0, attempted=2, emitted=0, unreachable=2)
    assert down.failed_cycle
    assert h.observe(down)["state"] == lh.DEGRADED          # one failed cycle: said, not refused
    assert h.observe(down)["state"] == lh.DEGRADED
    snap = h.observe(down)
    assert (snap["state"], snap["reason"]) == (lh.UNHEALTHY, "store_unreachable")
    assert snap["retry_after_s"] == 30
    # the store answers again: one clear cycle is not enough
    assert h.observe(_ok(waiting_rows=1, oldest_waiting_age_s=1.0))["state"] == lh.UNHEALTHY
    s2 = h.observe(_ok(waiting_rows=1, oldest_waiting_age_s=1.0))
    assert s2["state"] == lh.OK, "two cycles clear of every threshold bring it down"


def test_an_old_waiting_row_is_unhealthy_even_while_the_store_drains():
    """Backpressure: the store takes rows but not fast enough; a row waiting past 30 s refuses new work."""
    h, c = _tracker()
    s = h.observe(_ok(waiting_rows=900, oldest_waiting_age_s=31.0, attempted=200, emitted=200))
    assert (s["state"], s["reason"]) == (lh.UNHEALTHY, "waiting")
    assert 10 <= s["retry_after_s"] <= 120


def test_the_backlog_ceiling():
    h, _ = _tracker()
    assert h.observe(_ok(waiting_rows=5001, oldest_waiting_age_s=2.0))["reason"] == "backlog"
    h2, _ = _tracker()
    s = h2.observe(_ok(waiting_rows=501, oldest_waiting_age_s=2.0))
    assert (s["state"], s["reason"]) == (lh.DEGRADED, "backlog")


def test_hysteresis_holds_between_half_and_the_threshold():
    h, _ = _tracker()
    h.observe(_ok(waiting_rows=10, oldest_waiting_age_s=40.0))
    for _ in range(5):  # 20 s is under the 30 s threshold but over its half: it stays unhealthy
        assert h.observe(_ok(waiting_rows=10, oldest_waiting_age_s=20.0))["state"] == lh.UNHEALTHY
    h.observe(_ok(waiting_rows=10, oldest_waiting_age_s=14.0))
    s = h.observe(_ok(waiting_rows=10, oldest_waiting_age_s=12.0))
    assert s["state"] == lh.DEGRADED, "below half of the unhealthy age, still over the degraded age"


def test_a_rejected_group_is_stuck_not_an_outage():
    """One malformed event retried every cycle must not refuse every transfer of the TEG."""
    h, _ = _tracker()
    poison = lh.Observation(waiting_rows=0, oldest_waiting_age_s=None, stuck_rows=3, oldest_stuck_age_s=900.0,
                            attempted=1, emitted=0, rejected=1, unreachable=0)
    assert not poison.failed_cycle
    for _ in range(10):
        s = h.observe(poison)
        assert (s["state"], s["reason"]) == (lh.DEGRADED, "rejected_group")
    assert s["failed_cycles"] == 0


def test_nothing_to_emit_tests_nothing_unless_nothing_waits():
    h, _ = _tracker()
    down = lh.Observation(waiting_rows=1, oldest_waiting_age_s=6.0, attempted=1, emitted=0, unreachable=1)
    h.observe(down)
    h.observe(down)
    s = h.observe(lh.Observation(waiting_rows=1, oldest_waiting_age_s=7.0))  # rows arrived after the select
    assert s["failed_cycles"] == 2, "an idle cycle with work waiting is neither proof of health nor of failure"
    s = h.observe(lh.Observation())
    assert s["failed_cycles"] == 0, "nothing waits, so nothing is failing (the gate never stays shut on nothing)"


def test_snapshot_round_trips_through_redis_encoding():
    h, _ = _tracker()
    snap = h.observe(_ok())
    body = lh.decode(lh.encode(snap, "eu", "w1"))
    assert body["state"] == lh.OK and body["teg_id"] == "eu" and body["worker"] == "w1"
    assert lh.decode("not json") is None and lh.decode(json.dumps({"state": "fine"})) is None
    assert lh.key_ttl_s(5) == 15 and lh.key_ttl_s(10) == 30
    assert lh.health_key("eu") == "teg:eu:ledger_health"
    assert lh.stuck_param([None, 7, 7, 3]) == [-1, 3, 7]


def test_thresholds_from_env_refuse_nonsense():
    t = lh.Thresholds.from_env({"TEG_LEDGER_UNHEALTHY_AGE_S": "45", "TEG_LEDGER_DEGRADED_BACKLOG": "-3",
                                "TEG_LEDGER_RECOVERY_CYCLES": "x"})
    assert t.unhealthy_age_s == 45.0 and t.degraded_backlog == 500 and t.recovery_cycles == 2


# ------------------------------------------------------------------------------------------------ 3. the verdict
class _FakeRedis:
    def __init__(self, value=None, raises=False):
        self.value, self.raises = value, raises

    async def get(self, key):
        if self.raises:
            raise ConnectionError("down")
        return self.value


def _run(coro):
    """A private loop, closed after: asyncio.run() would unset the thread's loop for whatever runs next."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_the_leaders_verdict_is_read_when_published():
    h, _ = _tracker()
    raw = lh.encode(h.observe(_ok(waiting_rows=6000, oldest_waiting_age_s=2.0)), lg._teg_id(), "w")
    v = _run(lg.read_verdict(now=lg._BOOTED_AT + 999, redis=_FakeRedis(raw)))
    assert (v["state"], v["source"]) == (lh.UNHEALTHY, "leader")


def test_a_missing_verdict_is_unknown_only_in_the_first_minute():
    v = _run(lg.read_verdict(now=lg._BOOTED_AT + 5, redis=_FakeRedis(None)))
    assert v["state"] == "unknown"

    async def calm():
        return 2, 1.5

    async def behind():
        return 7, 95.0

    async def broken():
        raise OSError("no db")

    later = lg._BOOTED_AT + lg.BOOT_GRACE_S + 1
    v = _run(lg.read_verdict(now=later, redis=_FakeRedis(None), measure=calm))
    assert (v["state"], v["source"]) == (lh.DEGRADED, "journal"), "a leader gap with nothing waiting passes"
    v = _run(lg.read_verdict(now=later, redis=_FakeRedis(raises=True), measure=behind))
    assert (v["state"], v["source"]) == (lh.UNHEALTHY, "journal"), "a dead leader with work waiting refuses"
    v = _run(lg.read_verdict(now=later, redis=None, use_redis_client=False, measure=broken))
    assert v["state"] == lh.UNHEALTHY and v["reason"].startswith("unmeasured"), "never healthy by silence"


def test_decisions():
    assert lg.decide("off", False, lh.UNHEALTHY) == "pass_off"
    assert lg.decide("enforce", True, lh.UNHEALTHY) == "pass_off", "a TEG without the outbox is inert"
    assert lg.decide("shadow", False, lh.UNHEALTHY) == "would_refuse"
    assert lg.decide("enforce", False, lh.UNHEALTHY) == "refuse"
    assert lg.decide("enforce", False, lh.DEGRADED) == "pass_degraded"
    assert lg.decide("enforce", False, lh.OK) == "pass"
    assert lg.decide("enforce", False, "unknown") == "pass_unknown"
    assert lg.resolve_mode("ENFORCE") == "enforce" and lg.resolve_mode(None) == "off"
    assert lg.resolve_mode("enfroce") == "shadow", "a typo measures, it does not enforce and it does not go dark"


# ------------------------------------------------------------------------------------------------ 4. the gate
async def _call(gate, method, path):
    sent = []
    reached = []

    async def downstream(scope, receive, send):
        reached.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    g = lg.LedgerGate(downstream) if gate is None else gate(downstream)
    await g({"type": "http", "method": method, "path": path, "headers": [], "query_string": b""}, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in next(m for m in sent if m["type"] == "http.response.start")["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, headers, body, reached


@pytest.fixture
def unhealthy(monkeypatch):
    async def fake():
        return {"state": lh.UNHEALTHY, "reason": "store_unreachable", "source": "leader", "retry_after_s": 30}
    monkeypatch.setattr(lg, "verdict", fake)
    yield
    lg.configure(mode="off", inert=True)


def test_enforce_refuses_a_starting_request_with_the_sentence(unhealthy):
    lg.configure(mode="enforce", inert=False)
    status, headers, body, reached = _run(_call(None, "POST", "/api/v1/token/transfer"))
    assert status == 503 and not reached
    assert headers.get("retry-after") == "30"
    doc = json.loads(body)
    assert doc["code"] == "ledger_unavailable" and doc["status"] == 503
    assert doc["detail"] == lg.DETAIL and lg.SENTENCE in doc["detail"]
    assert doc["type"].endswith("/ledger-unavailable") and doc["instance"] == "/api/v1/token/transfer"
    assert doc["context"]["ledger"]["state"] == lh.UNHEALTHY


def test_enforce_lets_finishing_work_readers_and_unclassified_paths_through(unhealthy):
    lg.configure(mode="enforce", inert=False)
    for method, path in (("POST", "/api/v1/cross-teg/commit/t1"), ("POST", "/api/v1/cross-teg/credit-async"),
                         ("GET", "/api/v1/token/balance/x"), ("POST", "/api/v1/auth/token"),
                         ("POST", "/api/v1/admin/exchange/move")):
        status, _h, _b, reached = _run(_call(None, method, path))
        assert status == 200 and reached == [path], (method, path)


def test_shadow_refuses_nothing(unhealthy):
    lg.configure(mode="shadow", inert=False)
    status, _h, _b, reached = _run(_call(None, "POST", "/api/v1/token/transfer"))
    assert status == 200 and reached


def test_a_teg_without_the_outbox_is_inert(unhealthy):
    lg.configure(mode="enforce", inert=True)
    status, _h, _b, reached = _run(_call(None, "POST", "/api/v1/token/transfer"))
    assert status == 200 and reached


def test_require_ledger_in_a_handler(unhealthy):
    lg.configure(mode="enforce", inert=False)
    with pytest.raises(lg.LedgerUnavailableError):
        _run(lg.require_ledger("/api/v1/admin/exchange/move"))
    lg.configure(mode="shadow", inert=False)
    _run(lg.require_ledger("/api/v1/admin/exchange/move"))


def test_a_verdict_that_raises_reads_unhealthy(monkeypatch):
    async def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(lg, "verdict", boom)
    lg.configure(mode="enforce", inert=False)
    try:
        status, _h, body, reached = _run(_call(None, "POST", "/api/v1/tokenomics/stake"))
        assert status == 503 and not reached and b"unmeasured" in body
    finally:
        lg.configure(mode="off", inert=True)


# ------------------------------------------------------------------------------------------------ the outbox's hook
def test_the_outbox_measures_every_cycle_including_an_empty_one():
    from teg_core_service.core import balance_outbox as bo
    tree = _ast_of(bo.BalanceOutboxEmitter._cycle_once)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "_measure_health"]
    assert len(calls) == 2, f"_cycle_once measures the ledger {len(calls)} times (the empty path and the emitting one)"
    assert bo.BREAK_AFTER_FAILS >= 1

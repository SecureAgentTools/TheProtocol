"""§MONEY-R39 — the account-deletion forfeiture must ride the shared mTLS mover, and a drain
that moved no money must be a number the cycle fails on.

Found 2026-09-04 by the money audit: `_teg_drain_to_treasury` opened its OWN `aiohttp.ClientSession()`
and POSTed an admin bearer to `TEG_API_BASE_URL`, which on every mainframe and operator is the
`ssl_verify_client on` nginx-teg sidecar. No SPIRE bundle, no client SVID ⇒ CERTIFICATE_VERIFY_FAILED;
the plain port ⇒ 403 "mTLS identity required"; and the bearer was the placeholder-shaped marker the
TEG refuses since R26. Population on frame-a: ONE `AccountAnonymized` ever, `avt_forfeited "0"`,
1000 units stranded on a revoked agent; the worker's vitals read `ok`.

Two properties, both structural (parsed, never grepped — four text checks matched documentation in
one session), plus behaviour tests against the real module with the mover monkeypatched:
  1. the helper's ONLY outbound call is `services.escrow.escrow_deposit` (the guild/contract mover:
     httpx + get_httpx_verify() = SPIRE bundle + the registry's SVID), reason `account_deletion_forfeit`,
     ref `acctdel-forfeit-{deletion_id}-{did}` (the pre-R39 key shape, so replays stay replays);
  2. a failed drain is COUNTED (`registry_account_deletion_drain_failures_total{reason}`), carried in
     the `AccountAnonymized` payload (`teg_drain_failures`, `avt_staked_not_forfeited`), and FAILS the
     worker's vitals cycle via `ctx.fail(...)`.

Control: run with R39_SRC pointing at a pre-R39 copy of the two files — every structural test goes RED.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["R39_SRC"]) if os.environ.get("R39_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())
ROUTER = SRC / "routers" / "account_deletion.py"
WORKER = SRC / "background_tasks" / "account_deletion_worker.py"


def _fn(tree: ast.AST, name: str):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found — re-point this gate")


def _callee_name(c: ast.Call) -> str:
    f = c.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


@pytest.fixture(scope="module")
def router_tree():
    return ast.parse(ROUTER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def worker_tree():
    return ast.parse(WORKER.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 1 · the transport
def test_no_handrolled_http_session_in_the_module(router_tree):
    """`aiohttp`/`httpx` must not be imported by the deletion router at all: the only TEG
    transport a money leg may use is the shared mover's."""
    for n in ast.walk(router_tree):
        if isinstance(n, ast.Import):
            assert not any(a.name.split(".")[0] in ("aiohttp", "httpx") for a in n.names), ast.dump(n)
        if isinstance(n, ast.ImportFrom):
            assert (n.module or "").split(".")[0] not in ("aiohttp", "httpx"), ast.dump(n)


def test_the_drain_rides_escrow_deposit_and_nothing_else(router_tree):
    fn = _fn(router_tree, "_teg_drain_to_treasury")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
    names = {_callee_name(c) for c in calls}
    assert "escrow_deposit" in names, "the drain must ride services.escrow.escrow_deposit"
    forbidden = {"ClientSession", "AsyncClient", "post", "request", "urlopen"}
    assert not (names & forbidden), f"a hand-rolled transport survives in the drain: {names & forbidden}"
    # awaited, not fire-and-forget
    awaited = [a for a in ast.walk(fn) if isinstance(a, ast.Await)
               and isinstance(a.value, ast.Call) and _callee_name(a.value) == "escrow_deposit"]
    assert awaited, "escrow_deposit must be awaited"
    call = awaited[0].value
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw.get("reason"), ast.Constant) and kw["reason"].value == "account_deletion_forfeit", (
        "the TEG stamps entry_type from the reason; it must be the forfeiture's own")


def test_the_forfeit_key_shape_is_the_pre_r39_one(router_tree):
    """`acctdel-forfeit-{deletion_id}-{agent_did}` — a re-run after a partial anonymization must
    hit the SAME key and replay, never pay twice."""
    fn = _fn(router_tree, "_forfeit_ref")
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.JoinedStr), "the ref must be an f-string"
    head = ret.value.values[0]
    assert isinstance(head, ast.Constant) and head.value.startswith("acctdel-forfeit-"), head
    names = [v.value.id for v in ret.value.values
             if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)]
    assert names == ["deletion_id", "agent_did"], names


def test_the_drain_helper_imports_the_shared_mover_from_services(router_tree):
    fn = _fn(router_tree, "_teg_drain_to_treasury")
    imports = [n for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)]
    assert any((n.module or "").endswith("services.escrow") and
               {a.name for a in n.names} >= {"escrow_deposit", "EscrowError"} for n in imports), (
        "the mover must come from services.escrow, the module the guild/contract rails use")


# ---------------------------------------------------------------- 2 · counted, carried, failed
def test_a_failed_drain_is_counted_by_reason(router_tree):
    src = ROUTER.read_text(encoding="utf-8")
    counter = [n for n in ast.walk(router_tree) if isinstance(n, ast.Call)
               and any(isinstance(a, ast.Constant) and a.value == "registry_account_deletion_drain_failures_total"
                       for a in n.args)]
    assert counter, "counter registry_account_deletion_drain_failures_total must be defined"
    labels = [a for a in counter[0].args if isinstance(a, ast.List)]
    assert labels and [e.value for e in labels[0].elts] == ["reason"], "the counter is labelled by reason"
    fn = _fn(router_tree, "_teg_drain_to_treasury")
    reasons = sorted({c.args[0].value for c in ast.walk(fn) if isinstance(c, ast.Call)
                      and _callee_name(c) == "_count_drain_failure"
                      and c.args and isinstance(c.args[0], ast.Constant)})
    assert reasons == ["teg_refused", "transport"], reasons
    assert "except Exception" in src  # the transport class is caught, counted, and returned as False


def test_the_audit_event_carries_the_two_numbers(router_tree):
    """`AccountAnonymized.data` must carry `teg_drain_failures` and `avt_staked_not_forfeited` —
    without them a drain that never worked reads as an ordinary anonymization (dev 8483)."""
    emits = [c for c in ast.walk(router_tree) if isinstance(c, ast.Call) and _callee_name(c) == "emit"
             and any(k.arg == "event_type" and isinstance(k.value, ast.Constant)
                     and k.value.value == "AccountAnonymized" for k in c.keywords)]
    assert len(emits) == 1, f"expected one AccountAnonymized emit, found {len(emits)}"
    data = next(k.value for k in emits[0].keywords if k.arg == "data")
    assert isinstance(data, ast.Dict)
    keys = {k.value for k in data.keys if isinstance(k, ast.Constant)}
    for want in ("avt_forfeited", "avt_staked_not_forfeited", "teg_drain_failures"):
        assert want in keys, f"{want} missing from the AccountAnonymized payload: {sorted(keys)}"


def test_the_worker_fails_its_cycle_when_a_drain_moved_no_money(worker_tree):
    run = _fn(worker_tree, "run_forever")
    fails = [c for c in ast.walk(run) if isinstance(c, ast.Call) and _callee_name(c) == "fail"]
    assert fails, "run_forever must call ctx.fail(...) when drain_failures > 0"
    # the fail sits inside the vitals cycle context
    withs = [w for w in ast.walk(run) if isinstance(w, ast.AsyncWith)
             and any(isinstance(i.context_expr, ast.Call) and _callee_name(i.context_expr) == "cycle"
                     for i in w.items)]
    assert withs, "the cycle context is gone — re-point this gate"
    inside = [c for c in ast.walk(withs[0]) if isinstance(c, ast.Call) and _callee_name(c) == "fail"]
    assert inside, "ctx.fail must be inside the vitals cycle"
    # and the failure is conditioned on the drain count the scan returns
    guard = [t for t in ast.walk(withs[0]) if isinstance(t, ast.If)
             and "drain_failures" in ast.dump(t.test)]
    assert guard, "the fail must be gated on summary['drain_failures']"
    scan = _fn(worker_tree, "_scan_and_anonymize")
    returns = [r for r in ast.walk(scan) if isinstance(r, ast.Return) and r.value is not None]
    assert returns, "_scan_and_anonymize must RETURN its numbers"
    for r in returns:
        assert isinstance(r.value, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "drain_failures" for k in r.value.keys), ast.dump(r)


# ---------------------------------------------------------------- 3 · behaviour, mover monkeypatched
_mod = None
try:
    if not os.environ.get("R39_SRC"):
        from agentvault_registry.routers import account_deletion as _mod  # type: ignore
except Exception as _exc:  # noqa: BLE001
    _IMPORT_ERR = repr(_exc)
else:
    _IMPORT_ERR = ""

needs_module = pytest.mark.skipif(_mod is None, reason=f"router import unavailable here: {_IMPORT_ERR or 'R39_SRC control run'}")


def _counter_value(reason: str) -> float:
    c = _mod.ACCOUNT_DELETION_DRAIN_FAILURES
    if c is None:
        return 0.0
    return c.labels(reason=reason)._value.get()


@needs_module
@pytest.mark.asyncio
async def test_refused_drain_returns_false_and_counts(monkeypatch):
    from decimal import Decimal
    from agentvault_registry.services import escrow as _escrow

    async def refused(*a, **k):
        raise _escrow.EscrowError(403, "mTLS identity required")
    monkeypatch.setattr(_escrow, "escrow_deposit", refused)
    before = _counter_value("teg_refused")
    ok = await _mod._teg_drain_to_treasury("did:theprotocol:r39-test", Decimal("1"), "del-1")
    assert ok is False
    assert _counter_value("teg_refused") == before + 1


@needs_module
@pytest.mark.asyncio
async def test_transport_error_returns_false_and_counts(monkeypatch):
    from decimal import Decimal
    from agentvault_registry.services import escrow as _escrow

    async def dead(*a, **k):
        raise ConnectionError("CERTIFICATE_VERIFY_FAILED")
    monkeypatch.setattr(_escrow, "escrow_deposit", dead)
    before = _counter_value("transport")
    ok = await _mod._teg_drain_to_treasury("did:theprotocol:r39-test", Decimal("1"), "del-2")
    assert ok is False
    assert _counter_value("transport") == before + 1


@needs_module
@pytest.mark.asyncio
async def test_successful_drain_uses_the_forfeit_key_and_reason(monkeypatch):
    from decimal import Decimal
    from agentvault_registry.services import escrow as _escrow
    seen = {}

    async def ok_(source_did, amount, ref, *, reason):
        seen.update(source_did=source_did, amount=amount, ref=ref, reason=reason)
        return {"status": "ok"}
    monkeypatch.setattr(_escrow, "escrow_deposit", ok_)
    b_ref, b_tr = _counter_value("teg_refused"), _counter_value("transport")
    ok = await _mod._teg_drain_to_treasury("did:theprotocol:r39-test", Decimal("12.5"), "del-3")
    assert ok is True
    assert seen == {"source_did": "did:theprotocol:r39-test", "amount": Decimal("12.5"),
                    "ref": "acctdel-forfeit-del-3-did:theprotocol:r39-test",
                    "reason": "account_deletion_forfeit"}
    assert (_counter_value("teg_refused"), _counter_value("transport")) == (b_ref, b_tr)


@needs_module
@pytest.mark.asyncio
async def test_zero_amount_never_dials(monkeypatch):
    from decimal import Decimal
    from agentvault_registry.services import escrow as _escrow

    async def boom(*a, **k):
        raise AssertionError("must not dial for a zero amount")
    monkeypatch.setattr(_escrow, "escrow_deposit", boom)
    assert await _mod._teg_drain_to_treasury("did:theprotocol:r39-test", Decimal("0"), "del-4") is True

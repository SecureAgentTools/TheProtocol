"""§FXSTRAND-2 (2026-09-07) — THE "(origin refunded)" MARKER MUST MEAN THE MONEY WENT BACK.

agentvault2-eb measured the first fix on route 511e702c-eabb-4d0d-9c7f-deda461777f0: the sender
was down 48 of 50, @fx_router held +1.99, there was exactly ONE TokensTransferred for the route,
and an FxRouteRefunded sat beside it. `_fx_route_refund_to_origin` returned None on every path and
the caller appended the marker unconditionally, so a refund that FAILED still read as compensated —
the original false claim, one path narrower.

The second half is the same class as the failure being compensated: the refund resolves the origin's
home the way the egress resolves the receiver's, so a route failing BECAUSE a card has not propagated
here cannot be refunded for that same reason, and the dead-letter it writes carries no origin_teg_id,
leaving the keeper to repeat the resolve that just failed. The ids now ride the delegate payload.

These are AST gates on the compiled statements, not on behaviour a fixture could stage: the branch
only fires when a real peer refuses a real leg. Each gate carries its own RED control below.
"""
import ast
import pathlib

import pytest

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "src" / "agentvault_registry" / "routers" / "teg_integration.py")

REFUND = "_fx_route_refund_to_origin"
MARK = "_FX_COMPENSATED_MARK"
# §FXPOSTCONV (2026-09-26): the route engine's refunds go through one local wrapper, `_compensate`, which returns the
# refund's verdict (and refuses to refund at all after a conversion). A verdict RETURNED by it is consumed by whoever
# binds the wrapper's result, so the gate follows it one level.
WRAPPER = "_compensate"


def _tree(text=None):
    return ast.parse(text if text is not None else SRC.read_text())


def _func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found")


# ── the three properties, as functions so a control can be run through them ───────────────────
def refund_results_are_consumed(tree):
    """Every refund call's bool is consumed (never called for effect): bound to a name, or RETURNED by the
    engine's wrapper, whose every call is itself bound."""
    bound, consumed = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Await):
            call = n.value.value
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") in (REFUND, WRAPPER):
                bound |= {t.id for t in n.targets if isinstance(t, ast.Name)}
                consumed.add(id(call))
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Await):
            call = n.value.value
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == REFUND:
                consumed.add(id(call))
    calls = [c for c in ast.walk(tree)
             if isinstance(c, ast.Call) and getattr(c.func, "id", "") in (REFUND, WRAPPER)]
    ok = len(calls) > 0 and len(bound) > 0 and all(id(c) in consumed for c in calls)
    return ok, [c for c in calls if getattr(c.func, "id", "") == REFUND], bound


def relayed_verdicts(tree):
    """§REPATLANE (V0603): the names an ORIGIN binds from the far gateway's verdict. The origin does not refund: the
    gateway does, and writes the marker only when its own refund succeeded; `_fx_route_delegate` turns the gateway's
    refusal into `{"compensated": MARK in <its detail>}`, and the origin binds `.get("compensated")`. A name bound that
    way carries the gateway's refund verdict, so the origin may relay the marker under it. Only counted while the
    delegate still computes `compensated` from the marker itself."""
    delegates = [f for f in ast.walk(tree)
                 if isinstance(f, (ast.AsyncFunctionDef, ast.FunctionDef)) and f.name == "_fx_route_delegate"]
    reads_the_mark = any(
        isinstance(k, ast.Constant) and k.value == "compensated" and isinstance(v, ast.Compare)
        and any(isinstance(x, ast.Name) and x.id == MARK for x in ast.walk(v.left))
        and any(isinstance(op, ast.In) for op in v.ops)
        for f in delegates for n in ast.walk(f) if isinstance(n, ast.Dict) for k, v in zip(n.keys, n.values))
    if not reads_the_mark:
        return set()
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "get" and c.args
                and isinstance(c.args[0], ast.Constant) and c.args[0].value == "compensated"
                for c in ast.walk(n.value)):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return names


def marker_is_conditional(tree, bound):
    """Every use of the marker in a raise must sit in an IfExp tested on a bound refund result."""
    uses, guarded = 0, 0
    for n in ast.walk(tree):
        if isinstance(n, ast.Raise):
            for sub in ast.walk(n):
                if isinstance(sub, ast.Name) and sub.id == MARK:
                    uses += 1
                    break
            for sub in ast.walk(n):
                if isinstance(sub, ast.IfExp) and any(
                    isinstance(x, ast.Name) and x.id == MARK for x in ast.walk(sub)
                ) and any(isinstance(x, ast.Name) and x.id in bound for x in ast.walk(sub.test)):
                    guarded += 1
                    break
    return uses > 0 and uses == guarded, uses, guarded


def refund_returns_a_verdict(tree):
    """Every return in the helper carries a value — None on any path is the defect itself."""
    fn = _func(tree, REFUND)
    rets = [r for r in ast.walk(fn) if isinstance(r, ast.Return)]
    return bool(rets) and all(r.value is not None for r in rets), rets


# ── gates ─────────────────────────────────────────────────────────────────────────────────────
def test_every_refund_result_is_consumed():
    ok, calls, bound = refund_results_are_consumed(_tree())
    assert ok, f"{len(calls)} refund call(s), {len(bound)} bound result(s) — a discarded bool is the bug"


def test_the_compensated_marker_is_never_unconditional():
    _, _, bound = refund_results_are_consumed(_tree())
    relayed = relayed_verdicts(_tree())
    assert relayed == {"_compensated"}, relayed
    ok, uses, guarded = marker_is_conditional(_tree(), bound | relayed)
    assert ok, f"{uses} raise(s) mention {MARK}, only {guarded} guarded on the refund's own verdict"


def test_refund_helper_returns_a_verdict_on_every_path():
    ok, rets = refund_returns_a_verdict(_tree())
    assert ok, f"{sum(1 for r in rets if r.value is None)} bare return(s) — the caller cannot tell"


def test_refund_calls_carry_the_origin_home_ids():
    """The keeper must never have to resolve what the failing hop already could not."""
    _, calls, _ = refund_results_are_consumed(_tree())
    for c in calls:
        kw = {k.arg for k in c.keywords}
        assert {"origin_teg_id", "origin_registry_id"} <= kw, \
            f"refund at line {c.lineno} does not pass the origin's home ids"


def test_hop_request_and_engine_carry_the_origin_home_ids():
    tree = _tree()
    model = _func_or_class(tree, "FxRouteHopRequest")
    fields = {n.target.id for n in model.body if isinstance(n, ast.AnnAssign)}
    assert {"origin_teg_id", "origin_registry_id"} <= fields, \
        "FxRouteHopRequest must accept the origin's home ids from the calling frame"
    for fname in ("_fx_route_hop_execute", "_fx_route_hop_execute_inner"):
        fn = _func(tree, fname)
        params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        assert {"origin_teg_id", "origin_registry_id"} <= params, f"{fname} drops them"


def test_the_origin_stamps_its_own_home_on_the_first_hop():
    """Two kickoff payloads (same-currency gateway and FX-core delegate) — both must stamp."""
    tree = _tree()
    stamped = 0
    for n in ast.walk(tree):
        if not isinstance(n, ast.Dict):
            continue
        keys = {k.value for k in n.keys if isinstance(k, ast.Constant)}
        if "final_receiver_did" not in keys or "hop_budget" not in keys:
            continue
        if {"origin_teg_id", "origin_registry_id"} <= keys:
            calls = {getattr(v.func, "id", "") for v in n.values if isinstance(v, ast.Call)}
            if {"_get_local_teg_id", "_get_local_registry_id"} <= calls:
                stamped += 1
    assert stamped == 2, f"{stamped} of 2 origin kickoff payloads stamp their own home ids"


def _func_or_class(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return n
    raise AssertionError(f"class {name} not found")


# ── controls: the gates must go RED on the shapes they exist to refuse ────────────────────────
_OLD_UNCONDITIONAL = f'''
{MARK} = "(origin refunded)"
async def {REFUND}(db, a, b, origin_did, amount, route_id):
    try:
        return
    except Exception:
        logger.error("parked")
async def caller():
    await {REFUND}(db, a, b, o, amt, rid)
    raise HTTPException(status_code=409, detail=f"failed {{{MARK}}}")
'''


def test_control_the_old_shape_fails_every_gate():
    tree = _tree(_OLD_UNCONDITIONAL)
    ok_consumed, calls, bound = refund_results_are_consumed(tree)
    assert calls, "control must still contain a refund call"
    assert not ok_consumed, "control's discarded result must be refused"
    ok_mark, uses, guarded = marker_is_conditional(tree, bound)
    assert uses == 1 and guarded == 0 and not ok_mark, "control's unconditional marker must be refused"
    ok_ret, _ = refund_returns_a_verdict(tree)
    assert not ok_ret, "control's bare return must be refused"


_FIXED_SHAPE = f'''
{MARK} = "(origin refunded)"
async def {REFUND}(db, a, b, origin_did, amount, route_id, origin_teg_id="", origin_registry_id=""):
    if not rtid:
        return False
    return True
async def caller():
    _did = await {REFUND}(db, a, b, o, amt, rid, origin_teg_id=t, origin_registry_id=r)
    raise HTTPException(status_code=409,
                        detail="failed" + (f" {{{MARK}}}" if _did else " — refund ALSO failed"))
'''


_RELAY = f'''
{MARK} = "(origin refunded)"
async def _fx_route_delegate(url, body):
    return {{"status": "error", "compensated": {MARK} in str(_d)}}
async def origin():
    onward = await _fx_route_delegate(u, b)
    _compensated = bool((onward or {{}}).get("compensated"))
    raise HTTPException(status_code=409, detail="failed" + (f" {{{MARK}}}" if _compensated else "."))
async def origin_unguarded():
    other = True
    raise HTTPException(status_code=409, detail="failed" + (f" {{{MARK}}}" if other else "."))
'''


def test_control_a_relayed_verdict_guards_only_its_own_raise():
    """§REPATLANE (V0603): the origin's relay of the gateway's verdict passes; a marker guarded on any other name does
    not, and once the delegate stops reading the marker no name counts as a relayed verdict."""
    tree = _tree(_RELAY)
    relayed = relayed_verdicts(tree)
    assert relayed == {"_compensated"}
    ok, uses, guarded = marker_is_conditional(tree, relayed)
    assert (ok, uses, guarded) == (False, 2, 1), "the raise guarded on `other` must be refused"
    assert relayed_verdicts(_tree(_RELAY.replace(f"{MARK} in str(_d)", "True"))) == set()


def test_control_the_fixed_shape_passes_every_gate():
    """The green half: a gate that only ever refuses would pass by refusing everything."""
    tree = _tree(_FIXED_SHAPE)
    ok_consumed, _, bound = refund_results_are_consumed(tree)
    assert ok_consumed
    ok_mark, uses, guarded = marker_is_conditional(tree, bound)
    assert ok_mark and uses == 1 == guarded
    ok_ret, _ = refund_returns_a_verdict(tree)
    assert ok_ret


_WRAPPED_SHAPE = f'''
{MARK} = "(origin refunded)"
async def {REFUND}(db, a, b, origin_did, amount, route_id, origin_teg_id="", origin_registry_id=""):
    return True
async def engine(post_conversion=False):
    async def {WRAPPER}():
        if post_conversion:
            return False
        return await {REFUND}(db, a, b, o, amt, rid, origin_teg_id=t, origin_registry_id=r)
    _did = await {WRAPPER}()
    raise HTTPException(status_code=409, detail="failed" + (f" {{{MARK}}}" if _did else " parked"))
'''


def test_control_the_wrapped_shape_passes_and_a_discarded_wrapper_fails():
    """§FXPOSTCONV: the engine's wrapper returns the verdict; its caller binds it. A wrapper called for effect is
    the old defect one level up and must still be refused."""
    tree = _tree(_WRAPPED_SHAPE)
    ok_consumed, _, bound = refund_results_are_consumed(tree)
    assert ok_consumed and "_did" in bound
    ok_mark, uses, guarded = marker_is_conditional(tree, bound)
    assert ok_mark and uses == 1 == guarded
    discarded = _tree(_WRAPPED_SHAPE.replace(f"_did = await {WRAPPER}()", f"await {WRAPPER}()\n    _did = True"))
    ok_bad, _, _ = refund_results_are_consumed(discarded)
    assert not ok_bad, "a wrapper whose verdict is dropped must be refused"

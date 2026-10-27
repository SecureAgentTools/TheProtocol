"""The emissions that cannot be driven, gated structurally (§FEDEVENTS batch 4).

The first three batches drive every emission a test can actually cause. That
leaves the majority: 172 distinct event types are emitted registry-wide, and
most of the remainder fire only on a timeout, a breach, a multi-day window or a
reactor cycle — the settlement saga family, the bridge lock/unlock pair,
`TokensUnstaked` behind a ~7-day cooldown, the compensation mints, treasury
quarantine. No test can manufacture those, and a test that waits for one is a
test that reports a defect when the world was simply quiet.

**A drive is the wrong instrument for them; the emit SITE is the right one.**
This file censuses every `event_type=` call in the running image by AST and
asserts the properties an emission needs in order to be trustworthy when it
eventually fires:

  1. it names an aggregate — an event nobody can look up is not an audit record;
  2. a value-touching emission does not sit in a handler that discards its own
     failure;
  3. the population of already-weak sites does not GROW.

(3) is a ratchet rather than a pass/fail, and deliberately. 141 of 217 sites
carry no `idempotency_key` and 28 swallow their own failure; a gate that failed
on the existing population would be red forever, and a permanently-red ratchet
is a disabled ratchet. What it can do honestly is refuse to let the number
climb.

⚠ AST, not grep. Three separate content checks failed across two sessions on
2026-09-04 by matching a docstring or a comment instead of code — including one
where a grep matched the very comment describing the behaviour it was asserting
had been removed. `ast.parse` cannot make that mistake.

This runs entirely against source inside the image. It writes nothing, calls no
rail, and is Δ-irrelevant.
"""
from __future__ import annotations

import ast
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import _done

# Baselines measured 2026-09-04 against the §FEDEVENTS image. These are
# CEILINGS, not targets: the gate fails when the population of weak sites grows.
# ⚠ RE-MEASURED after the census was widened. The first version read only
# `event_type=` KEYWORD args and was blind to `_emit("GuildBidPlaced", ...)` and
# `_emit_legacy("ContractCreated", ...)` — an entire emission style, 114 sites
# and 84 event types, including 40 types with live rows in the EventStore. A
# gate is loudest about what its scope cannot see; these numbers were the proof.
# ⚠ RE-MEASURED AGAIN 2026-09-06 (§EVTYPES4), and the drop is mostly the
# INSTRUMENT getting more honest, not the code getting better:
#   * agentvault2-60's batch-8 item 8 keyed 24 value-touching sites (aa909b8);
#   * the census now RESOLVES the callee, so 13 sites that were always keyed
#     (the wrapper builds or forwards the key) stopped being counted against
#     it, and 5 rows that were never emissions at all — `_record_canary_event`
#     stamps redis and emits nothing — left the population entirely.
# Measured on the TREE: 332 sites, 186 keyless, 4 value-touching keyless, 27
# swallowed. The four were deliberate then, each with a written reason: two
# recorded a NON-event (a key dedups nothing), two were treasury-quarantine
# flips where a time-scoped key was thought to park a legitimate re-trigger
# inside its own window (the keeper rule).
# ⚠ RE-MEASURED 2026-09-14 (§SILENT): 340 sites, 186 keyless, 0 value-touching
# keyless, 22 swallowed. The four are keyed now, and the reasons changed with
# the reading: a per-attempt key on the two non-events dedups exactly what every
# key dedups, the emitter's own retry after a timeout the store had already
# accepted; and the two treasury flips carry a per-DAY key because a day is the
# granularity of the decision itself (the streak is read from distribution
# DAYS and each flip is guarded by the recorded state), so the key parks
# nothing the flip could legitimately repeat. The 22 swallowed left are
# debug-only handlers on non-value events (delegation, pull-sync, tallies,
# diagnostics); the six value sites report at ERROR and count instead
# (`emit_or_report`, `registry_value_emit_failed_total`).
# 🔴 A TIER RUNNING AN OLDER IMAGE WILL READ HIGHER AND THIS RATCHET WILL BE RED
# THERE. That is correct and intended: the ceiling describes the code, and an
# image that predates the code is behind it, not exempt. It goes green on the
# tier's next rebuild.
_BASELINE_NO_IDEMPOTENCY = 186
_BASELINE_SWALLOWED = 22  # §SILENT 2026-09-14: 27 -> 22 (the six value sites report instead of swallowing; the 22 left are debug-only handlers on non-value events)

_VALUE = re.compile(
    r"Token|Transfer|Fee|Stak|Reward|Escrow|Settle|Payment|Dividend|Mint|Burn|"
    r"Slash|Fund|Treasur|Fiat|Bridge")


def _registry_root() -> str:
    import agentvault_registry
    return os.path.dirname(agentvault_registry.__file__)


def _kw(call: ast.Call, name: str) -> Optional[str]:
    for k in call.keywords or []:
        if k.arg == name:
            try:
                return ast.unparse(k.value)
            except Exception:
                return "?"
    return None


def _swallow_class(tree: ast.AST, call: ast.Call) -> Optional[str]:
    """Is this emit inside a handler that records nothing?

    Two shapes count: a bare `pass`, and a debug-only log with no re-raise. Both
    mean a broken emitter degrades to silence, which is the §VITALS failure —
    real, handled, and invisible to anything reading status codes.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not any(n is call for n in ast.walk(node)):
            continue
        for handler in node.handlers:
            if all(isinstance(b, ast.Pass) for b in handler.body):
                return "pass"
            txt = " ".join(ast.unparse(b) for b in handler.body)
            if "logger.debug" in txt and "raise" not in txt:
                return "debug-only"
    return None


_EVENT_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{3,}$")           # CamelCase types
_DOTTED_NAME = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*$")   # stake.completed


def _callee(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


# ── §EVTYPES4 2026-09-06 — resolve the CALLEE before judging the call ────────
# WHY. The census called a site "keyless" whenever the CALL did not carry
# `idempotency_key=`. Measured against the real code by agentvault2-60 while
# keying the value-touching sites, 13 of the 41 it named were wrong in one of
# three ways, and a fourth kind was not an emission at all:
#
#   * the wrapper DERIVES the key itself   (_emit_fx_event / _emit_fx_route_event
#     build `idempotency_key=f"{event_type}:{swap_id}"` internally);
#   * the site passes the key under another NAME (exchange_service._emit takes
#     `key=`);
#   * the site passes it POSITIONALLY (org_treasury._emit_org_money_event);
#   * `_record_canary_event` takes `event_type=` and stamps REDIS — it emits
#     nothing, so its five call sites were never emit sites at all and had no
#     business in the denominator.
#
# So resolve the callee, one level, in its own file, and ask what it actually
# does. Same-file only ON PURPOSE: `_emit` is defined in several modules and a
# global name map would resolve the wrong one, which is a worse failure than the
# one being fixed. A callee this cannot find is judged exactly as before.
_KEY_PARAM_NAMES = ("idempotency_key", "key", "idem_key")


def _local_defs(tree: ast.AST) -> Dict[str, Any]:
    """name -> FunctionDef for every def in this module (methods included)."""
    out: Dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _key_param_index(fn) -> Optional[Tuple[str, int]]:
    """(param_name, positional_index) of the callee's key parameter, if any."""
    args = list(getattr(fn.args, "posonlyargs", []) or []) + list(fn.args.args or [])
    for i, a in enumerate(args):
        if a.arg in _KEY_PARAM_NAMES:
            return a.arg, i
    for a in (fn.args.kwonlyargs or []):
        if a.arg in _KEY_PARAM_NAMES:
            return a.arg, -1
    return None


def _wrapper_facts(fn) -> Dict[str, bool]:
    """What the resolved callee does: reach an emitter, and where its key comes from.

    ⚠ DERIVED IS NOT THE SAME AS FORWARDED, and conflating them is a FALSE
    GREEN — the dangerous direction for a ratchet. Measured while writing this:
    treating any `idempotency_key=` inside the wrapper as "this wrapper keys its
    sites" flipped 61 sites to keyed, including every `guild._emit` and
    `admin_agents._emit_admin_action` call — and both of those forward a
    parameter that DEFAULTS TO None, so a site that omits it is genuinely
    keyless. Only a key the wrapper BUILDS (an f-string, a computed expression)
    keys every site unconditionally; a key it merely passes through still has to
    be supplied at the call.
    """
    reaches_emitter = False
    derives_key = False
    supplies_aggregate = False
    param_names = {a.arg for a in
                   (list(getattr(fn.args, "posonlyargs", []) or [])
                    + list(fn.args.args or []) + list(fn.args.kwonlyargs or []))}
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Call):
            continue
        if "emit" not in _callee(sub).lower():
            continue
        reaches_emitter = True
        for k in sub.keywords or []:
            if k.arg not in _KEY_PARAM_NAMES:
                continue
            # a bare Name that is one of this wrapper's own parameters is a
            # PASS-THROUGH; anything else (f-string, call, attribute, literal)
            # is the wrapper minting the key itself.
            if isinstance(k.value, ast.Name) and k.value.id in param_names:
                continue
            derives_key = True
        # §EVTYPES8: the SAME question one dimension over. A wrapper that BUILDS
        # its own aggregate_id (`f"agent:{agent_did}"`) names the aggregate for
        # every one of its callers; one that merely forwards a parameter does
        # not, and its callers still have to supply it. Derived, never forwarded
        # — the distinction that stopped 61 false flips on the key dimension.
        for k in sub.keywords or []:
            if k.arg != "aggregate_id":
                continue
            if isinstance(k.value, ast.Name) and k.value.id in param_names:
                continue
            supplies_aggregate = True
    return {"reaches_emitter": reaches_emitter, "derives_key": derives_key,
            "supplies_aggregate": supplies_aggregate}


def _callee_supplies_aggregate(call: ast.Call, defs: Dict[str, Any]) -> bool:
    """Does this call's resolvable callee BUILD the aggregate_id itself?

    False for anything this file cannot read — an unresolved name must never be
    excused, because a census that drops what it cannot see is the failure mode
    rather than the fix (same rule as `_site_key_state`).
    """
    name = _callee(call).split(".")[-1]
    fn = defs.get(name)
    if fn is None:
        return False
    try:
        return bool(_wrapper_facts(fn).get("supplies_aggregate"))
    except Exception:                                        # noqa: BLE001
        return False


def _site_key_state(call: ast.Call, defs: Dict[str, Any]) -> str:
    """'keyed' | 'keyless' | 'not-an-emit'.

    'not-an-emit' is only ever returned for a callee this file CAN resolve and
    that provably reaches no emitter — never for an unresolved name, because a
    census that drops what it cannot read is the failure mode, not the fix.
    """
    for k in call.keywords or []:
        if k.arg == "idempotency_key":
            return "keyed"
    fn = defs.get(_callee(call))
    if fn is None:
        return "keyless"
    facts = _wrapper_facts(fn)
    if not facts["reaches_emitter"]:
        return "not-an-emit"
    if facts["derives_key"]:
        return "keyed"
    kp = _key_param_index(fn)
    if kp:
        pname, pidx = kp
        for k in call.keywords or []:
            if k.arg == pname:
                return "keyed"
        if pidx >= 0 and len(call.args) > pidx:
            return "keyed"
    return "keyless"


def _event_names_of(call: ast.Call) -> list:
    """The event name(s) one call emits, each with how it was found.

    §NIGHTLYTRUTH (2026-09-14): `event_type="A" if refused else "B"` is TWO names. The old extraction
    took `ast.unparse` of the keyword, saw it start with a quote, stripped the quotes and filed
    `A' if refused else 'B` as one row — which the census's own control then reported as "a row that
    looks like prose" every night (`background_tasks/federation_sync.py:163`). A conditional with two
    string branches yields both; a name that is not a literal (an f-string, a variable) yields nothing,
    exactly as before.
    """
    for k in call.keywords or []:
        if k.arg == "event_type":
            v = k.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                return [(v.value, "keyword")]
            if isinstance(v, ast.IfExp):
                names = [b.value for b in (v.body, v.orelse)
                         if isinstance(b, ast.Constant) and isinstance(b.value, str)]
                return [(n, "keyword-conditional") for n in names]
            return []
    if "emit" in _callee(call).lower() and call.args:
        a0 = call.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            v = a0.value
            if _EVENT_NAME.match(v) or _DOTTED_NAME.match(v):
                return [(v, "positional")]
    return []


def _sourceless(root: str) -> Optional[str]:
    """Why this census cannot read code here, or None.

    A release image ships bytecode only (the kit's Dockerfile.registry.dist): the
    package holds `.pyc` files and no `.py`, so a source census finds nothing
    because there is nothing to read. That is a property of the IMAGE, not a
    finding, and it is said as one (§TESTBED 2026-09-19: the kit's sandbox ran
    the federation suite and the census self-check went red on 0 sites). A tree
    that HAS source and still yields no census stays red: the control below
    exists for exactly that.
    """
    py = pyc = 0
    for dirpath, _dirs, files in os.walk(root):
        # the census's OWN scope (see _census): the test suite ships as source in a release image too, and so do the
        # three seed scripts compose runs by name; counting them read a bytecode-only package as one with source
        # (measured on the dev3 kit image: api_tests plus prod_seed/operator_seed/test_seed.py, still red on 0 sites)
        if "__pycache__" in dirpath or f"{os.sep}api_tests" in dirpath:
            continue
        for fn in files:
            if fn.endswith(".py") and ".bak" not in fn:
                py += 1
            elif fn.endswith(".pyc"):
                pyc += 1
    if not pyc or py * 20 >= pyc:        # a package that is mostly source (or has no bytecode) is read as source
        return None
    return (f"this image ships bytecode only ({pyc} .pyc files, {py} .py under {root}): the "
            f"emission census reads source and has none to read here, so the event-contract "
            f"gates are NOT MEASURED on it; they run from a source tree (CI does)")


def _census() -> List[Dict[str, Any]]:
    """Every emit site in the installed registry package.

    Catches BOTH shapes: `event_type="X"` as a keyword, and `X` as the first
    positional argument of anything whose name contains "emit". The keyword-only
    version of this function missed 114 sites.

    Raises PreconditionUnmet in an image without source (see `_sourceless`), so
    every gate built on it skips with the true reason instead of passing on an
    empty census or failing as if the code had lost its emitters.
    """
    root = _registry_root()
    why = _sourceless(root)
    if why:
        raise PreconditionUnmet(why)
    rows: List[Dict[str, Any]] = []
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath or f"{os.sep}api_tests" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py") or ".bak" in fn:
                continue
            path = os.path.join(dirpath, fn)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except Exception:
                continue
            _defs = _local_defs(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                names = _event_names_of(node)
                if not names:
                    continue
                _state = _site_key_state(node, _defs)
                if _state == "not-an-emit":
                    continue          # the callee reaches no emitter (see above)
                base = {
                    "key_state": _state,
                    "callee": _callee(node),
                    "file": os.path.relpath(path, root),
                    "line": node.lineno,
                    "aggregate_id": _kw(node, "aggregate_id"),
                    # §EVTYPES8: resolved from the CALLEE, so a wrapper that builds
                    # the aggregate itself is not reported as a site missing one.
                    "callee_supplies_aggregate": _callee_supplies_aggregate(node, _defs),
                    "idempotency_key": _kw(node, "idempotency_key"),
                    "swallowed": _swallow_class(tree, node),
                }
                for event, how in names:
                    rows.append({**base, "event": event, "how": how})
    return rows


def _sites(rows) -> str:
    return ", ".join(f"{r['file']}:{r['line']}({r['event']})" for r in rows[:12])


@federation_test(
    name="emission_sites_name_an_aggregate",
    category="event_contract",
    budget_sec=90.0,
    severity="high",
    requires=[],
    tags=["no-probe", "event_emission", "contract", "static"],
)
async def test_emission_sites_name_an_aggregate(rig: FederationTestRig) -> AssertionResult:
    """A direct emit must say which aggregate the event belongs to.

    `aggregate_id` is how anything is ever found again: the whole suite queries
    `/events/aggregate/{id}`, and an event emitted without one is a row nobody
    can look up from the entity it describes. Sites that emit through a wrapper
    (`_emit_admin_action`, `emit_staking_event`, the `emit_tokens_*` family) pass
    their aggregate inside the helper and are excluded — the census cannot see
    through the call, and reporting them would be an artefact of the instrument
    rather than a finding.
    """
    # `no-probe`: this is STATIC ANALYSIS, not an integration test — it walks
    # the source tree via _census()/the guard under test and never reaches the
    # tier, so the U1 vacuity verdict must not fire on it. The tag is a claim
    # a reader can check, and U1 is what made the distinction visible: before
    # it, a source-reading gate and a tier probe were indistinguishable rows.
    rows = _census()
    if not rows:
        raise PreconditionUnmet("no emit sites found — the census is looking in the wrong tree")
    direct = [r for r in rows
              if r.get("how") == "keyword"
              and (r["idempotency_key"] is not None or r["aggregate_id"] is not None)]
    # §EVTYPES8 — THE DOCSTRING'S EXCLUSION HAD STOPPED WORKING. Wrapper sites are
    # meant to be excluded (they pass their aggregate inside the helper), and the
    # filter above implements that by "has an explicit kwarg". §BATCH7 then added
    # `idempotency_key=` to wrapper CALLS, which pulled them back into `direct` —
    # so `admin_agents.py:668(AgentOwnershipTransferred)` was reported as missing
    # an aggregate while `_emit_admin_action` sets `aggregate_id=f"agent:{did}"`
    # two frames down. An artefact of the instrument, which is precisely what the
    # docstring warns against. Resolve the callee instead of guessing from kwargs:
    # a wrapper that BUILDS an aggregate names it for every caller.
    missing = [r for r in direct
               if not r["aggregate_id"] and not r.get("callee_supplies_aggregate")]
    state = {
        "emit_sites_total": len(rows),
        "sites_with_explicit_kwargs": len(direct),
        "missing_aggregate": len(missing),
        "examples": _sites(missing),
    }
    return _done(not missing, "every direct emit site names an aggregate", state)


@federation_test(
    name="value_emissions_do_not_swallow_their_failure",
    category="event_contract",
    budget_sec=90.0,
    severity="critical",
    requires=[],
    tags=["no-probe", "event_emission", "contract", "money", "static"],
)
async def test_value_emissions_do_not_swallow_failure(rig: FederationTestRig) -> AssertionResult:
    """No VALUE-touching emission may sit in a handler that discards its failure.

    This is the §S4 shape stated as a rule. The supply invariant is computed
    from these events, so an emit that fails silently moves `total_circulating`
    and `transit_net` by exactly zero while money moves in the TEG — Δ reads a
    contented 0.0 and nothing anywhere goes red. `TEGBulkProxy._flush` was
    exactly this, wrapped in `except Exception: pass`, and it was the ONLY site
    emitting for coalesced transfers.

    A ratchet on the measured population rather than a demand that it be zero:
    the count may not grow. Reported per site, so the list is actionable rather
    than a number.
    """
    # `no-probe`: this is STATIC ANALYSIS, not an integration test — it walks
    # the source tree via _census()/the guard under test and never reaches the
    # tier, so the U1 vacuity verdict must not fire on it. The tag is a claim
    # a reader can check, and U1 is what made the distinction visible: before
    # it, a source-reading gate and a tier probe were indistinguishable rows.
    rows = _census()
    if not rows:
        raise PreconditionUnmet("no emit sites found — the census is looking in the wrong tree")
    swallowed = [r for r in rows if r["swallowed"]]
    value_swallowed = [r for r in swallowed if _VALUE.search(r["event"])]
    state = {
        "emit_sites_total": len(rows),
        "swallowed_total": len(swallowed),
        "swallowed_baseline": _BASELINE_SWALLOWED,
        "value_touching_swallowed": len(value_swallowed),
        "value_sites": _sites(value_swallowed),
        "by_class": {c: sum(1 for r in swallowed if r["swallowed"] == c)
                     for c in ("pass", "debug-only")},
    }
    grew = len(swallowed) > _BASELINE_SWALLOWED
    state["grew_since_baseline"] = grew
    return _done(not grew,
                 "the population of failure-swallowing emit sites has not grown", state)


@federation_test(
    name="emission_idempotency_key_ratchet",
    category="event_contract",
    budget_sec=90.0,
    severity="high",
    requires=[],
    # §EVTYPES 2026-09-05: structural (source census, no tier probe) — same
    # missing "no-probe" as its sibling ratchet; a green run would read vacuous.
    tags=["no-probe", "event_emission", "contract", "static"],
)
async def test_emission_idempotency_ratchet(rig: FederationTestRig) -> AssertionResult:
    """The count of emissions without an idempotency key may not grow.

    An emit with no key cannot be deduplicated, so a retry writes the event
    twice. For a value event that is a double entry in the ledger the invariant
    is derived from; for an audit event it is a second record of one act.

    141 of 217 sites carry no key today. Demanding zero would produce a gate
    that is red forever, and a permanently-red ratchet is a disabled one — the
    §DASHRESTORE lesson. So this holds the line instead, and names the
    value-touching subset separately because those are the ones worth fixing
    first.
    """
    rows = _census()
    if not rows:
        raise PreconditionUnmet("no emit sites found — the census is looking in the wrong tree")
    # §EVTYPES4: `key_state` is the resolved answer (the raw `idempotency_key`
    # field only sees a key written AT the call site, which is how 13 keyed
    # sites and 5 non-emissions were being counted against this ratchet).
    no_key = [r for r in rows if r["key_state"] == "keyless"]
    value_no_key = [r for r in no_key if _VALUE.search(r["event"])]
    state = {
        "emit_sites_total": len(rows),
        "without_idempotency_key": len(no_key),
        "baseline": _BASELINE_NO_IDEMPOTENCY,
        "value_touching_without_key": len(value_no_key),
        "value_sites": _sites(value_no_key),
    }
    grew = len(no_key) > _BASELINE_NO_IDEMPOTENCY
    state["grew_since_baseline"] = grew
    return _done(not grew, "the population of key-less emit sites has not grown", state)


@federation_test(
    name="emission_census_callee_resolution_controls",
    category="event_contract",
    budget_sec=30.0,
    severity="critical",
    requires=[],
    tags=["no-probe", "event_emission", "contract", "control"],
)
async def test_callee_resolution_controls(rig: FederationTestRig) -> AssertionResult:
    """Controls for §EVTYPES4's callee resolution — BOTH directions.

    The resolution added on 2026-09-06 makes the census answer FEWER sites
    keyless (227 -> 186) and drop 5 rows from the population. Every one of those
    moves makes a ratchet looser, which is the direction that has to be proven,
    not assumed: a resolver bug here does not show up as a red run, it shows up
    as a quieter green. So each rule gets a control that fails if the rule stops
    working, and — the half that matters — a control that fails if the rule
    starts swallowing a genuinely unkeyed site.

    Snippet-based on purpose: parsing five short modules is exact and instant,
    where planting a file in the real tree would measure the filesystem.
    """
    def state_of(src: str, line_of_interest: int = 0) -> str:
        tree = ast.parse(src)
        defs = _local_defs(tree)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and (_kw(n, "event_type") or
                     ("emit" in _callee(n).lower() and n.args) or
                     _callee(n).startswith(("_emit", "_record")))]
        target = [c for c in calls if c.lineno == line_of_interest] if line_of_interest else calls
        return _site_key_state(target[-1], defs) if target else "no-call"

    cases: Dict[str, Any] = {}

    # (1) RED CONTROL — a bare emit with no key anywhere must stay keyless.
    cases["bare_emit_is_keyless"] = state_of(
        "def _emit(t, a, d):\n"
        "    get_event_emitter().emit_background(event_type=t, aggregate_id=a, data=d)\n"
        "def caller():\n"
        "    _emit('TokensTransferred', 'x', {})\n", 4) == "keyless"

    # (2) the wrapper BUILDS the key -> every site is keyed without passing one.
    cases["derived_key_is_keyed"] = state_of(
        "def _emit_fx(event_type, swap_id, d):\n"
        "    emitter.emit(event_type=event_type, idempotency_key=f'{event_type}:{swap_id}')\n"
        "def caller():\n"
        "    _emit_fx('FxSwapSettled', 's1', {})\n", 4) == "keyed"

    # (3) 🔴 THE ONE THAT NEARLY WENT WRONG. A wrapper that merely FORWARDS a
    # parameter defaulting to None does NOT key a site that omits it. Treating
    # forwarded and derived alike flipped 61 sites green, guild._emit and
    # _emit_admin_action among them.
    forwarding = ("def _emit(event_type, agg, data, idempotency_key=None):\n"
                  "    emitter.emit_background(event_type=event_type, idempotency_key=idempotency_key)\n")
    cases["forwarded_key_omitted_is_keyless"] = state_of(
        forwarding + "def caller():\n    _emit('GuildOrderPosted', 'o1', {})\n", 4) == "keyless"
    cases["forwarded_key_supplied_is_keyed"] = state_of(
        forwarding + "def caller():\n    _emit('GuildOrderSettled', 'o1', {}, idempotency_key='guild-settled-o1')\n",
        4) == "keyed"

    # (4) a key passed POSITIONALLY into the callee's key parameter counts.
    cases["positional_key_is_keyed"] = state_of(
        "def _emit(event_type, listing_id, data, key):\n"
        "    emitter.emit_background(event_type=event_type, idempotency_key=key)\n"
        "def caller():\n"
        "    _emit('ExchangeTradeExecuted', 'l1', {}, 'trade-1')\n", 4) == "keyed"

    # (5) a callee that reaches NO emitter is not an emit site at all — the
    # _record_canary_event shape, which stamps redis and emits nothing.
    cases["non_emitter_callee_drops_out"] = state_of(
        "def _record_canary_event(event_type, data):\n"
        "    redis.hset('canary', event_type, data)\n"
        "def caller():\n"
        "    _record_canary_event(event_type='TokensTransferred', data={})\n", 4) == "not-an-emit"

    # (6) an UNRESOLVABLE callee must be judged exactly as before — never
    # dropped. A census that discards what it cannot read is the failure this
    # change exists to fix, not a licence to repeat it elsewhere.
    cases["unresolved_callee_stays_keyless"] = state_of(
        "def caller():\n"
        "    some_imported_emit(event_type='TokensTransferred', data={})\n", 2) == "keyless"

    # ── §EVTYPES8 — the SAME resolution, one dimension over ────────────────
    # `emission_sites_name_an_aggregate` excludes wrapper sites in its docstring
    # and implemented that as "has an explicit kwarg". §BATCH7 added
    # `idempotency_key=` to wrapper CALLS, which pulled them back in, and the
    # suite reported admin_agents.py:668 as missing an aggregate while
    # `_emit_admin_action` sets `aggregate_id=f"agent:{did}"` two frames down —
    # an artefact of the instrument, which is what its own docstring warns
    # against. Same three controls as above, because the same two ways to be
    # wrong apply: excuse too much, or excuse what cannot be read.
    def supplies(src: str) -> bool:
        tree = ast.parse(src)
        defs = _local_defs(tree)
        target = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and _kw(n, "event_type")
                  and "emitter.emit" not in _callee(n)]
        return bool(target) and _callee_supplies_aggregate(target[-1], defs)

    cases["wrapper_that_BUILDS_the_aggregate_excuses_its_callers"] = supplies(
        "async def _emit_admin_action(*, event_type, agent_did, data=None, idempotency_key=None):\n"
        "    await emitter.emit(event_type=event_type, aggregate_id=f'agent:{agent_did}', data=data)\n"
        "async def caller():\n"
        "    await _emit_admin_action(event_type='X', agent_did=d, idempotency_key='k')\n") is True

    cases["wrapper_that_only_FORWARDS_does_not_excuse_them"] = supplies(
        "async def _fwd(*, event_type, aggregate_id=None, idempotency_key=None):\n"
        "    await emitter.emit(event_type=event_type, aggregate_id=aggregate_id, data={})\n"
        "async def caller():\n"
        "    await _fwd(event_type='X', idempotency_key='k')\n") is False

    cases["unresolvable_callee_is_never_excused_of_an_aggregate"] = supplies(
        "async def caller():\n"
        "    await some_imported_helper(event_type='X', idempotency_key='k')\n") is False

    failed = sorted(k for k, v in cases.items() if not v)
    return _done(not failed, "callee resolution keys only what is really keyed",
                 {"controls": cases, "failed": failed})


@federation_test(
    name="emission_census_is_reading_real_code",
    category="event_contract",
    budget_sec=90.0,
    severity="critical",
    requires=[],
    tags=["no-probe", "event_emission", "contract", "control"],
)
async def test_census_is_reading_real_code(rig: FederationTestRig) -> AssertionResult:
    """The census must be reading CODE, and enough of it to mean anything.

    The control for the three gates above, and it exists because of a specific
    failure: on 2026-09-04 three separate content checks across two sessions
    matched a docstring or a comment instead of the code it described — one of
    them matched the very comment explaining that the code had been removed.
    A census that silently found nothing would make all three gates above pass
    for the worst possible reason.

    So: assert a substantial population, assert the known-present event types
    are in it, and assert that a string appearing ONLY in prose is not counted.
    """
    # `no-probe`: this is STATIC ANALYSIS, not an integration test — it walks
    # the source tree via _census()/the guard under test and never reaches the
    # tier, so the U1 vacuity verdict must not fire on it. The tag is a claim
    # a reader can check, and U1 is what made the distinction visible: before
    # it, a source-reading gate and a tier probe were indistinguishable rows.
    rows = _census()
    events = {r["event"] for r in rows}
    # Types that must exist in any registry build; if these are missing the
    # census is pointed at the wrong tree or the parse is failing silently.
    # Anchors span BOTH emission shapes on purpose: the first three are keyword
    # emits, `GuildBidPlaced` is positional and was invisible to the old census.
    anchors = {"TokensTransferred", "TokensIssued", "TransactionFeeCollected",
               "AgentCapabilityIssued", "GuildBidPlaced", "ContractCreated"}
    missing_anchors = sorted(anchors - events)
    # A comment/docstring mention must NOT become a census row. `execute_transfer`
    # appears in a docstring in the TEG's bulk path and fooled a text check today;
    # its analogue here is that no census row may carry an unquoted expression.
    prose_leak = [r for r in rows if not r["event"] or " " in r["event"]]
    state = {
        "emit_sites": len(rows),
        "distinct_event_types": len(events),
        "missing_anchor_types": missing_anchors,
        "rows_that_look_like_prose": len(prose_leak),
    }
    # Thresholds raised with the widened census (330 sites / 256 types measured).
    # A census that silently narrowed again would trip this before the three
    # gates above could pass for the wrong reason.
    state["positional_sites"] = sum(1 for r in rows if r.get("how") == "positional")
    ok = (len(rows) >= 300 and len(events) >= 230 and not missing_anchors
          and not prose_leak and state["positional_sites"] >= 80)
    return _done(ok, "the emission census reads real code and finds the known types", state)

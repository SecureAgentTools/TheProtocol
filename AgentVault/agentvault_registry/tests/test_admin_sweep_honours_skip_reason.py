"""A DECLARED `skip_reason` MUST BIND ON THE ADMIN-BRIDGE SWEEP, NOT ONLY THE PUBLIC ONE.

§MCPADMSKIP 2026-09-07. `MCP_CONTRACTS` lets a contract say "do not call this tool,
and here is why". The public sweep reads that field. `_sweep_one_admin` did not: it
took the lifecycle-outcome shortcut and otherwise went straight to a default call,
so 19 admin contracts carrying a deliberate skip were swept anyway — and the run
then reported "cloud-op admin contract_gap — no expect_keys nor outputSchema" for
tools that HAVE a contract explaining why they must not be called.

The one that matters is `adminAgoraDelistListing`, whose reason reads
"DESTRUCTIVE — cancels all orders + refunds escrow (exchange.py:1058); never
blind-sweep". It was blind-swept on every cloud-op run and survived only because
empty args fail validation before the action — i.e. by luck, not by the guard.

Same class as `refusal_contract_can_become_an_action` and the field census before
it: **a declarative field binds exactly the consumers that read it.** So this gate
does not check that the field exists; it checks that THIS consumer reads it, and
reads it BEFORE the call — an ordering no runtime assertion in a green run can see,
because the tools that would prove it are the ones that must not be called.

The control is in the test: it re-runs itself against the PRE-FIX source from git
and requires that version to FAIL. A gate that cannot fail measures nothing.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" /
        "api_tests" / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py")
_FUNCS = ("_sweep_one_admin", "_cloudop_one_admin")
_DEFAULT_CALL = "_mcp_rpc_call_admin"


def _gate(source: str, func: str) -> tuple[bool, str]:
    """(honours_skip_reason, why) for ONE sweep in one version of the source."""
    tree = ast.parse(source)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == func:
            target = node
            break
    if target is None:
        return False, f"{func} not found — it was renamed; re-point this gate"
    _FUNC = func

    skip_lines = [
        n.lineno for n in ast.walk(target)
        if isinstance(n, ast.Attribute) and n.attr == "skip_reason"
    ]
    call_lines = [
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(target) if isinstance(n, ast.Call)
    ]
    default_calls = [
        n.lineno for n in ast.walk(target)
        if isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Name) and n.func.id == _DEFAULT_CALL)
            or getattr(n.func, "attr", "") == _DEFAULT_CALL)
    ]
    if not default_calls:
        return False, (f"no {_DEFAULT_CALL} inside {_FUNC} — the sweep's call site "
                       f"moved, so this gate is measuring the wrong function "
                       f"(calls seen: {sorted(set(call_lines))[:8]})")
    if not skip_lines:
        return False, f"{_FUNC} never reads .skip_reason: a declared skip does not bind here"
    if min(skip_lines) > min(default_calls):
        return False, (f"{_FUNC} reads .skip_reason at line {min(skip_lines)} but calls "
                       f"{_DEFAULT_CALL} first at {min(default_calls)} — the tool is "
                       f"already called by the time the skip is consulted")
    return True, "ok"


def test_admin_sweep_reads_skip_reason_before_calling() -> None:
    """BOTH admin sweeps. The flow is duplicated — frame and cloud-op each have
    their own — and fixing one moved nothing in the other's numbers, which is the
    reason this gate names them explicitly rather than checking "an" admin sweep."""
    src = _SRC.read_text()
    bad = {f: why for f in _FUNCS for ok, why in [_gate(src, f)] if not ok}
    assert not bad, bad


def test_the_gate_fails_on_the_pre_fix_source() -> None:
    """The control: the version before §MCPADMSKIP must NOT pass this gate.

    Skips (loudly) rather than passing if git cannot produce that revision — a
    control that silently vanishes is how a gate stops discriminating without
    anyone noticing.
    """
    rel = "agentvault_registry/src/agentvault_registry/api_tests/categories/flow_mcp_lifecycle/test_flow_mcp_lifecycle.py"
    repo = Path(__file__).resolve().parents[2]
    # ⚠ THE LOUD SKIP BELOW COULD NEVER FIRE IN THE IMAGE. `subprocess.run(["git", …])` RAISES
    # FileNotFoundError when git is not installed, one statement before `proc` exists to be
    # inspected — so the control did not skip loudly, it FAILED, and a red that means "no git
    # here" is indistinguishable from a red that means "the gate stopped discriminating".
    # The production image ships no git (measured: 2 failures on V0281 and V0282 alike).
    try:
        proc = subprocess.run(["git", "-C", str(repo), "show", f"bc83ae9:{rel}"],
                              capture_output=True, text=True)
    except FileNotFoundError:
        import pytest
        pytest.skip("git is not available in this environment (the image ships none) — "
                    "control not run, so this gate is UNPROVEN here; it runs in a full git checkout of this repository "
                    "(CI's image has no git and its clone is --depth 1)")
    if proc.returncode != 0 or not proc.stdout:
        import pytest
        pytest.skip(f"pre-fix revision unavailable here ({proc.stderr.strip()[:120]}) — "
                    f"control not run, so this gate is UNPROVEN in this environment")
    fails = {f: why for f in _FUNCS for ok, why in [_gate(proc.stdout, f)] if not ok}
    assert fails, ("the pre-fix source PASSES this gate for both sweeps, so the gate "
                   "does not discriminate and would not have caught the defect it was "
                   "written for")
    for why in fails.values():
        assert "never reads .skip_reason" in why or "already called" in why, why


def test_the_gate_catches_a_HALF_fix() -> None:
    """The control that matters for a DUPLICATED sweep.

    `c2880b6` fixed the central sweep and not the cloud-op copy, and the cloud-op
    numbers did not move — a fix aimed at one copy looks exactly like a fix that did
    not work. A gate that only asked "does an admin sweep read the field" would have
    gone green on that commit; this one must not.
    """
    rel = "agentvault_registry/src/agentvault_registry/api_tests/categories/flow_mcp_lifecycle/test_flow_mcp_lifecycle.py"
    repo = Path(__file__).resolve().parents[2]
    try:                                  # see the note on the sibling control above
        proc = subprocess.run(["git", "-C", str(repo), "show", f"c2880b6:{rel}"],
                              capture_output=True, text=True)
    except FileNotFoundError:
        import pytest
        pytest.skip("git is not available in this environment (the image ships none) — "
                    "control not run, so this gate is UNPROVEN here; it runs in a full git checkout of this repository "
                    "(CI's image has no git and its clone is --depth 1)")
    if proc.returncode != 0 or not proc.stdout:
        import pytest
        pytest.skip("half-fixed revision unavailable here — control not run")
    results = {f: _gate(proc.stdout, f) for f in _FUNCS}
    assert results["_sweep_one_admin"][0], "the central sweep WAS fixed in c2880b6"
    assert not results["_cloudop_one_admin"][0], (
        "the cloud-op sweep was NOT fixed in c2880b6, so a gate that passes it "
        "cannot see a half-applied fix — which is the failure this leg exists for")

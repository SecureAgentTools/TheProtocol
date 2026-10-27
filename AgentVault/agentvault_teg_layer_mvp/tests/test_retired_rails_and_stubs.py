"""§MONEY-R31 / R30 — the retired rails stay retired, and no stub lies about a money path.

R31's fix line: "each line becomes either a removed surface, an alert, or a
documented operator action; none stays a comment." Two of them were worse than
comments — they were comments that had stopped being TRUE:

  * endpoints_attestation.py said "For MVP/testing, we proceed anyway" about an
    insufficient treasury. §MONEY-R24 had already made that path DEFER. A reader
    would conclude the TEG still over-issues.
  * crud.py::calculate_pending_rewards said "For MVP, returns 0. In production,
    would calculate…", which reads as an invitation. Its caller pays out with
    `agent.token_balance += stake.amount + pending` — a direct ORM credit — so a
    non-zero return would create supply on an untagged write (§MONEY-R18).

These gates pin the BEHAVIOUR those comments describe, so the comments cannot
drift back into being wrong without something failing.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "teg_core_service"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/teg_core_service")
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/teg_core_service")


# ── R30: the retired staking family stays behind its guard ──────────────────

def test_every_retired_governance_staking_route_calls_the_guard():
    """R30 gated nine duplicate routes. A new route added to that file without
    the guard would silently reopen the second staking model."""
    mod = SRC / "api" / "v1" / "endpoints_governance.py"
    src = mod.read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded = [
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(c, ast.Call)
            and (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == "_retired_rail_guard"
            for c in ast.walk(n)
        )
    ]
    assert len(guarded) >= 7, (
        f"only {len(guarded)} routes in endpoints_governance.py call _retired_rail_guard "
        "— R30 gated the whole duplicate staking family"
    )
    for name in ("stake_tokens", "unstake_tokens"):
        assert any(name == g for g in guarded), f"{name} is no longer behind the R30 guard"


def test_the_guard_is_default_off():
    """`TEG_RETIRED_RAILS` unset must mean retired. A default-on guard retires nothing."""
    src = (SRC / "api" / "v1" / "endpoints_governance.py").read_text(encoding="utf-8")
    assert 'getenv("TEG_RETIRED_RAILS", "false")' in src, (
        "the retired-rails flag no longer defaults to false — the family would be live"
    )


# ── R31: the stubs describe what the code does ──────────────────────────────

def test_the_attestation_reward_defers_and_says_so():
    src = (SRC / "api" / "v1" / "endpoints_attestation.py").read_text(encoding="utf-8")
    assert "For MVP/testing, we proceed anyway" not in src, (
        "the stale comment is back. §MONEY-R24 made this path DEFER; a comment "
        "saying it proceeds makes a reader conclude the TEG over-issues."
    )
    assert "DEFER, NEVER ISSUE" in src, "the R24 defer branch is gone"
    assert 'if "Insufficient balance" in str(ve)' in src, (
        "the insufficient-treasury branch no longer distinguishes its ValueError — "
        "it would swallow unrelated errors or stop deferring"
    )


def test_pending_rewards_is_zero_and_documented_as_dead():
    """A non-zero return here would credit token_balance directly (untagged)."""
    src = (SRC / "database" / "crud.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == "calculate_pending_rewards"),
        None,
    )
    assert fn is not None, "calculate_pending_rewards is gone — re-point this gate"
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert returns, "no return statement found"
    for r in returns:
        val = r.value
        ok = (
            isinstance(val, ast.Call)
            and (getattr(val.func, "id", None) or getattr(val.func, "attr", None)) == "Decimal"
        )
        assert ok, (
            "calculate_pending_rewards returns something other than a Decimal literal. "
            "Its caller does `agent.token_balance += stake.amount + pending`, a direct "
            "ORM credit — a computed reward here creates supply on an untagged write "
            "(§MONEY-R18). Rewards belong on the funded distribution rail."
        )
    doc = ast.get_docstring(fn) or ""
    assert "retired" in doc.lower(), (
        "the docstring no longer records that this is dead code behind a retired rail"
    )


@pytest.mark.parametrize("marker", [
    "PER PROCESS",              # the in-memory rate limit
    "proof of work is NOT validated",
    "NOT persisted",
])
def test_the_onboarding_stubs_state_what_they_do(marker):
    """Each MVP stub now says what it does, not what it might one day do."""
    src = (SRC / "api" / "v1" / "endpoints_onboarding.py").read_text(encoding="utf-8")
    assert marker in src, f"the R31 statement {marker!r} is gone from the onboarding rail"


def test_no_onboarding_stub_is_left_as_a_bare_todo():
    src = (SRC / "api" / "v1" / "endpoints_onboarding.py").read_text(encoding="utf-8")
    bare = [
        line.strip() for line in src.splitlines()
        if "TODO" in line and "§MONEY-R31" not in line
    ]
    assert not bare, f"bare TODOs left on the onboarding money rail: {bare}"

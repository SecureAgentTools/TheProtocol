"""§MONEY-R15 — a deletion forfeits the money it can actually move, and says so.

The purge used to request `liquid + staked` in ONE call to the TEG's
`/admin/treasury/receive`. That endpoint validates against `token_balance`,
which is LIQUID only:

    if source.token_balance < request.amount: -> 400

so for any agent holding stake the drain was REFUSED and the deletion forfeited
NOTHING — not even the liquid part — while the report counted a drain failure.
The comment beside the call already said "drains liquid only"; the code asked for
both. Measured on frame-a when this was found: 11 of 4,191 agents hold stake.

Δ was never at risk — a refused call moves nothing. What was wrong is that the
forfeiture did not happen and the report did not say which part was missing.

The staked balance is genuinely unforfeitable by this rail (locked behind the
unstake cooldown, and the credential is being wiped), so it is now reported under
its own key rather than counted as money that moved.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/agentvault_registry")
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/agentvault_registry")

MOD = SRC / "routers" / "account_deletion.py"


@pytest.fixture(scope="module")
def purge_fn():
    tree = ast.parse(MOD.read_text(encoding="utf-8"))
    fns = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(c, ast.Call)
            and (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == "_teg_drain_to_treasury"
            for c in ast.walk(n)
        )
    ]
    assert len(fns) == 1, f"expected exactly one caller of _teg_drain_to_treasury, found {len(fns)}"
    return fns[0]


def _drain_calls(fn):
    return [
        c for c in ast.walk(fn)
        if isinstance(c, ast.Call)
        and (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == "_teg_drain_to_treasury"
    ]


def test_the_drain_asks_for_liquid_only(purge_fn):
    """The amount argument must be the liquid name, never a liquid+staked sum."""
    calls = _drain_calls(purge_fn)
    assert calls, "no drain call found — re-point this gate"
    for c in calls:
        amount = c.args[1] if len(c.args) > 1 else None
        assert amount is not None, "the drain is called without a positional amount"
        assert not isinstance(amount, ast.BinOp), (
            "the drain amount is an expression (liquid + staked?). /admin/treasury/receive "
            "validates against token_balance — LIQUID — so a sum is refused and the "
            "deletion forfeits nothing at all."
        )
        assert isinstance(amount, ast.Name) and "liquid" in amount.id, (
            f"the drain amount should be the liquid balance, got {ast.dump(amount)[:80]}"
        )


def test_staked_is_reported_separately_not_as_forfeited(purge_fn):
    src = ast.get_source_segment(MOD.read_text(encoding="utf-8"), purge_fn) or ""
    assert "avt_staked_not_forfeited" in src, (
        "staked must be reported under its own key — folding it into avt_forfeited "
        "reports money as moved that is merely stranded"
    )


def test_the_report_declares_both_keys():
    src = MOD.read_text(encoding="utf-8")
    for key in ('"avt_forfeited"', '"avt_staked_not_forfeited"'):
        assert key in src, f"{key} missing from the deletion report"


def test_a_refused_drain_is_counted_not_swallowed(purge_fn):
    src = ast.get_source_segment(MOD.read_text(encoding="utf-8"), purge_fn) or ""
    assert "teg_drain_failures" in src, "a refused drain must still be counted"

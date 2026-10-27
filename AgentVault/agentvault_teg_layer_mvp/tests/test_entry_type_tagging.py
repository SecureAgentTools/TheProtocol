"""§MONEY-R18 — the ordinary transfer path must not emit kind='unknown'.

MEASURED on the live EventStore 2026-09-04, which is why this exists:

    kind='unknown'   4,661,352 LedgerBalanceChanged events, the single largest
                     class, still arriving today; 1,794,963 with net != 0.

Those are single-sided legs of ordinary fee-bearing transfers (sender -0.0105,
receiver +0.010, fee_collector +0.0005) and their counterparts sit in other
buckets, so Δ=0.0 held throughout — this was never a leak. It is a BLIND SPOT:
everything untagged lands in transit_net beside legitimate transfers, so an
untagged mover that really did create or destroy money would move transit_net
and total_circulating together and Δ would stay 0.0. Invisible, exactly like a
dropped TokensTransferred.

Δ behaviour is UNCHANGED by tagging: materialized_balances.sql sends
'mint'/'dispute_comp' to tokens_issued, 'slash'/'burn' to tokens_destroyed, and
everything else — 'unknown' and 'transfer' alike — to transit_net.

⚠ The money plan also proposed "the outbox refuses a balance change without an
entry_type". Applied before this tagging, that would REFUSE THE MAIN TRANSFER
PATH. Tag every legitimate mover first; refuse last.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest


def _crud_src() -> str:
    here = pathlib.Path(__file__).resolve().parents[1]
    for cand in (here / "src" / "teg_core_service" / "database" / "crud.py",
                 pathlib.Path("/app/src/teg_core_service/database/crud.py")):
        if cand.is_file():
            return cand.read_text()
    pytest.skip("crud.py not found in either the repo or image layout")


def _default_of(fn_name: str, arg: str):
    tree = ast.parse(_crud_src())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name)
    args = fn.args.args + fn.args.kwonlyargs
    defaults = list(fn.args.defaults)
    # positional defaults align to the TAIL of args
    pos = {a.arg: d for a, d in zip(args[len(args) - len(defaults):], defaults)}
    assert arg in pos, f"{fn_name} has no default for {arg!r}"
    return pos[arg]


def test_execute_transfer_tags_by_default():
    """The default was None — 'unchanged for every caller' — which is precisely
    how the busiest money rail came to be labelled 'unknown' 4.6M times."""
    d = _default_of("execute_transfer", "entry_type")
    assert isinstance(d, ast.Constant), "entry_type default is no longer a literal"
    assert d.value is not None, (
        "execute_transfer's entry_type defaults to None again — every untagged "
        "transfer will be emitted as kind='unknown' and the bucket stops meaning anything"
    )
    assert d.value == "transfer", f"unexpected default tag {d.value!r}"


def test_the_tag_is_still_actually_applied():
    """A default is worth nothing if the `if entry_type:` guard were removed."""
    src = _crud_src()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "execute_transfer")
    body = ast.unparse(fn)
    assert "teg.entry_type" in body, "execute_transfer no longer stamps the GUC"
    assert "set_config" in body, "the GUC must be set via set_config (SET LOCAL cannot bind a param)"


def test_issuance_still_tags_mint():
    """Guard the neighbour: 'mint' is the tag the invariant routes to tokens_issued.
    If this ever regressed, minted supply would land in transit_net and Δ WOULD break."""
    src = _crud_src()
    assert "teg.entry_type = 'mint'" in src, "execute_issuance no longer tags 'mint'"


def test_an_explicit_none_from_a_wrapper_still_tags():
    """The regression that a signature default alone did NOT catch.

    First attempt changed only `execute_transfer`'s own default and deployed it.
    Verified live afterwards: post-deploy LedgerBalanceChanged events still read
    kind='unknown'. Cause — EnhancedTransferService.execute_transfer carries its
    own `entry_type: Optional[str] = None` and forwards it EXPLICITLY, and an
    explicit None beats a callee default.

    So the tag must be resolved at the point of USE, not in the signature. This
    asserts set_config receives the COALESCED value; if someone reverts it to the
    raw parameter, a wrapper can silently defeat the tagging again.
    """
    src = _crud_src()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "execute_transfer")
    body = ast.unparse(fn)
    assert '_entry_type = entry_type or' in body, (
        "execute_transfer no longer coalesces entry_type at the point of use — a "
        "wrapper forwarding an explicit None will emit kind='unknown' again"
    )
    assert "'et': _entry_type[:48]" in body or '"et": _entry_type[:48]' in body, (
        "set_config is being handed the RAW parameter again, not the coalesced value"
    )


def test_the_enhanced_wrapper_defaults_too():
    """Belt as well as braces: the wrapper is the live path (TEG emission is
    blocked there), so its signature should say what it does."""
    here = pathlib.Path(__file__).resolve().parents[1]
    for cand in (here / "src" / "teg_core_service" / "transfer_service_enhanced.py",
                 pathlib.Path("/app/src/teg_core_service/transfer_service_enhanced.py")):
        if cand.is_file():
            src = cand.read_text(); break
    else:
        pytest.skip("transfer_service_enhanced.py not found")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "execute_transfer")
    args = fn.args.args + fn.args.kwonlyargs
    defaults = list(fn.args.defaults)
    pos = {a.arg: d for a, d in zip(args[len(args) - len(defaults):], defaults)}
    d = pos.get("entry_type")
    assert isinstance(d, ast.Constant) and d.value == "transfer", (
        f"EnhancedTransferService.execute_transfer entry_type default is {getattr(d,'value',d)!r}, "
        "not 'transfer' — this is the wrapper that defeated the first fix"
    )


# ══ §MONEY-R24 / R20 — the TEG stops creating supply on two more rails ══════

def _teg_src(rel: str) -> str:
    here = pathlib.Path(__file__).resolve().parents[1]
    for cand in (here / "src" / "teg_core_service" / rel,
                 pathlib.Path("/app/src/teg_core_service") / rel):
        if cand.is_file():
            return cand.read_text()
    pytest.skip(f"{rel} not found")


def test_r24_attestation_reward_never_issues_directly():
    """It used to read "For MVP/testing, issue tokens directly" and do
    `agent.token_balance += reward_amount` on an insufficient-treasury error —
    supply from nothing, untagged, so Δ stayed 0.0 and nothing could see it."""
    src = _teg_src("api/v1/endpoints_attestation.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "submit_attestation")
    muts = [n for n in ast.walk(fn)
            if isinstance(n, ast.AugAssign) and "token_balance" in ast.unparse(n.target)]
    assert not muts, (
        f"submit_attestation credits token_balance directly again at line(s) "
        f"{[m.lineno for m in muts]} — that creates supply the invariant cannot see"
    )
    assert "DEFERRED" in ast.unparse(fn), "the deferred path lost its operator-facing log"


def test_r20_reward_cycle_gate_precedes_the_distribution():
    """Structural, not textual: the 501 must come BEFORE distribute_staking_rewards,
    or the supply-creating call still runs and only the response is refused."""
    src = _teg_src("api/v1/endpoints_governance.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "trigger_reward_cycle")
    gate = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "TEG_STAKING_REWARD_CYCLE_ENABLED" in n.value]
    call = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "distribute_staking_rewards"]
    assert gate, "the reward cycle is no longer gated"
    assert call, "test aimed at the wrong function"
    assert min(gate) < min(call), (
        f"the gate (L{min(gate)}) must precede distribute_staking_rewards (L{min(call)})"
    )
    assert "501" in ast.unparse(fn), "the refusal is no longer a 501"


# ══ §MONEY-R30 — the TEG's duplicate governance-staking family is retired ═══

def test_r30_every_retired_route_guards_before_it_works():
    """The guard must be the FIRST executable statement of each route.

    A guard placed anywhere else would let the route do its work and only then
    refuse — which for a staking rail means moving stake and returning a 404.
    Docstrings are allowed ahead of it; nothing else is.
    """
    src = _teg_src("api/v1/endpoints_governance.py")
    tree = ast.parse(src)
    targets = ["stake_tokens", "unstake_tokens", "get_my_stakes", "get_staking_summary",
               "get_all_stakes", "create_delegation", "get_my_delegations", "end_delegation",
               "get_validator_delegations"]
    for name in targets:
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        body = [b for b in fn.body
                if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
        first = body[0]
        assert (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Name)
                and first.value.func.id == "_retired_rail_guard"), (
            f"{name}: the retired-rail guard is not the first executable statement"
        )


def test_r30_leaves_the_registrys_real_staking_rail_alone():
    """`/tokenomics/lock` and `/tokenomics/unlock` ARE the registry's staking rail
    (teg_client.stake_tokens -> lock_tokens). Gating them would break real staking,
    so this asserts the guard was NOT applied to that module."""
    src = _teg_src("api/v1/endpoints_tokenomics_enhanced.py")
    assert "_retired_rail_guard" not in src, (
        "the retirement guard reached the tokenomics module — that is the LIVE rail"
    )


def test_r30_trigger_reward_cycle_keeps_its_own_gate():
    """R20 gates it on its own flag because it CREATES supply; R30's flag is about
    a duplicate model. Collapsing the two would let TEG_RETIRED_RAILS re-arm a
    supply-creating rail."""
    src = _teg_src("api/v1/endpoints_governance.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "trigger_reward_cycle")
    body = ast.unparse(fn)
    assert "TEG_STAKING_REWARD_CYCLE_ENABLED" in body, "R20's own gate is gone"
    assert "_retired_rail_guard" not in body, (
        "trigger_reward_cycle now rides TEG_RETIRED_RAILS — that flag would re-arm "
        "a supply-creating rail along with the harmless ones"
    )

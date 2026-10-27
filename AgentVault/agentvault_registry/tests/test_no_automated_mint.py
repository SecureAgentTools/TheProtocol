"""§MONEY-R19 / D9 — a provisioning shortfall must not create money by itself.

`cross_teg_treasury_fund` used to POST the TEG's /admin/token/issue whenever the
mainframe treasury could not cover an operator seed. That is a supply decision
taken by plumbing, with no human in the loop and no registry-side TokensIssued
event (PART 3 makes the registry the only legitimate emitter of that type).

⚠ It did NOT breach Δ — execute_issuance tags `teg.entry_type='mint'`, the L2
outbox emits kind='mint', and materialized_balances.sql books it into
tokens_issued, so the invariant held. The defect is that supply grew without a
decision, which is noise against ~1e9 and the entire economy on a low-supply net.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

from agentvault_registry.routers import teg_integration as tg


# ── the flag ────────────────────────────────────────────────────────────────

def test_mint_on_demand_is_off_by_default(monkeypatch):
    monkeypatch.delenv("TREASURY_MINT_ON_DEMAND_ENABLED", raising=False)
    assert tg._mint_on_demand_enabled() is False


@pytest.mark.parametrize("v", ["true", "TRUE", "1", "yes", "on", " true "])
def test_mint_on_demand_opt_in_words(monkeypatch, v):
    monkeypatch.setenv("TREASURY_MINT_ON_DEMAND_ENABLED", v)
    assert tg._mint_on_demand_enabled() is True


@pytest.mark.parametrize("v", ["false", "0", "no", "off", "", "maybe"])
def test_mint_on_demand_everything_else_is_off(monkeypatch, v):
    monkeypatch.setenv("TREASURY_MINT_ON_DEMAND_ENABLED", v)
    assert tg._mint_on_demand_enabled() is False


# ── the wiring: the refusal must DOMINATE the mint ──────────────────────────

def _fund_fn():
    src = pathlib.Path(tg.__file__).read_text()
    tree = ast.parse(src)
    return next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "cross_teg_treasury_fund"
    )


def test_the_mint_is_gated_and_the_gate_comes_first():
    """Structural, not textual: the flag check must appear BEFORE the mint POST.

    A test that merely asserted 'the file mentions the flag' would stay green if
    the guard were moved below the mint, which is exactly the mistake that would
    reintroduce the defect.
    """
    fn = _fund_fn()
    body = ast.unparse(fn)
    assert "admin/token/issue" in body, "test aimed at the wrong function"

    gate_lines = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_mint_on_demand_enabled"
    ]
    assert gate_lines, "the mint is no longer gated by _mint_on_demand_enabled()"

    # CODE only — the function's docstring also names /admin/token/issue, and
    # matching documentation is the same wrong-property mistake in miniature
    # (this test caught it on its first run).
    doc_node = fn.body[0] if (fn.body and isinstance(fn.body[0], ast.Expr)
                              and isinstance(fn.body[0].value, ast.Constant)
                              and isinstance(fn.body[0].value.value, str)) else None
    mint_lines = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and "admin/token/issue" in n.value
        and not (doc_node is not None and n is doc_node.value)
    ]
    assert mint_lines, "could not locate the mint POST"
    assert min(gate_lines) < min(mint_lines), (
        f"the flag check (line {min(gate_lines)}) must precede the mint "
        f"(line {min(mint_lines)}) — otherwise the mint runs before the gate"
    )


def test_the_refusal_is_a_409_that_names_the_operator_action():
    """A 503 would read as 'try again later'. This is 'a human must decide'."""
    fn = _fund_fn()
    body = ast.unparse(fn)
    assert "HTTP_409_CONFLICT" in body, "the shortfall refusal must be a 409"
    assert "issue units first" in body, (
        "the refusal must name what the operator has to do; a bare 'treasury "
        "short' leaves them guessing"
    )


def test_the_counter_exists_and_is_labelled():
    c = tg.TREASURY_SHORTFALL_REFUSED
    if c is None:
        pytest.skip("prometheus_client absent in this image — degraded by design")
    # prometheus_client strips the _total suffix on a Counter's internal _name;
    # the EXPOSED series is registry_treasury_shortfall_refused_total.
    assert c._name == "registry_treasury_shortfall_refused"
    assert c._labelnames == ("reason",)


# ══ §MONEY-R23 — lost-callback compensation pays from the treasury ══════════

import types
import uuid as _uuid

from agentvault_registry.tasks import settlement_reconciliation as sr


class _Settlement:
    def __init__(self):
        self.id = 4242
        self.dispute_id = 77
        self.complainant_did = f"did:theprotocol:{_uuid.uuid4()}"
        self.status = "PENDING"
        self.slashed_amount = None
        self.minted_amount = None
        self.mint_tx_id = None
        self.slash_tx_id = None
        self.settled_at = None
        self.error_message = None


class _Db:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def test_the_minting_path_is_gone_from_the_module():
    """CODE, not comments — the docstring deliberately still describes the old path."""
    tree = ast.parse(pathlib.Path(sr.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_compensate_from_slash_evidence")
    doc = fn.body[0].value if (fn.body and isinstance(fn.body[0], ast.Expr)
                               and isinstance(fn.body[0].value, ast.Constant)) else None
    code_strings = [
        n.value for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not doc
    ]
    assert not any("admin/token/issue" in c for c in code_strings), \
        "the compensation path mints again"
    assert not hasattr(sr, "_auto_mint_from_slash_evidence"), \
        "the old minting function is still reachable"


def test_it_must_not_emit_a_mint_event_while_paying_by_transfer():
    """The Δ trap this change had to avoid.

    A treasury transfer is Δ-neutral. DisputeCompensationMinted is classified
    `dispute_comp`, which materialized_balances.sql books into tokens_issued.
    Emitting it alongside a transfer would raise tokens_issued while circulating
    stayed flat — converting a safe path into a REAL Δ breach. If someone ever
    re-adds the emit without restoring the mint, this goes red.
    """
    src = pathlib.Path(sr.__file__).read_text()
    tree = ast.parse(src)
    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    } | {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "emit_dispute_compensation_minted" not in called, (
        "a mint event is emitted on a path that only transfers — tokens_issued "
        "would rise while circulating stays flat (Δ breach)"
    )


@pytest.mark.asyncio
async def test_it_pays_via_the_waterfall_with_a_deterministic_key(monkeypatch):
    seen = {}

    async def fake_fund(db, request, actor_label, idempotency_key=None):
        seen["reason"] = request.reason
        seen["amount"] = request.amount
        seen["did"] = request.target_agent_did
        seen["idem"] = idempotency_key
        seen["actor"] = actor_label
        return {"transaction_id": "tx-comp-1"}

    monkeypatch.setattr(
        "agentvault_registry.routers.teg_integration._fund_agent_from_treasury_internal",
        fake_fund,
    )
    st, db = _Settlement(), _Db()
    await sr._compensate_from_slash_evidence(db, st, {"amount": 12, "slash_tx_id": "s-1"})

    assert seen["reason"] == "dispute_compensation"
    assert seen["amount"] == "12"
    # Deterministic: a re-drive replays instead of paying twice. uuid4() here was
    # the whole defect.
    assert seen["idem"] == f"ddr-comp-{st.id}"
    assert st.status == "SETTLED"
    assert st.mint_tx_id == "tx-comp-1"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_a_dry_treasury_does_not_fall_back_to_minting(monkeypatch):
    """D9: a treasury that cannot pay is an operator decision, not a reason to
    create supply. The settlement must stay unsettled for retry/admin review."""
    async def boom(db, request, actor_label, idempotency_key=None):
        raise RuntimeError("treasury exhausted")

    monkeypatch.setattr(
        "agentvault_registry.routers.teg_integration._fund_agent_from_treasury_internal",
        boom,
    )
    st, db = _Settlement(), _Db()
    await sr._compensate_from_slash_evidence(db, st, {"amount": 12, "slash_tx_id": "s-1"})

    assert st.status == "PENDING", "a failed payment must not mark the settlement settled"
    assert st.settled_at is None
    assert db.commits == 0


# ══ §MONEY-R22 — a dead rail that would double-book if repaired ════════════

def test_r22_claim_rewards_refuses_before_reaching_the_teg():
    """This one WOULD have breached Δ if repaired: it emits
    `TokensIssued reason=reward_claim` for rewards the waterfall already paid as
    `TokensTransferred` — tokens_issued up, no matching balance movement.

    The gate must precede any teg_client call, or a repair to teg_client silently
    re-arms it."""
    from agentvault_registry.routers import staking_enhanced as se
    tree = ast.parse(pathlib.Path(se.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "claim_staking_rewards")
    gate = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "REGISTRY_STAKING_CLAIM_REWARDS_ENABLED" in n.value]
    assert gate, "claim-rewards is no longer gated"
    body = ast.unparse(fn)
    assert "HTTP_404_NOT_FOUND" in body, "the refusal must be a 404 (the route reads as gone)"
    teg = [n.lineno for n in ast.walk(fn)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and "claim_rewards" in n.func.attr]
    if teg:
        assert min(gate) < min(teg), (
            f"the gate (L{min(gate)}) must precede the teg_client call (L{min(teg)})"
        )


# ══ §MONEY-R21 — the slash reports honestly; the ARITHMETIC is untouched ═════

def test_r21_slash_still_only_touches_the_cache_and_says_so():
    """This residue's money half is HIS decision (HARD STOP 4: making slashes real
    moves money on the live fleet the moment enforcement fires). So this asserts
    TWO things, and the second matters as much as the first:

      1. the log no longer claims a slash that did not happen, and
      2. the arithmetic is UNCHANGED — same cap, same subtraction.

    A "reporting only" change that quietly altered the amount would be far worse
    than the lie it replaced.
    """
    from agentvault_registry.services import enforcement_engine as ee
    src = pathlib.Path(ee.__file__).read_text()
    tree = ast.parse(src)

    # (2) behaviour: the cap and the subtraction survive, unchanged
    caps = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "min"
            and "action.amount" in ast.unparse(n)]
    assert len(caps) >= 2, "the cache-cap arithmetic changed — this was meant to be reporting-only"

    # (1) reporting: the old sentence claimed money was taken.
    #
    # AST, not substring — a `in src` check matched the COMMENT that quotes the
    # old line, which is the fourth time in one session a text check of mine hit
    # documentation instead of code. Only strings actually passed to a logger
    # count.
    log_strings = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("info", "warning", "error", "debug", "exception"):
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    log_strings.append(a.value)
                elif isinstance(a, ast.JoinedStr):
                    log_strings.append(ast.unparse(a))
    joined = "\n".join(log_strings)
    assert "Slashed" not in joined, (
        f"a logger call claims a slash again: {[l for l in log_strings if 'Slashed' in l]}"
    )
    assert any("REGISTRY CACHE" in l for l in log_strings), (
        "no logger call says the slash touched the cache only"
    )
    assert ee.ENFORCEMENT_CACHE_ONLY_SLASH is None or \
        ee.ENFORCEMENT_CACHE_ONLY_SLASH._name == "registry_enforcement_cache_only_slash", \
        "the cache-only slash counter is missing"

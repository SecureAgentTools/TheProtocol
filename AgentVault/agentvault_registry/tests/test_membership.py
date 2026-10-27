"""§MEMBERSHIP (2026-10-02) — the membership rule, pure: knobs, qualification, tenure weight, and the line
that no Unit, lock or point may ever weigh a vote.

No database here (tests/test_membership_db.py drives the SQL against a real Postgres). Every structural
assertion has a control that must fail on a planted violation, so a scanner that finds nothing is proven
able to find something.
"""
from __future__ import annotations

import ast
import datetime as dt
import textwrap
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "agentvault_registry"
UTC = dt.timezone.utc
T0 = dt.datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def m():
    sys.path.insert(0, str(SRC.parent))
    from agentvault_registry.services import membership as mod
    return mod


@pytest.fixture(autouse=True)
def _clean_knobs(monkeypatch, m):
    for k in ("GOVERNANCE_WEIGHT_MODE", "GOVERNANCE_PRESENCE_MODE", "GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS",
              "GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", "GOVERNANCE_MEMBER_TENURE_FULL_DAYS", "NETWORK_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    m._np.reset_cache()
    yield
    m._np.reset_cache()


def _row(**kw):
    base = {"status": "locked", "funded_by": "self", "locked_at": T0, "matured_at": None,
            "agent_status": "active", "enforcement_status": "active"}
    base.update(kw)
    return base


# ── knobs: the default is today's behaviour ──────────────────────────────────

def test_weight_mode_defaults_to_lock_and_a_typo_keeps_lock(m, monkeypatch):
    assert m.weight_mode() == "lock" and not m.member_mode()
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    assert m.member_mode()
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "memebr")
    assert m.weight_mode() == "lock", "an unknown mode must keep today's weights, never switch them"


def test_presence_defaults_off_and_a_typo_is_conditional_not_off(m, monkeypatch):
    assert m.presence_mode() == "off"
    monkeypatch.setenv("GOVERNANCE_PRESENCE_MODE", "required")
    assert m.presence_mode() == "required"
    monkeypatch.setenv("GOVERNANCE_PRESENCE_MODE", "requried")
    assert m.presence_mode() == "conditional", "a typo must not silently switch the confirmation off"


def test_member_knob_defaults(m, monkeypatch):
    assert m.min_bond_age_days() == 30
    assert m.requires_matured_bond() is False
    assert m.tenure_full_days() == 365
    monkeypatch.setenv("GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", "-4")
    assert m.min_bond_age_days() == 0, "a negative age is clamped, never a membership before the bond"
    monkeypatch.setenv("GOVERNANCE_MEMBER_TENURE_FULL_DAYS", "0")
    assert m.tenure_full_days() == 1, "a zero tenure would divide by zero; it is clamped to a day"


# ── tenure weight ─────────────────────────────────────────────────────────────

def test_weight_runs_from_one_to_two_and_stops(m):
    assert m.weight_for(T0, T0, 365) == 1.0
    assert m.weight_for(T0, T0 + dt.timedelta(days=182.5), 365) == 1.5
    assert m.weight_for(T0, T0 + dt.timedelta(days=365), 365) == 2.0
    assert m.weight_for(T0, T0 + dt.timedelta(days=4000), 365) == 2.0, "tenure caps at 2.0"
    assert m.weight_for(T0, T0 - dt.timedelta(days=3), 365) == 1.0, "a clock behind the start is not a negative weight"
    assert m.points_for(1.37) == 137 and m.POINTS_PER_WEIGHT == 100


# ── which bond makes a member ─────────────────────────────────────────────────

def test_a_self_funded_locked_bond_qualifies_after_the_minimum_age(m):
    at, reasons = m.bond_qualifies_at(_row(), min_age_days=30, requires_matured=False)
    assert reasons == [] and at == T0 + dt.timedelta(days=30)
    at, _ = m.bond_qualifies_at(_row(funded_by="wallet", status="matured"), min_age_days=0, requires_matured=False)
    assert at == T0


@pytest.mark.parametrize("row,code", [
    ({"funded_by": "treasury"}, "bond_funded_by_treasury"),
    ({"status": "released"}, "bond"),
    ({"status": "forfeited"}, "bond"),
    ({"status": "voided"}, "bond"),
    ({"funded_by": None}, "bond"),
    ({"enforcement_status": "suspended"}, "agent_suspended"),
    ({"agent_status": "revoked"}, "agent_suspended"),
])
def test_a_bond_that_does_not_make_a_member_says_why(m, row, code):
    at, reasons = m.bond_qualifies_at(_row(**row), min_age_days=30, requires_matured=False)
    assert at is None and code in reasons


def test_the_matured_knob_counts_only_matured_bonds_and_from_their_maturity(m):
    at, reasons = m.bond_qualifies_at(_row(), min_age_days=30, requires_matured=True)
    assert at is None and reasons == ["bond_matured"]
    matured = T0 + dt.timedelta(days=45)
    at, reasons = m.bond_qualifies_at(_row(status="matured", matured_at=matured), min_age_days=30,
                                      requires_matured=True)
    assert reasons == [] and at == matured, "membership begins at maturity when that is later than the age rule"


def test_member_since_is_the_earliest_qualifying_bond_that_has_come(m):
    now = T0 + dt.timedelta(days=40)
    rows = [
        _row(locked_at=T0 + dt.timedelta(days=5)),                        # qualifies day 35
        _row(locked_at=T0),                                               # qualifies day 30: earliest
        _row(locked_at=T0 - dt.timedelta(days=90), funded_by="treasury"),  # never
        _row(locked_at=T0 + dt.timedelta(days=20)),                       # day 50: not yet
    ]
    assert m.member_since_from_rows(rows, now=now, min_age_days=30, requires_matured=False) == T0 + dt.timedelta(days=30)
    assert m.member_since_from_rows(rows[3:], now=now, min_age_days=30, requires_matured=False) is None
    assert m.member_since_from_rows([], now=now, min_age_days=30, requires_matured=False) is None


# ── the line: no balance, lock or point ever weighs a vote ────────────────────

FORBIDDEN_NAMES = {
    "staked_balance", "liquid_balance", "token_balance", "locked_balance",
    "Stake", "OrgSharePosition", "vetoken_calculator", "VeTokenCalculator",
}
FORBIDDEN_TABLES = ("stakes", "org_share_positions", "agent_teg_profiles", "materialized_balances")


def _violations(source: str) -> list:
    """Names and SQL that would let holdings into a membership decision."""
    found = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = [a.name for a in node.names]
            if "vetoken" in mod or "exchange" in mod or any(n in FORBIDDEN_NAMES for n in names):
                found.append(f"import {mod}:{names}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            if any(k in low for k in ("select", "from ", "join ")):
                for t in FORBIDDEN_TABLES:
                    if f" {t} " in f" {low} ".replace("\n", " ") or f"{t}." in low:
                        found.append(f"sql:{t}")
                for col in ("staked_balance", "liquid_balance", "token_balance"):
                    if col in low:
                        found.append(f"sql:{col}")
    return found


@pytest.mark.parametrize("rel", ["services/membership.py", "routers/membership.py",
                                 "services/governance_presence.py"])
def test_membership_reads_no_holdings(rel):
    src = (SRC / rel).read_text(encoding="utf-8")
    assert _violations(src) == [], f"{rel} reads holdings: {_violations(src)}"


def test_the_holdings_scanner_can_fail():
    planted = [
        "x = agent.staked_balance\n",
        "from ..services.vetoken_calculator import vetoken_calculator\n",
        "q = 'SELECT amount FROM stakes WHERE agent_did = :d'\n",
        "q = 'SELECT qty FROM org_share_positions p JOIN agents a ON a.did = p.holder_did'\n",
        "q = \"SELECT liquid_balance FROM agents\"\n",
    ]
    for src in planted:
        assert _violations(src), f"the scanner missed a planted holding read: {src!r}"
    assert _violations("x = 'released'\n") == [], "a harmless string is not a violation"


def test_member_vote_path_in_crud_reads_no_holdings():
    """The member branch of cast_vote and its helpers must not reach for a lock or a balance."""
    src = (SRC / "crud" / "crud_governance.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    for name in ("member_vote_weight", "developer_vote_on", "precheck_member_vote"):
        assert name in funcs, f"{name} is missing from crud_governance"
        seg = ast.get_source_segment(src, funcs[name]) or ""
        assert _violations(seg) == [], f"{name} reads holdings: {_violations(seg)}"
    cast = ast.get_source_segment(src, funcs["cast_vote"]) or ""
    member_branch = cast.split("if _membership.member_mode():", 1)[1].split("# P3/D2: Calculate veToken", 1)[0]
    assert "voting_power=points" in member_branch
    # a fragment of a function body: re-wrap it so the scanner parses statements, not an indentation error
    wrapped = "async def _member_branch():\n" + textwrap.indent(textwrap.dedent(member_branch), "    ")
    assert _violations(wrapped) == [], f"the member branch reads holdings: {_violations(wrapped)}"

"""§MEMBERSHIP phase B (2026-10-02) — the commons tally and its rules, pure (no database).

The tally is the whole fairness of the commons: the median of the points a submission received from at least N
members, never points from its own developer, each developer capped, what is not awarded left where it is. Every
structural assertion has a control that must fail on a planted violation.
"""
from __future__ import annotations

import ast
import datetime as dt
import pathlib
import sys
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "agentvault_registry"


@pytest.fixture(scope="module")
def c():
    sys.path.insert(0, str(SRC.parent))
    from agentvault_registry.services import commons as mod
    return mod


@pytest.fixture(autouse=True)
def _clean(monkeypatch, c):
    for k in ("COMMONS_ENABLED", "COMMONS_FEE_SHARE_PERCENT", "COMMONS_RECIPIENT_CAP_PERCENT",
              "COMMONS_MIN_VOTERS_PER_SUBMISSION", "COMMONS_MAX_SUBMISSIONS_PER_DEVELOPER", "COMMONS_MAX_BUDGET",
              "NETWORK_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    c._np.reset_cache()
    yield
    c._np.reset_cache()


def S(i, dev, did=None):
    return {"id": i, "developer_id": dev, "submitter_did": did or f"did:a{i}", "status": "submitted"}


def B(dev, **alloc):
    return {"voter_developer_id": dev, "allocations": {k.lstrip("s"): v for k, v in alloc.items()}}


def rows(result):
    return {r["submission_id"]: r for r in result["rows"]}


def test_knob_defaults_are_off_and_conservative(c, monkeypatch):
    assert c.commons_enabled() is False
    assert c.fee_share_percent() == Decimal("50") and c.recipient_cap_percent() == Decimal("20")
    assert c.min_voters() == 2 and c.max_submissions_per_developer() == 5 and c.max_budget() is None
    monkeypatch.setenv("COMMONS_FEE_SHARE_PERCENT", "250")
    assert c.fee_share_percent() == Decimal("100"), "a share above 100 % is clamped"
    monkeypatch.setenv("COMMONS_RECIPIENT_CAP_PERCENT", "0")
    assert c.recipient_cap_percent() == Decimal("1"), "a zero cap would pay nobody; it is clamped to 1 %"
    with pytest.raises(c.CommonsRefusal) as e:
        c.require_enabled()
    assert e.value.status_code == 403 and "is not enabled on this registry" in e.value.message


def test_median_of_the_points_decides_and_shares_fill_the_budget(c):
    subs = [S(1, 10), S(2, 20)]
    ballots = [B(30, s1=60, s2=40), B(40, s1=50, s2=50), B(50, s1=90, s2=10)]
    r = c.tally(subs, ballots, budget=Decimal("1000"), cap_percent=Decimal("100"), min_voters_needed=2)
    rr = rows(r)
    assert rr[1]["median_points"] == Decimal("60") and rr[2]["median_points"] == Decimal("40")
    assert rr[1]["amount"] == Decimal("600.000000") and rr[2]["amount"] == Decimal("400.000000")
    assert r["awarded"] == Decimal("1000") and r["unallocated"] == Decimal("0")


def test_a_small_ring_cannot_steer_the_median(c):
    """Two members flood their friend's work with 100 points; three others give it 10. The median holds at 10."""
    subs = [S(1, 10), S(2, 20)]
    ballots = [B(31, s1=100), B(32, s1=100), B(33, s1=10, s2=90), B(34, s1=10, s2=90), B(35, s1=10, s2=90)]
    rr = rows(c.tally(subs, ballots, budget=Decimal("100"), cap_percent=Decimal("100"), min_voters_needed=2))
    assert rr[1]["median_points"] == Decimal("10") and rr[2]["median_points"] == Decimal("90")


def test_points_from_the_own_developer_never_count(c):
    subs = [S(1, 10)]
    ballots = [B(10, s1=100), B(20, s1=40), B(30, s1=40)]   # developer 10 voting for its own work
    rr = rows(c.tally(subs, ballots, budget=Decimal("100"), cap_percent=Decimal("100"), min_voters_needed=2))
    assert rr[1]["voters"] == 2 and rr[1]["median_points"] == Decimal("40")


def test_too_few_voters_is_no_award_and_says_why(c):
    subs = [S(1, 10), S(2, 20), S(3, 30)]
    ballots = [B(40, s1=50, s2=50), B(50, s1=50)]
    rr = rows(c.tally(subs, ballots, budget=Decimal("100"), cap_percent=Decimal("100"), min_voters_needed=2))
    assert rr[1]["funded"] and not rr[2]["funded"] and rr[2]["reason"] == "too_few_voters"
    assert rr[3]["reason"] == "no_points" and rr[3]["amount"] == 0
    assert rr[1]["amount"] == Decimal("100.000000"), "the only funded submission takes the budget"


def test_the_cap_binds_per_developer_and_the_rest_stays_unallocated(c):
    subs = [S(1, 10), S(2, 10), S(3, 20)]                     # developer 10 has two submissions
    ballots = [B(30, s1=40, s2=40, s3=20), B(40, s1=40, s2=40, s3=20)]
    r = c.tally(subs, ballots, budget=Decimal("1000"), cap_percent=Decimal("50"), min_voters_needed=2)
    rr = rows(r)
    dev10 = rr[1]["amount"] + rr[2]["amount"]
    assert dev10 == Decimal("500.000000") and rr[1]["capped"] and rr[2]["capped"]
    assert rr[3]["amount"] == Decimal("200.000000") and not rr[3]["capped"]
    assert r["unallocated"] == Decimal("300"), "what the cap removed is not handed to anyone else"


def test_amounts_round_down_and_never_exceed_the_budget(c):
    subs = [S(1, 10), S(2, 20), S(3, 30)]
    ballots = [B(40, s1=1, s2=1, s3=1), B(50, s1=1, s2=1, s3=1)]
    r = c.tally(subs, ballots, budget=Decimal("100"), cap_percent=Decimal("100"), min_voters_needed=2)
    assert all(row["amount"] == Decimal("33.333333") for row in r["rows"])
    assert r["awarded"] <= Decimal("100") and r["unallocated"] == Decimal("0.000001")


def test_struck_or_withdrawn_work_is_not_tallied(c):
    subs = [S(1, 10), {**S(2, 20), "status": "struck"}]
    ballots = [B(30, s1=50, s2=50), B(40, s1=50, s2=50)]
    r = c.tally(subs, ballots, budget=Decimal("100"), cap_percent=Decimal("100"), min_voters_needed=2)
    assert [row["submission_id"] for row in r["rows"]] == [1]


def test_a_pay_run_re_sends_only_while_the_ledger_remembers_the_key(c):
    """The ledger keeps an idempotency record 24 hours from the first attempt: inside that a re-send of a payment
    that landed answers with the original transaction, past it the same re-send could pay twice."""
    now = dt.datetime(2026, 10, 2, 12, tzinfo=dt.timezone.utc)
    ago = lambda hours: now - dt.timedelta(hours=hours)  # noqa: E731
    assert c.RETRY_WINDOW < dt.timedelta(hours=24), "the window must close before the ledger forgets the key"
    assert c.payment_action("pending", None, now) == "pay"
    assert c.payment_action("pending", ago(1), now) == "retry", "a lost answer is never taken for an unsent payment"
    assert c.payment_action("pending", ago(30), now) == "decide"
    assert c.payment_action("failed", ago(22), now) == "retry"
    assert c.payment_action("failed", ago(24), now) == "decide"
    assert c.payment_action("failed", None, now) == "decide", "a failure with no clock is never re-sent blind"
    for settled in ("paid", "partial", "written_off"):
        assert c.payment_action(settled, ago(1), now) is None


def test_the_ballot_digest_binds_the_exact_allocation(c):
    a = {"3": 40, "1": 60}
    assert c.ballot_digest(a) == c.ballot_digest({"1": 60, "3": 40}), "order does not matter"
    assert c.ballot_digest(a) != c.ballot_digest({"1": 59, "3": 41}), "one point moved is a different ballot"


# ── the line: nothing held enters a commons formula ──────────────────────────

FORBIDDEN_NAMES = {"staked_balance", "liquid_balance", "token_balance", "locked_balance", "Stake", "OrgSharePosition",
                   "vetoken_calculator", "VeTokenCalculator", "weight_for", "points_for"}
FORBIDDEN_TABLES = ("stakes", "org_share_positions", "agent_teg_profiles", "materialized_balances")


def _violations(source: str) -> list:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = " " + node.value.lower().replace("\n", " ") + " "
            if any(k in low for k in (" select ", " from ", " join ")):
                found += [f"sql:{t}" for t in FORBIDDEN_TABLES if f" {t} " in low or f" {t}." in low]
                found += [f"sql:{col}" for col in ("staked_balance", "liquid_balance", "token_balance") if col in low]
    return found


@pytest.mark.parametrize("rel", ["services/commons.py", "routers/commons.py"])
def test_the_commons_reads_no_holdings_and_no_vote_weight(rel):
    """Membership decides WHO may ballot (weight_points_for > 0); no weight, balance or lock shapes an amount.
    A member's tenure weight (weight_for, points_for) is a governance concept and must never price an award."""
    src = (SRC / rel).read_text(encoding="utf-8")
    assert _violations(src) == [], f"{rel}: {_violations(src)}"


def test_the_commons_scanner_can_fail():
    for planted in ("x = agent.liquid_balance\n", "a = amount * weight_for(s, n, 365)\n",
                    "q = 'SELECT amount FROM stakes WHERE agent_did = :d'\n"):
        assert _violations(planted), planted

"""§MONEY-M2 — a rendered profile must describe a coherent economy.

The knob table turns two numbers (S0 and the grant, decisions D1 and D2) into
twenty amounts. That is exactly the kind of derivation that can produce a
plausible-looking file which is nonsense: a mint cap above the supply, dust
larger than the smallest deliberate stake, a machine allowed to heal a whole
grant unattended.

These invariants hold for ANY S0 and grant, so re-rendering at a different scale
cannot quietly produce an incoherent network. They are relationships, never
particular numbers — pinning "the floor is 200000" would just re-state the
decision back to itself.

ANCHOR RULE, which these encode: a knob a PERSON experiences scales with the
GRANT; a knob the NETWORK experiences scales with S0. Two knobs were anchored to
S0 and came out large next to a 1000-unit grant (dust at 1 unit = 0.1% of a whole
grant; auto-heal at 10 = 1%), and moving them to GRANT is what these tests keep
honest.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
KNOBS_PY = HERE / "scripts" / "network_profile_knobs.py"

# (S0, GRANT) pairs. The first is the Commander's decision; the others exist so
# the invariants are proved as relationships rather than as one lucky arithmetic.
SCALES = [
    (Decimal("1000000"), Decimal("1000")),   # D1/D2 as approved 2026-09-04
    (Decimal("100000"), Decimal("100")),
    (Decimal("10000000"), Decimal("5000")),
    (Decimal("1000000000"), Decimal("1000")),  # today's frame-a scale
]


def _load_knobs():
    spec = importlib.util.spec_from_file_location("network_profile_knobs", KNOBS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.KNOBS


def _render(s0: Decimal, grant: Decimal) -> dict:
    out = {}
    for k in _load_knobs():
        f = k["lowsupply"]
        if f is None:
            continue
        v = eval(f, {"__builtins__": {}}, {"S0": s0, "GRANT": grant})  # noqa: S307
        assert isinstance(v, Decimal), f"{k['name']} formula {f!r} produced {type(v).__name__}"
        out[k["name"]] = v
    return out


pytestmark = pytest.mark.skipif(not KNOBS_PY.is_file(), reason="knob table not in this checkout")


@pytest.mark.parametrize("s0,grant", SCALES)
def test_every_formula_evaluates_to_an_exact_decimal(s0, grant):
    """Integer arithmetic only. A float literal would raise on Decimal, and
    coercing through float reintroduces §MONEY-R15's truncation class."""
    vals = _render(s0, grant)
    assert vals, "no sized knobs rendered — this gate would pass by not looking"
    for name, v in vals.items():
        assert v >= 0, f"{name} is negative at S0={s0} GRANT={grant}"


@pytest.mark.parametrize("s0,grant", SCALES)
def test_a_mint_cap_never_exceeds_the_supply(s0, grant):
    """A cap above the supply is no cap."""
    v = _render(s0, grant)
    assert v["TEG_MINT_MAX_AVT"] <= s0
    assert v["TEG_TRANSFER_MAX_AVT"] <= s0


@pytest.mark.parametrize("s0,grant", SCALES)
def test_one_grant_never_exceeds_the_floor_that_guards_the_treasury(s0, grant):
    """If a single grant could clear the floor, the floor cannot bound a burst."""
    v = _render(s0, grant)
    assert grant < v["GENESIS_GRANT_TREASURY_FLOOR"]


@pytest.mark.parametrize("s0,grant", SCALES)
def test_four_operator_seeds_fit_inside_the_supply(s0, grant):
    """The standup provisions four operators. Four seeds must not be the economy."""
    v = _render(s0, grant)
    assert v["OPERATOR_PROVISION_FUNDING_AVT"] * 4 < s0


@pytest.mark.parametrize("s0,grant", SCALES)
def test_dust_is_smaller_than_the_smallest_deliberate_amount(s0, grant):
    """Dust is swept, not returned. It must be below anything a person means to do."""
    v = _render(s0, grant)
    assert v["EXCHANGE_REPAT_DUST"] < v["STAKING_MIN_STAKE_AMOUNT"], (
        "the sweep threshold is at or above the minimum stake — real money would be "
        "swept as dust"
    )
    assert v["EXCHANGE_REPAT_DUST"] < grant / 100, "dust is more than 1% of a grant"


@pytest.mark.parametrize("s0,grant", SCALES)
def test_a_machine_cannot_heal_a_whole_grant_unattended(s0, grant):
    """The reconciliation guard corrects drift with no human in the loop."""
    v = _render(s0, grant)
    assert v["BALANCE_RECONCILE_AUTO_APPROVE_MAX"] < grant / 10, (
        "the guard may auto-approve more than 10% of a person's entire grant"
    )


@pytest.mark.parametrize("s0,grant", SCALES)
def test_a_petition_cannot_dwarf_a_grant(s0, grant):
    v = _render(s0, grant)
    assert v["FUNDING_REQUEST_MAX_AVT"] <= grant


@pytest.mark.parametrize("s0,grant", SCALES)
def test_a_person_holding_one_grant_can_reach_the_market(s0, grant):
    """A listing fee or a minimum stake above a grant makes the network
    unusable for exactly the people it was sized for."""
    v = _render(s0, grant)
    assert v["EXCHANGE_LISTING_FEE"] <= grant
    assert v["STAKING_MIN_STAKE_AMOUNT"] <= grant


@pytest.mark.parametrize("s0,grant", SCALES)
def test_canaries_are_not_the_economy(s0, grant):
    """Canaries dispatch REAL currency on a timer. Ten of them at the top-up
    target must stay a rounding error against the supply."""
    v = _render(s0, grant)
    assert v["CANARY_REBALANCER_TOPUP_AVT"] * 10 < s0 / 10, (
        "ten canaries topped to target would hold more than 10% of the supply"
    )
    assert v["CANARY_REBALANCER_FLOOR_AVT"] <= v["CANARY_REBALANCER_TOPUP_AVT"], (
        "the refill floor is above the refill target — every check would refill"
    )


def test_the_committed_lowsupply_profile_matches_the_approved_numbers():
    """The file on disk must be a render of D1/D2, not a hand-edit."""
    prof = HERE / "config" / "network_profile.lowsupply-2026.env"
    if not prof.is_file():
        pytest.skip("lowsupply profile not rendered in this checkout")
    text = prof.read_text(encoding="utf-8")
    on_disk = {m.group(1): Decimal(m.group(2))
               for m in re.finditer(r"^([A-Z_]+)=([0-9.]+)$", text, re.M)}
    expected = _render(Decimal("1000000"), Decimal("1000"))
    mismatched = {k: (on_disk[k], expected[k]) for k in expected
                  if k in on_disk and on_disk[k] != expected[k]}
    assert not mismatched, (
        f"the committed profile disagrees with the knob table: {mismatched}. "
        "Re-render, never hand-edit an amount."
    )
    assert len(on_disk) >= 15, f"only {len(on_disk)} amounts parsed from the profile"

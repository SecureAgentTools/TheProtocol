"""§MCPTEST30 (2026-09-30) — `bond_gate_settle_pays_a_payee_that_lost_its_bond` sizes each offence to close the bond.

The slash is `slash_percent` of the offence's DISPUTED AMOUNT, and only the levels whose policy says
`admin_review_required: false` execute on their own. Six bond-sized disputes read 250 -> 225 -> 175 -> 175 ... on the
standing pair (L3/L4 wait for review), so the test skipped in 18 of 49 archived runs. `_disputed_to_take` is the
smallest dispute whose slash covers the bond still held, after the engine's volume tiers; pinned against the engine's
own arithmetic (services/enforcement_engine.py: minor REPLACES the percent, major MULTIPLIES it).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agentvault_registry.api_tests.federation_suite.tests.test_reputation_bond_gates import _disputed_to_take

TIERS = {"minor": {"max_amount": 100, "slash_percent_override": 5},
         "major": {"min_amount": 10000, "slash_percent_override_multiplier": 1.5}}


def _engine_slash(disputed: int, pct: Decimal, tiers) -> Decimal:
    """The engine's slash for one offence (correlation multiplier 1), written from its source."""
    minor, major = tiers.get("minor") or {}, tiers.get("major") or {}
    if minor and disputed <= minor.get("max_amount", 0):
        pct = Decimal(str(minor["slash_percent_override"]))
    elif major and disputed >= major.get("min_amount", float("inf")):
        pct = pct * Decimal(str(major["slash_percent_override_multiplier"]))
    return max(Decimal(1), Decimal(disputed) * pct / Decimal(100))


@pytest.mark.parametrize("held,pct", [(Decimal(250), Decimal(10)), (Decimal(175), Decimal(20)),
                                      (Decimal(5), Decimal(10)), (Decimal(2000), Decimal(10)),
                                      (Decimal("0.5"), Decimal(10)), (Decimal(250), Decimal(10))])
@pytest.mark.parametrize("tiers", [TIERS, {}])
def test_the_dispute_closes_the_bond_at_that_level(held, pct, tiers):
    disputed = _disputed_to_take(held, pct, tiers)
    assert _engine_slash(disputed, pct, tiers) >= held, (held, pct, disputed)


def test_the_measured_standing_pair_case():
    # L1 10% on the backstop's 250: 2,501 disputed takes the whole bond in the first, auto-executing offence
    assert _disputed_to_take(Decimal(250), Decimal(10), TIERS) == 2501

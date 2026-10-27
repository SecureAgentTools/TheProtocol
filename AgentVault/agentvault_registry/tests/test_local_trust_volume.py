"""§VITALS mig 0171 — bilateral trust volume survives a sub-unit transfer.

Verified on 24h of real registry-a traffic before the fix
(`scratchpad/vitals/prove_trust_truncation.py`):

    4,668 transfers · 73.1% fractional · **57.0% stored as ZERO**
    19 of 29 active senders scored tx_volume = 0 while moving real value
    992.33 of 17,158.33 units erased (5.8%)

TWO layers had to move together: `routers/teg_integration.py` truncated with
`int(float(amount))` BEFORE the DB saw the value, and the column was BIGINT so it
could not have held a fraction anyway. Fixing either alone changes nothing.

It matters because `services/eigentrust_engine.py` Step 8 weights the global trust
vector by volume and projects it into `Agent.reputation_score`: an agent whose
whole history is sub-unit kept the DEFAULT weight of 1.0 and was quietly
down-weighted against anyone who happened to move whole units.
"""
from __future__ import annotations

import inspect
from decimal import Decimal

from agentvault_registry import models
from agentvault_registry.routers import teg_integration, reputation_trust


def test_the_column_is_numeric_not_an_integer():
    col = models.LocalTrustScore.__table__.c.tx_volume
    assert col.type.__class__.__name__ == "Numeric", f"got {col.type!r}"
    assert (col.type.precision, col.type.scale) == (36, 18)


def test_the_call_site_no_longer_truncates():
    """`int(float(x))` truncates toward zero: 0.9 -> 0, 1.9 -> 1. It ran on every
    completed transfer.

    ⚠ Asserted on the AST, not on the source TEXT. The first version of this test
    grepped for the literal `int(float(transfer_amount))` and went red against the
    correct fix, because the comment explaining the fix quotes the very expression
    it removed — the §COCKPITTILES trap (a guard keyed on a string the change
    itself writes) in a new costume. A structural gate cannot be fooled by prose.
    """
    import ast as _ast
    tree = _ast.parse(inspect.getsource(teg_integration._record_transfer_ancillary))
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
                and node.func.id == "int" and node.args
                and isinstance(node.args[0], _ast.Call)
                and isinstance(node.args[0].func, _ast.Name)
                and node.args[0].func.id == "float"):
            raise AssertionError("int(float(...)) is back on the transfer path")
    assert "Decimal(str(transfer_amount))" in inspect.getsource(
        teg_integration._record_transfer_ancillary)


def test_the_api_reports_volume_as_a_number_that_can_hold_a_fraction():
    """An `int` here would coerce every sub-unit volume back to 0 on the way out,
    reintroducing the defect at the surface after fixing it in the column."""
    assert reputation_trust.TrustEdgeResponse.model_fields["tx_volume"].annotation is float


def test_eigentrust_casts_before_the_power_and_the_numpy_add():
    """`Decimal ** float` raises, and a numpy float array will not take a Decimal.
    Both are on the path that turns volume into reputation_score."""
    from agentvault_registry.services import eigentrust_engine
    src = inspect.getsource(eigentrust_engine)
    assert "float(volume_map.get(i, 0))" in src
    assert "features[i, 2] += float(r.tx_volume)" in src


def test_the_updater_accumulates_exactly():
    """The arithmetic the upsert performs, in isolation: a hundred dust transfers
    must not vanish."""
    total = Decimal(0)
    for _ in range(100):
        total = max(Decimal(0), Decimal(str(total)) + Decimal(str("0.01")))
    assert total == Decimal("1.00")
    assert int(total) == 1
    # …and the shape that was shipping: every one of those transfers stored 0
    assert sum(int(float("0.01")) for _ in range(100)) == 0

"""§FLARETOUCH (2026-09-09) — a flare flip must touch the CARD, or no peer ever learns.

Measured: 41 flare revocations through the admin rail on frame-c moved 0 rows in `agent_cards`,
and Registry-A went on rendering all 24 of those agents in "Distinguished Agents". The export feed
is ordered by the card's own clock; nothing in the revoke moved it. Same class §ENFPROP closed for
suspend / reinstate / self-delete — this rail simply predates it. (A 7-day full reconcile does
eventually repair it, which is why it stayed invisible: "it heals in a week" is not propagation.)

⚠ THE SECOND HALF IS THE ONE THAT IS EASY TO GET WRONG. The revoke's existing loop filters
`Agent.flare_tier.is_not(None)`, but §COSMETICS-ORIGIN ships the flare sidecar when EITHER the
agent OR the DEVELOPER holds a tier. So clearing the developer changes what is exported for agents
that never had a tier of their own — exactly the ones that filtered loop never visits. The touch
must therefore walk every agent the developer owns.

Structural, not behavioural, and deliberately so: the defect was never in what the function
computed, it was in what it FAILED to call. An AST assertion sees that; a fixture that mocks the
db and asserts on returned rows would have passed before the fix as happily as after.
"""
import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "fiat_onramp.py"
TREE = ast.parse(SRC.read_text())


def _fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found in {SRC.name}")


def _calls(fn):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            out.append(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def test_revoke_touches_the_card():
    assert "touch_native_card_no_commit" in _calls(_fn("admin_revoke_flare")), (
        "the revoke changes rows and no peer will ever see it"
    )


def test_grant_touches_the_card_too():
    """Symmetry is not tidiness here: if only revoke propagates, a mirror can show a flare the
    home has revoked — worse than showing neither."""
    assert "touch_native_card_no_commit" in _calls(_fn("_evaluate_shadow_chancellor"))


def test_the_touch_walks_every_owned_agent_not_the_tiered_subset():
    """The filtered loop is fine for CLEARING columns and wrong for TOUCHING cards."""
    src = ast.get_source_segment(SRC.read_text(), _fn("admin_revoke_flare")) or ""
    after = src.split("§FLARETOUCH", 1)
    assert len(after) == 2, "the touch block is not present"
    block = after[1]
    assert "creator_developer_id == dev.id" in block, "the touch must select by owner"
    assert "flare_tier.is_not(None)" not in block, (
        "the touch must NOT reuse the tiered filter — agents inheriting the developer's tier are "
        "exactly the ones whose export changes and the filtered loop never visits"
    )


def test_touch_failure_cannot_fail_a_completed_purchase():
    """A stale mirror is a delay; a raised exception here would undo a paid grant. It must be
    caught AND logged — the silence is what let the revoke side hide."""
    src = ast.get_source_segment(SRC.read_text(), _fn("_evaluate_shadow_chancellor")) or ""
    seg = src.split("§FLARETOUCH", 1)[1].split("await db.commit()", 1)[0]
    assert "try:" in seg and "except" in seg, "the grant-side touch must not be able to raise"
    assert "logger.warning" in seg, "and it must say so when it fails"

"""§MONEY-R28 — a cross-registry stage leg must not be reopened for a SECOND stage
unless the first one was fully reversed.

THE DEFECT. Three sites stage a payout through the payer before a cross-registry transfer:
`routers/guild.py` settle (`xf_stage`) and dispute-payout (`xfd_stage`), and
`services/contract_settlement.py` milestone release (`ctrref:{cid}:m{seq}:xf_stage`). Each
carries a RANDOM `nonce` in its escrow ref, so the leg's TEG Idempotency-Key is new on every
attempt. The transfer's own key is stable. On failure each site compensated and then
UNCONDITIONALLY reopened the record for the payer's retry. When a transfer had actually
COMMITTED but timed out, the compensation could not run (the payer no longer held the funds),
yet the record reopened anyway: the retry staged a SECOND payout under a NEW key while the
transfer replayed from cache and moved nothing. Escrow out twice, worker paid once.

WHY THE OBVIOUS FIX IS WRONG — DO NOT "CORRECT" THE NONCE TO A CONSTANT. With a constant key
the retry's stage payout replays from cache and moves NOTHING, so the payer holds no staged
funds. Either the transfer then fails forever (until the 24h idempotency record expires), or —
worse — the payer happens to hold their own funds, the transfer succeeds out of their pocket,
the record settles, and the bounty is ORPHANED in escrow. That is a worse defect than the one
being closed. The nonce is CORRECT; it is only dangerous when paired with an unconditional
reopen.

THE INVARIANT THIS RATCHET PINS: a fresh stage key is reachable only after a full reversal.
Compensation succeeding ⟺ the funds are back in escrow ⟺ reopening is safe. Compensation
failing (for ANY reason) ⟺ the funds are still with the payer ⟺ the claim must be held.

WHERE HELD RECORDS GO (all pre-existing, verified 2026-09-04 — no new state was invented):
  • guild 'settling'   → guild_order_reaper flags xreg orders 'disputed' for admin at 30 min
  • guild 'resolving'  → same, via the branch this batch added for consistency (site 4)
  • contract 'releasing' → contract_reaper EXCLUDES xreg (`counterparty_home_registry IS NULL`)
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"

# (file, SQL fragment of the reopen that must be conditional, how many such reopens)
_REOPENS = [
    ("routers/guild.py", "SET status='submitted' WHERE id=:o AND status='settling'", 1),
    ("routers/guild.py", "SET status='resolved' WHERE id=:o AND status='resolving'", 1),
    ("services/contract_settlement.py", "SET status='submitted' WHERE contract_id=:c", 1),
]


def _compensated_guard_line_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Line ranges of every `if compensated:` body — found by PARSING, never by grep."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "compensated":
            lo = min(b.lineno for b in node.body)
            hi = max(getattr(b, "end_lineno", b.lineno) for b in node.body)
            out.append((lo, hi))
    return out


def _string_literal_lines(tree: ast.AST, fragment: str) -> list[int]:
    return [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and fragment in n.value
    ]


@pytest.mark.parametrize("relpath,fragment,expected", _REOPENS)
def test_stage_reopen_is_conditional_on_compensation(relpath, fragment, expected):
    tree = ast.parse((_ROOT / relpath).read_text())
    lines = _string_literal_lines(tree, fragment)

    # Population check: a ratchet that finds nothing passes by measuring nothing.
    assert len(lines) == expected, (
        f"{relpath}: expected {expected} reopen statement(s) containing {fragment!r}, found {len(lines)}"
    )

    guards = _compensated_guard_line_ranges(tree)
    assert guards, f"{relpath}: no `if compensated:` guard found at all"

    for ln in lines:
        assert any(lo <= ln <= hi for lo, hi in guards), (
            f"{relpath}:{ln}: the stage reopen is UNCONDITIONAL. A retry after a "
            f"timed-out-but-committed transfer stages a second payout under a new nonce while the "
            f"transfer replays from cache — escrow out twice, payee paid once."
        )


@pytest.mark.parametrize("relpath", ["routers/guild.py", "services/contract_settlement.py"])
def test_compensation_flag_is_set_only_inside_the_try(relpath):
    """`compensated = True` must be the last statement of the compensating call's `try`.

    Set anywhere else it stops meaning 'the funds actually went back' and the guard above
    silently reverts to the unconditional behaviour it exists to prevent.
    """
    tree = ast.parse((_ROOT / relpath).read_text())
    sets = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "compensated" for t in n.targets)
        and isinstance(n.value, ast.Constant) and n.value.value is True
    ]
    assert sets, f"{relpath}: no `compensated = True` found"

    try_body_lines = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            for b in n.body:
                try_body_lines.update(range(b.lineno, getattr(b, "end_lineno", b.lineno) + 1))
    for s in sets:
        assert s.lineno in try_body_lines, (
            f"{relpath}:{s.lineno}: `compensated = True` is outside the compensating try — it would "
            f"be set even when the re-escrow raised"
        )


def test_reaper_does_not_revert_a_stuck_xreg_resolving_order():
    """The reaper's `resolving` branch must gate on `worker_home_registry` BEFORE reverting.

    Reverting an xreg dispute payout to 'resolved' lets it run again under a new
    `xfd_stage:{nonce}` — the same double-drain the sibling 'settling' branch already avoids.
    """
    src = (_ROOT / "background_tasks/guild_order_reaper.py").read_text()
    tree = ast.parse(src)

    back_assigns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "back" for t in n.targets)
    ]
    assert len(back_assigns) == 1, f"expected 1 `back = ...` revert, found {len(back_assigns)}"

    guards = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Subscript)
        and isinstance(n.test.slice, ast.Constant)
        and n.test.slice.value == "worker_home_registry"
    ]
    assert len(guards) >= 2, (
        "the reaper must gate BOTH the 'resolving' and the 'settling' branch on "
        f"worker_home_registry; found {len(guards)} such guard(s)"
    )
    # the revert must come after an xreg guard that `continue`s
    assert any(g.lineno < back_assigns[0].lineno for g in guards), (
        "the `resolving` revert is not preceded by an xreg guard — a stuck cross-registry "
        "dispute payout would be reopened for a second stage"
    )

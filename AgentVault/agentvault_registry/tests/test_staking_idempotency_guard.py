"""§MONEY — the staking idempotency guard must test PRESENCE, not truthiness.

`StakingService.check_idempotency()` returns `None` when no prior request exists and
`key_record.response_data` when one does. The three call sites guarded that with a bare
`if existing_response:`, so a stored FALSY payload (`{}`) read as "never seen" and **the
stake re-executed** — a money leg replayed because a dict was empty.

MEASURED 2026-09-04 on frame-a: `idempotency_keys` held 4 rows, 0 SQL-null, 0 empty, 0
JSON-null ⇒ the defect was LATENT, not live. It is fixed as a hazard, not an incident.

WHY `None` IS UNAMBIGUOUS HERE (and why the second test below exists): `response_data` is
`nullable=False`, so a row can never carry SQL NULL. That is the ONLY reason
`check_idempotency() is None` cleanly means "no record" rather than collapsing
"no record" with "record whose payload is null" — the two-state trap. If that column
ever becomes nullable, the guard silently starts lying again and this ratchet goes red.

⚠ Under the fix a stored `{}` now reaches `StakeTransactionRead(**{})` and raises → 500.
That is the CORRECT failure direction: a 500 is loud and moves no money, where the old
behaviour was silent and moved money twice.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "agentvault_registry" / "routers" / "staking_enhanced.py"
)


def _guards_on(name: str, tree: ast.AST) -> list[ast.If]:
    """Every `if <name> ...:` statement, found by PARSING — never by grep.

    A text search here would also match the docstrings and comments that quote the very
    line this ratchet asserts is gone (that mistake cost this session four false reds).
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if isinstance(t, ast.Name) and t.id == name:
            out.append(node)                      # bare truthiness  →  the defect
        elif isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == name:
            out.append(node)                      # a comparison     →  candidate fix
    return out


def test_every_existing_response_guard_tests_presence_not_truthiness():
    tree = ast.parse(_SRC.read_text())
    guards = _guards_on("existing_response", tree)

    # The population must be non-empty, or this ratchet passes by measuring nothing.
    assert len(guards) == 3, f"expected 3 guarded call sites, found {len(guards)}"

    for g in guards:
        assert isinstance(g.test, ast.Compare), (
            f"line {g.lineno}: bare `if existing_response:` — a stored falsy payload reads "
            f"as 'never seen' and the stake re-executes"
        )
        assert len(g.test.ops) == 1 and isinstance(g.test.ops[0], ast.IsNot), (
            f"line {g.lineno}: guard must be `is not`, got {type(g.test.ops[0]).__name__}"
        )
        cmp_to = g.test.comparators[0]
        assert isinstance(cmp_to, ast.Constant) and cmp_to.value is None, (
            f"line {g.lineno}: guard must compare against None"
        )


def test_response_data_is_not_nullable_so_none_means_absent():
    """The schema invariant the guard's meaning rests on.

    If `response_data` becomes nullable, `check_idempotency()` returns `None` for BOTH
    "no record" and "record with a null payload", and `is not None` silently stops
    distinguishing them — the same two-state collapse one layer down.
    """
    from agentvault_registry.models import IdempotencyKey

    col = IdempotencyKey.__table__.c.response_data
    assert col.nullable is False, (
        "response_data became nullable — check_idempotency() can no longer distinguish "
        "'no record' from 'record with null payload'; the presence guard needs a third state"
    )

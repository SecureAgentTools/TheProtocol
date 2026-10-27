"""§MONEY-R15 — a money leg must not lose precision on its way to the TEG.

R15 asked me to PROVE the account-deletion forfeiture is Δ-neutral. The forfeiture rides
`/admin/treasury/receive`, the same fee-free admin mover the proven escrow rail uses, so its
Δ-neutrality rides on the TEG balance outbox exactly as `escrow_deposit`'s does. What the
inspection actually turned up was different and worse: the amount was TRUNCATED on the way out.

    str(float(Decimal("5000.000000000000000001")))  ->  "5000.0"
    str(float(Decimal("0.123456789012345678")))     ->  "0.12345678901234568"

FIVE call sites posted `str(float(<Decimal>))` to a TEG endpoint that declares `amount: Decimal`,
while the proven rail (`services/escrow.py::escrow_deposit`) posts `str(amount)`. Four were real
money legs and are fixed here: the deletion forfeiture, two dispute slashes in
`federation_disputes.py`, and the slash + compensation pair in `crud_disputes.py`.

⚠ THE FIFTH IS DELIBERATE AND MUST NOT BE "FIXED". `federation_disputes.py` ~:637 passes
`amount=str(float(slashed_amount))` into `fund_reward_via_waterfall`, and its own comment says
why: the durable Idempotency-Key's body hash must stay compatible with pre-roll cache entries.
Changing it would turn a replay into a 409 param-hash mismatch. This ratchet pins that site as
UNCHANGED, so the exception cannot be silently swept away by a future sweep — and so that the
next reader learns it is a decision, not an oversight.

⚠ THIS TEST PARSES. A text search for `str(float(` now matches the COMMENTS this batch added,
which is exactly how four false reds were produced earlier in the same session.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"

_MONEY_LEG_FILES = [
    # "routers/account_deletion.py" — §MONEY-R39 (2026-09-04): the forfeiture no longer builds
    # its own JSON body; it rides services/escrow.py::escrow_deposit (the proven rail this
    # module's docstring names), which posts str(amount). The Decimal reaching the mover is pinned by
    # tests/test_account_deletion_drain_transport.py::test_successful_drain_uses_the_forfeit_key_and_reason.
    "routers/federation_disputes.py",
    "crud/crud_disputes.py",
]


def _is_float_call(node: ast.AST) -> bool:
    """`float(x)` or `str(float(x))` — the shapes that truncate a Decimal."""
    n = node
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str" and n.args:
        n = n.args[0]
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"


@pytest.mark.parametrize("relpath", _MONEY_LEG_FILES)
def test_no_amount_in_an_outgoing_body_is_truncated_through_float(relpath):
    tree = ast.parse((_ROOT / relpath).read_text())
    offenders = []
    seen = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and k.value == "amount"):
                continue
            seen += 1
            if _is_float_call(v):
                offenders.append(node.lineno)
    # Population check — a ratchet that inspects nothing passes by measuring nothing.
    assert seen, f"{relpath}: no `\"amount\":` dict entry found at all — did the payload move?"
    assert not offenders, (
        f"{relpath}: an outgoing amount is passed through float() near line(s) {offenders}; "
        f"a Decimal loses digits and the TEG declares `amount: Decimal`"
    )


def test_the_waterfall_compatibility_site_is_left_alone():
    """The documented exception. If this goes red, someone swept it — read its comment first."""
    src = (_ROOT / "routers" / "federation_disputes.py").read_text()
    tree = ast.parse(src)
    kw_float = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg == "amount" and _is_float_call(kw.value)
    ]
    assert kw_float, (
        "the fund_reward_via_waterfall call no longer passes str(float(...)). Its comment says "
        "the historical amount format keeps the durable Idempotency-Key's body hash compatible "
        "with pre-roll cache entries; changing it turns a replay into a 409. If that was "
        "intentional, delete this test and say so — do not just make it pass."
    )

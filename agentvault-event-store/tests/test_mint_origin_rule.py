"""§MONEY-R10 — only this frame's own registry may append mint-class events.

The ledger authenticated the caller and then never asked whether THIS caller may
emit THIS type. Operator TEGs legitimately write here — teg-teg-op-{paris,london,
berlin,washington} account for 23,686+ events on frame-a — so a federated mTLS
identity POSTing `TokensIssued` was a real capability, not a theoretical one.

MEASURED before enforcing: 847 mint-class events, all from source_service
'registry' (841) or 'teg' (4, 2026-03-29, pre-policy), ZERO from any operator;
and source_operator_id is a live field (populated on 9 events), so that zero is
evidence rather than an unused column.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "routers" / "events.py"
if not SRC.is_file():
    SRC = pathlib.Path("/app/src/routers/events.py")


def _append_event_fn() -> ast.AST:
    tree = ast.parse(SRC.read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "append_event")


def test_the_rule_reads_the_authenticated_identity_not_the_request_body():
    """THE test. `source_service` arrives in the REQUEST BODY and is
    caller-supplied, so a rule keyed on it would refuse nobody — the same shape
    as trusting the first X-Forwarded-For element. The discriminator must be
    auth_context, which verify_event_auth derives from the mTLS SVID or the
    internal key.
    """
    # Locate the rule STRUCTURALLY. Slicing the unparsed body on a comment marker
    # does not work — ast.unparse drops comments, so the "head" was the whole
    # function and the assertion tripped on an unrelated later line. Same mistake
    # in miniature as every other scope error this session.
    fn = _append_event_fn()
    rule_ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                and "MONEY-R10" in ast.unparse(n)]
    assert rule_ifs, "the mint-origin rule is gone"
    test_src = ast.unparse(min(rule_ifs, key=lambda n: n.lineno).test)
    assert "auth_context" in test_src, (
        f"the rule's condition does not consult the authenticated identity: {test_src}"
    )
    assert "source_service" not in test_src, (
        f"the rule's condition reads the caller-supplied source_service — forgeable, "
        f"would refuse nobody: {test_src}"
    )


def test_the_rule_covers_both_shapes_of_a_mint():
    fn = _append_event_fn()
    rule_ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                and "MONEY-R10" in ast.unparse(n)]
    assert rule_ifs
    # the covered set is built just above the rule; take the whole enclosing scope
    # up to the rule's own line
    src_lines = SRC.read_text().split("\n")
    region = "\n".join(src_lines[fn.lineno - 1: min(rule_ifs, key=lambda n: n.lineno).lineno])
    assert "TokensIssued" in region and "DisputeCompensationMinted" in region, \
        "a mint-class event type is no longer covered"
    assert "'mint'" in region or '"mint"' in region, \
        "mint-kind LedgerBalanceChanged is not covered — the outbox shape would slip through"
    assert "dispute_comp" in region, "dispute_comp kind is not covered"


def test_the_refusal_precedes_the_write():
    """A rule that ran after the insert would refuse the response and keep the
    event — worse than no rule, because the ledger would then disagree with the
    API."""
    fn = _append_event_fn()
    rule = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "MONEY-R10" in str(n.value)]
    writes = [n.lineno for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("add", "commit", "flush")]
    assert rule, "no MONEY-R10 marker string in the function"
    if writes:
        assert min(rule) < min(writes), (
            f"the origin rule (L{min(rule)}) must precede the first DB write (L{min(writes)})"
        )


def test_origin_is_the_marker_for_an_internal_caller():
    """verify_event_auth returns operator == 'origin' for internal services and an
    operator NAME for anyone federated. If that contract changed, this rule would
    silently refuse the registry itself."""
    body = ast.unparse(ast.parse(SRC.read_text()))
    assert '"operator": "origin"' in body or "'operator': 'origin'" in body, (
        "verify_event_auth no longer marks internal callers as operator='origin' — "
        "the R10 rule's discriminator is broken"
    )

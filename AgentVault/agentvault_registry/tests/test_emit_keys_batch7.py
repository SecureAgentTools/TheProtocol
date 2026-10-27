"""§BATCH7 — the eight value-touching emit sites named by the emission_idempotency_key_ratchet carry a
deterministic key, and the two wrappers they go through forward it. Structural (AST), no DB."""
from __future__ import annotations

import ast
import pathlib

import agentvault_registry as _pkg

SRC = pathlib.Path(_pkg.__file__).resolve().parent

SITES = {  # (router, event_type) -> minimum number of keyed calls
    ("routers/admin_agents.py", "AgentOwnershipTransferred"): 1,
    ("routers/funding_requests.py", "FundingRequestCreated"): 1,
    ("routers/funding_requests.py", "FundingRequestApproved"): 1,
    ("routers/funding_requests.py", "FundingRequestRejected"): 1,
    ("routers/a2a_payment.py", "A2APaymentAuthorized"): 1,
    ("routers/federation_disputes.py", "PeerSlashConfigUpdated"): 1,
    ("routers/fiat_onramp.py", "FiatPurchaseInitiated"): 2,
}


def _calls_with_event_type(tree, event_type):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "event_type" and isinstance(kw.value, ast.Constant) and kw.value.value == event_type:
                    yield node


def _has_key_kw(call):
    return any(kw.arg == "idempotency_key" for kw in call.keywords)


def test_every_named_site_passes_a_key():
    for (rel, et), n in SITES.items():
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        calls = list(_calls_with_event_type(tree, et))
        assert len(calls) >= n, (rel, et, len(calls))
        for c in calls:
            assert _has_key_kw(c), f"{rel}: {et} emit at line {c.lineno} has no idempotency_key"
            kw = next(k for k in c.keywords if k.arg == "idempotency_key")
            assert isinstance(kw.value, ast.JoinedStr), f"{rel}:{c.lineno} the key must be a deterministic f-string, not a literal"


def test_wrappers_forward_the_key():
    for rel, fname in (("routers/admin_agents.py", "_emit_admin_action"), ("routers/fiat_onramp.py", "_emit")):
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == fname)
        params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
        assert "idempotency_key" in params, (rel, fname, params)
        inner = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "emit"]
        assert inner and all(_has_key_kw(c) for c in inner), (rel, fname, "inner emit does not forward the key")


def test_control_an_unkeyed_call_is_caught():
    fn = ast.parse('async def f():\n    await emitter.emit(event_type="X", aggregate_id="a", data={})').body[0]
    node = fn.body[0].value.value  # Await -> Call
    assert isinstance(node, ast.Call) and not _has_key_kw(node)

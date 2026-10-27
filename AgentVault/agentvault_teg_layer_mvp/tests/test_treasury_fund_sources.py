"""§SECFIX-3 (2026-09-25) — who may credit this TEG's treasury over /cross-teg/treasury-fund.

The route credits the local treasury with the amount the caller states. It accepted any internal-service identity of
ANY trusted domain, so a federated peer frame's registry or TEG could credit this frame's treasury (the architecture
audit of 2026-09-25). Treasury-to-treasury funding flows from a frame to its own operators, which share the frame's
trust domain, so the default source is this TEG's own domain; CROSS_TEG_TREASURY_FUND_SOURCES widens it.

On the way: in shared-key mode the auth function returned the KEY as the caller's "identity", which the handler logged
and wrote into the transaction memo. It now returns a label.

RED control: run with PYTHONPATH naming the tree before the fix; the rule functions do not exist there and the two
source checks fail.
"""
from __future__ import annotations

import ast
import pathlib

from teg_core_service.core import internal_auth as ia

OWN = "sandbox-a.theprotocol.cloud"
PEER = "sandbox-b.theprotocol.cloud"
SRC = pathlib.Path(ia.__file__).resolve().parents[1]


def _only_own(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    monkeypatch.delenv("CROSS_TEG_TREASURY_FUND_SOURCES", raising=False)


def test_the_own_domain_funds_by_default(monkeypatch):
    _only_own(monkeypatch)
    # the frame's own registry/TEG, and an operator of the frame (an operator shares its frame's trust domain)
    assert ia.treasury_fund_source_ok(f"spiffe://{OWN}/service/sbx-alpha-registry")
    assert ia.treasury_fund_source_ok(f"spiffe://{OWN}/operator/sbxalphaop/svid-writer")


def test_a_federated_peer_cannot_credit_this_treasury(monkeypatch):
    _only_own(monkeypatch)
    assert not ia.treasury_fund_source_ok(f"spiffe://{PEER}/service/sbx-beta-registry")
    assert not ia.treasury_fund_source_ok(f"spiffe://{PEER}/service/teg-layer")


def test_a_shared_key_caller_is_never_a_source(monkeypatch):
    _only_own(monkeypatch)
    assert not ia.treasury_fund_source_ok("shared-key")
    assert not ia.treasury_fund_source_ok(None)
    assert not ia.treasury_fund_source_ok("")


def test_no_configured_domain_means_no_source(monkeypatch):
    monkeypatch.delenv("SPIRE_TRUST_DOMAIN", raising=False)
    monkeypatch.delenv("CROSS_TEG_TREASURY_FUND_SOURCES", raising=False)
    assert ia.treasury_fund_sources() == []
    assert not ia.treasury_fund_source_ok(f"spiffe://{OWN}/service/sbx-alpha-registry")


def test_sources_widen_by_domain_or_exact_id(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    genesis = "spiffe://genesis.example/service/registry"
    monkeypatch.setenv("CROSS_TEG_TREASURY_FUND_SOURCES", f"{OWN}, {genesis}")
    assert ia.treasury_fund_source_ok(f"spiffe://{OWN}/service/registry")
    assert ia.treasury_fund_source_ok(genesis)
    assert not ia.treasury_fund_source_ok("spiffe://genesis.example/service/teg-layer")  # an exact id is exact
    assert not ia.treasury_fund_source_ok(f"spiffe://{PEER}/service/registry")


def _router_tree():
    return ast.parse((SRC / "api" / "cross_teg_router.py").read_text())


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def test_the_handler_checks_the_source_before_it_credits():
    fn = _func(_router_tree(), "receive_cross_teg_treasury_fund")
    check_line = credit_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "treasury_fund_source_ok":
            check_line = node.lineno if check_line is None else min(check_line, node.lineno)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == "token_balance":
                    credit_line = node.lineno if credit_line is None else min(credit_line, node.lineno)
    assert check_line is not None, "the treasury-fund handler never asks treasury_fund_source_ok"
    assert credit_line is not None and check_line < credit_line


def test_the_cross_teg_auth_never_returns_the_key():
    fn = _func(_router_tree(), "_validate_cross_teg_auth")
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
            assert node.value.id != "token", "the shared key is returned as the caller's identity"

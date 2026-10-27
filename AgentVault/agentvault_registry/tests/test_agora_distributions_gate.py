"""§BAFIN (2026-10-01) — AGORA_DISTRIBUTIONS_ENABLED switches the share-like feature of Organization Points off per
registry (core/agora_gate.py): no distribution can be declared, no new pot is funded, a pot already in escrow is paid
out to the end, and registry-config says so. Default on: a node that sets nothing is unchanged.

Behavioural for the gate module; structural (the AST) for the service and the worker step, whose modules need the
whole app to import.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.core import agora_gate as ag

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def test_default_on_and_only_an_explicit_off_disables(monkeypatch):
    monkeypatch.delenv("AGORA_DISTRIBUTIONS_ENABLED", raising=False)
    assert ag.distributions_enabled() is True
    for off in ("false", "FALSE", "0", "no", "off", " Off "):
        monkeypatch.setenv("AGORA_DISTRIBUTIONS_ENABLED", off)
        assert ag.distributions_enabled() is False, off
    for on in ("true", "1", "yes", "nonsense", ""):
        monkeypatch.setenv("AGORA_DISTRIBUTIONS_ENABLED", on)
        assert ag.distributions_enabled() is True, f"{on!r} must not switch anything off"


def test_the_refusal_names_its_code_word_first():
    assert ag.DISTRIBUTIONS_DISABLED_SENTENCE.startswith("agora_distributions_disabled:")
    assert "AGORA_DISTRIBUTIONS_ENABLED=false" in ag.DISTRIBUTIONS_DISABLED_SENTENCE
    # agentvault2-30's tester reads a 403 carrying this phrase as flag-gated (NOT MEASURED), never as a failure
    assert "is not enabled on this registry" in ag.DISTRIBUTIONS_DISABLED_SENTENCE


def _fn(rel: str, name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(fns) == 1, (rel, name, len(fns))
    return fns[0]


def test_declaring_checks_the_switch_before_anything_else():
    body = ast.unparse(_fn("services/exchange_service.py", "declare_dividend"))
    gate = body.find("if not distributions_enabled():")
    assert gate != -1, "declare_dividend no longer asks the switch"
    assert gate < body.find("_require_venue_open(db)") < body.find("_listing_lock(db"), "the switch must come first"
    assert "raise ExchangeError(403, DISTRIBUTIONS_DISABLED_SENTENCE)" in body


def test_the_worker_funds_no_new_pot_but_finishes_a_funded_one():
    body = ast.unparse(_fn("services/exchange_service.py", "process_dividends"))
    skip = body.find("if not d.pot_funded and (not dist_on):")
    assert skip != -1, "the settlement step must skip an unfunded pot while switched off"
    assert skip < body.find("'dividend_pot'"), "the skip must come before the pot moves"
    # a funded pot is never skipped: the only skip is keyed on pot_funded being false
    assert body.count("continue") >= 1 and "if not dist_on:" not in body


def test_registry_config_says_whether_distributions_are_live():
    tree = ast.parse((SRC / "main.py").read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config"]
    assert len(fns) == 1
    keys = {}
    for n in ast.walk(fns[0]):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant):
                    keys[k.value] = ast.unparse(v)
    assert "_agora_distributions_enabled()" in keys.get("agora_distributions_enabled", ""), sorted(keys)

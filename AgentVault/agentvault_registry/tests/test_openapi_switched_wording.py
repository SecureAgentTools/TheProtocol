"""W3 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "i want the illegal wording completly gone before
opening"): the OpenAPI schema documents only what the registry's switches let run, and says it in the compliant words.

With production's switches (STAKING_ENABLED and STAKING_REWARDS_ENABLED off) the routes that start a lock or pay, rate,
relock or distribute a payout on locked units are left out of the schema (core/staking_gate.route_documented; they still
answer, with the switch's sentence, when called), while releasing and the lock reads stay documented (nobody's units may
be stuck). No summary, description, tag, parameter description or model description then carries a staking, reward,
rate, earnings or token-as-value word; what may stay is an identifier in backticks or quotes (a permission name, a reason
code, an enum value) and the kept terms ("non-profit"). Route paths and model names are identifiers: his call (plan
PLAN_2026-10-25_COMPLIANT_OPENING.md), not checked here.
RED control: against bddf8fd6 every switched-off route is documented and 58 operations carry the words.
"""
from __future__ import annotations

import os
import re

import pytest

WORD = re.compile(r"\b(staking|staked|stakes?|unstak\w*|restak\w*|rewards?|yields?|APY|APR|interest rates?|dividends?|"
                  r"shareholders?|stocks?|IPOs?|invest(?:s|ed|ing|ment|ments|or|ors)?|profits?|revenue|earn(?:s|ed|ing|ings)?|"
                  r"crypto(?!graph)\w*|tokenomics|token economy|utility tokens?|insurance|premiums?|banks?|banking|securities)\b",
                  re.I)
STRIP = re.compile(r"`[^`]*`|'[^']*'|\"[^\"]*\"|non-profit", re.I)


def _schema(monkeypatch, staking: bool, payouts: bool):
    os.makedirs("/tmp/prom_multiproc_reg", exist_ok=True)
    monkeypatch.setenv("STAKING_ENABLED", "true" if staking else "false")
    monkeypatch.setenv("STAKING_REWARDS_ENABLED", "true" if payouts else "false")
    from agentvault_registry.main import app
    app.openapi_schema = None
    try:
        return app.openapi()
    finally:
        app.openapi_schema = None


def _texts(schema):
    for path, ops in schema["paths"].items():
        for verb, op in ops.items():
            if not isinstance(op, dict):
                continue
            where = f"{verb.upper()} {path}"
            yield where, "summary", op.get("summary") or ""
            yield where, "description", op.get("description") or ""
            for t in op.get("tags") or []:
                yield where, "tag", t
            for prm in op.get("parameters") or []:
                yield where, f"param {prm.get('name')}", prm.get("description") or ""
    for name, s in (schema.get("components", {}).get("schemas") or {}).items():
        yield f"schema {name}", "description", s.get("description") or ""
        for pn, pv in (s.get("properties") or {}).items():
            if isinstance(pv, dict):
                yield f"schema {name}", f"property {pn}", pv.get("description") or ""


def test_production_switches_leave_the_switched_off_routes_out(monkeypatch):
    paths = set(_schema(monkeypatch, False, False)["paths"])
    for gone in ("/api/v1/staking/stake", "/api/v1/teg/staking/stake", "/api/v1/staking/rewards/apy-tiers",
                 "/api/v1/staking/apy-tiers", "/api/v1/teg/rewards/claim", "/api/v1/staking/claim-rewards",
                 "/api/v1/tokenomics/rewards/{agent_did}"):
        assert gone not in paths, gone
    for kept in ("/api/v1/staking/unstake", "/api/v1/staking/balance", "/api/v1/staking/history",
                 "/api/v1/teg/staking/unstake"):
        assert kept in paths, kept


def test_locking_on_payouts_off_documents_the_lock_start_only(monkeypatch):
    paths = set(_schema(monkeypatch, True, False)["paths"])
    assert "/api/v1/staking/stake" in paths and "/api/v1/staking/rewards/apy-tiers" not in paths


def test_both_switches_on_document_everything(monkeypatch):
    on = set(_schema(monkeypatch, True, True)["paths"])
    off = set(_schema(monkeypatch, False, False)["paths"])
    assert off < on and {"/api/v1/staking/stake", "/api/v1/staking/rewards/apy-tiers"} <= on


def test_no_critical_word_in_what_the_schema_says_on_production_switches(monkeypatch):
    bad = []
    for where, field, text in _texts(_schema(monkeypatch, False, False)):
        for m in WORD.finditer(STRIP.sub(" ", text)):
            bad.append(f"{where} [{field}]: {m.group(0)}")
    assert not bad, f"{len(bad)} critical word(s) in the schema's prose:\n" + "\n".join(bad[:40])

"""§MCPTEST30 (V0524, 2026-10-01) — the cloud-op classifier knows the gate phrases operators actually send, and when it
knows none it reports the operator's words, never a guess at why.

Round 7 (sbxbetaop, V0515): getFiatTiers answered 503 "Fiat onramp is not currently enabled on this registry." and
instantiateContractTemplate 503 "Contract templates are disabled on this registry". No phrase matched ("not enabled",
"is disabled" only), and the row then said the tool's wrapper had dropped the operator's sentence, which was there.
"""
from __future__ import annotations

from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

ROUND7 = ("Error: fiat/tiers returned HTTP 503: Fiat onramp is not currently enabled on this registry.",
          "Error: instantiateContractTemplate returned HTTP 503: Contract templates are disabled on this registry")


def test_the_round7_sentences_are_gate_phrases():
    for text in ROUND7:
        assert any(m in text.lower() for m in F.CLOUDOP_GATE_MARKERS), text


def test_the_earlier_phrases_still_match():
    for text in ("The Guild is disabled on this registry", "Cross-registry OAuth federation is not enabled on this registry",
                 "Docker stats unavailable on this node", "fiat onramp is mainframe-only"):
        assert any(m in text.lower() for m in F.CLOUDOP_GATE_MARKERS), text


def test_an_unknown_refusal_is_reported_in_the_operators_words():
    o = SimpleNamespace(result_excerpt={"_text": "Error: x returned HTTP 503:   something   new\non two lines"}, fail_reason=None)
    assert F._refusal_words(o) == "x returned HTTP 503: something new on two lines"
    assert F._refusal_words(SimpleNamespace(result_excerpt={}, fail_reason=None)) == ""
    src = open(F.__file__).read()
    assert "wrapper \"\n" not in src and "drops the operator's sentence); not measured" not in src

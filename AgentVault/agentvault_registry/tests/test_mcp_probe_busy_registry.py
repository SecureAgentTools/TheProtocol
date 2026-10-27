"""§MCPTEST30 (V0529, 2026-10-01) — a registry that could not check the credential measures nothing about the tool.

V0529 answers -32003 (HTTP 503, Retry-After) when the database cannot check a credential. The two probes that read the
JSON-RPC error code themselves (types, range) would have read it as an unexplained JSON-RPC error and reported a
BUG-FIND on whatever tool was asked while the database was full (before V0529 the same moment read -32001, with the same
false find). A busy registry is NOT MEASURED; any other unexplained code stays a finding.
"""
from __future__ import annotations

from agentvault_registry.api_tests.contracts import type_confusion as TC
from agentvault_registry.api_tests.contracts import value_range as VR

BUSY = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32003, "message": "The registry cannot check credentials right now"}}
OTHER = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "Authentication required"}}
INVALID = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid params"}}


def test_minus_32003_is_unavailable_in_both_probes():
    assert TC.answer_kind("503", BUSY) == "unavailable"
    assert VR.answer_kind("503", BUSY) == "unavailable"
    assert TC.answer_kind("401", OTHER) == "jsonrpc_error -32001"
    assert VR.answer_kind("401", OTHER) == "jsonrpc_error -32001"


def test_a_busy_registry_is_not_measured_never_a_finding():
    for mod in (TC, VR):
        healthy, sentence, _ev = mod.verdict({"a": "unavailable", "b": "unavailable"})
        assert healthy is None and sentence.startswith("NOT MEASURED") and "-32003" in sentence
        healthy, sentence, _ev = mod.verdict({"a": "unavailable", "b": "invalid_params"})
        assert healthy is True, "the asks that came back are judged; the busy ones measure nothing"
        healthy, sentence, _ev = mod.verdict({"a": "unavailable", "b": "jsonrpc_error -32001"})
        assert healthy is False and sentence.startswith("BUG-FIND"), "an unexplained code stays a finding"

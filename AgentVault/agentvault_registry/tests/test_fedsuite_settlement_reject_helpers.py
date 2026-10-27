"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): the cross-frame settlement flow's two decisions, offline.

The flow (api_tests/federation_suite/tests/test_cross_registry_settlement_reject.py) asks an amount over every
auto-slash threshold the home holds, so the request always parks for an administrator and never auto-slashes; and it
touches only the settlement its own throwaway caused, matched by the defendant's DID AND the dispute's id (agentvault2-5b's
conditions for the console's settlements door).
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_reject as flow


def test_the_amount_is_over_every_enabled_threshold():
    assert flow.amount_over_every_threshold([]) == 1
    assert flow.amount_over_every_threshold(None) == 1
    peers = [{"name": "a", "auto_slash_enabled": True, "auto_slash_max_avt": 100},
             {"name": "b", "auto_slash_enabled": True, "auto_slash_max_avt": "250.0"},
             {"name": "c", "auto_slash_enabled": False, "auto_slash_max_avt": 10_000}]   # off: every request parks
    assert flow.amount_over_every_threshold(peers) == 251
    assert flow.amount_over_every_threshold([{"auto_slash_enabled": False, "auto_slash_max_avt": 5}]) == 1


def test_only_the_runs_own_settlement_is_touched():
    mine = {"id": "s1", "defendant_did": "did:theprotocol:x:d1", "dispute_id": 42, "status": "PENDING_ADMIN_APPROVAL"}
    rows = [mine,
            {"id": "s2", "defendant_did": "did:theprotocol:x:d1", "dispute_id": 41},     # its defendant, another dispute
            {"id": "s3", "defendant_did": "did:theprotocol:x:other", "dispute_id": 42},  # its dispute id, another frame's
            "not a row"]
    assert flow.ours(rows, "did:theprotocol:x:d1", "42") == [mine]
    assert flow.ours(None, "did:theprotocol:x:d1", "42") == []

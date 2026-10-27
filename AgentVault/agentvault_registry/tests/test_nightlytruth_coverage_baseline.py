"""§NIGHTLYTRUTH (2026-09-14) — the coverage ratchet's documented baseline lists the six types the 09-11/09-12
batches added without coverage, each with the session that added it, so the ratchet is green again for the
RIGHT reason (the gate's own third option: "listed in the documented baseline") and the next new type is visible.
The last test runs the ratchet's own computation over the tree: no new uncovered type, nothing dropped.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_uncovered as u

LISTED = {
    "GovernancePolicyChangeFailed", "OrphanedListingsSwept", "PeerTrustActionApplied",
    "PeerTrustActionObserved", "PeerTrustStateChanged", "ReputationBondUnlocked",
}


def test_the_six_types_are_listed_in_the_documented_baseline():
    assert LISTED <= u._UNCOVERED_BASELINE


def test_the_ratchet_reads_no_new_uncovered_type_over_the_tree():
    emitted = u._emitted_types()
    assert len(emitted) >= 200, "the census is reading the wrong tree"
    covered = (u._mcp_expected() | u._federation_named(emitted)) & emitted
    new_uncovered = sorted((emitted - covered) - u._UNCOVERED_BASELINE)
    assert new_uncovered == [], new_uncovered
    assert "PeerTrustActionApplied' if refused else 'PeerTrustActionObserved" not in emitted, "the census still reads a conditional as prose"

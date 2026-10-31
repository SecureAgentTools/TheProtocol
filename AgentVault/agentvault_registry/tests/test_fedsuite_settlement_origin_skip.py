"""§MCPTEST30 (V0650, tester batch 2 item 4, agentvault2-d3, 2026-10-31): the cross-frame settlement's reject test skips on
a frame whose origin names its internal federation proxy (the nightly pairs: no CROSS_REGISTRY_SETTLEMENT_DELIVERY, no
dialable federation address), and that skip was unread (unclassified) since V0639: read on the V0649 pair proof
(nt261031x2) and on the trial pair nt261031x3. It now carries a code with a ceiling of one row.

RED on the code before: the reason classifies as unclassified and the code has no baseline.
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.federation_suite import skip_codes
from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_reject as reject

# The reason as the V0649 pair proof's federation run recorded it (run 046a5d6d964c4c11), whole.
SEEN = ("precondition unmet: sandbox-A named itself https://nt261031x2a-nginx-federation:8443 as the settlement's "
        "origin, an address no peer holds, so every peer refuses its slash request (CROSS_REGISTRY_SETTLEMENT_DELIVERY "
        "is off there, or it has no dialable federation address): the home's half of the path cannot run here")


def test_the_pairs_reject_skip_has_a_code():
    assert skip_codes.classify_skip(SEEN) == "settlement_origin_internal"


def test_one_row_can_reach_it():
    assert skip_codes.BASELINE_SKIPS["settlement_origin_internal"] == 1
    ok, complaints = skip_codes.skip_verdict({"settlement_origin_internal": 1})
    assert ok, complaints
    ok, complaints = skip_codes.skip_verdict({"settlement_origin_internal": 2})
    assert not ok and complaints


def test_the_test_still_says_it_that_way():
    # the code reads the reject test's own sentence: a reworded precondition would fall back to unclassified
    assert "as the settlement's origin, an address no peer holds" in inspect.getsource(reject)


def test_another_precondition_stays_unread():
    assert skip_codes.classify_skip("precondition unmet: the origin answered nothing") == skip_codes.UNCLASSIFIED

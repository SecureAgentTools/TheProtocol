"""§MCPTEST30 (V0640): a refused request counts as http_expected whatever words its path carries.

services/log_metrics buckets WARNING records by the first keyword class that matches, and "settlement" ("settle",
"settlement", "escrow") came before "http_expected", so "HTTP exception on GET /agents/fedsuite-repbond-settlepayer-...:
404 - Not Found" counted as a settlement failure: with the sandbox federation suite's agents it fed production's
SettlementFailureRate (agentvault2-66, 2026-10-24). Pinned: the errors module's line for a 4xx is http_expected first,
the status read right after the path (a path holds no space); a 5xx, even one whose detail quotes a 404, still falls to
the keyword classes; the reconciliation's own warning is still settlement.
"""
from __future__ import annotations

from agentvault_registry.services.log_metrics import _categorise


def test_a_refused_request_is_http_expected_whatever_its_path_says():
    assert _categorise("HTTP exception on GET /agents/fedsuite-repbond-settlepayer-8162f104: 404 - Not Found") \
        == "http_expected"
    assert _categorise("HTTP exception on HEAD /agents/did:theprotocol:4ab-settle: 403 - Forbidden") == "http_expected"


def test_a_5xx_still_falls_to_the_keyword_classes():
    assert _categorise("HTTP exception on POST /api/v1/exchange/settle: 503 - settlement worker unavailable") \
        == "settlement"
    assert _categorise("HTTP exception on GET /x: 503 - the upstream escrow said: 404 - gone") == "settlement"


def test_the_reconciliation_warning_is_still_settlement():
    assert _categorise("Settlement 63761626 exhausted 3 retry attempts. Awaiting EventStore evidence or manual "
                       "resolution.") == "settlement"

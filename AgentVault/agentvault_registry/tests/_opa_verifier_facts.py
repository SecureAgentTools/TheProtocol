"""Facts the verifier's tests share (V0666 layer C): one set of facts per rule that every rule's verdict is GOOD on, so a test breaks
exactly one fact and reads what the verifier says."""
from __future__ import annotations

import copy
import datetime as dt

NOW = dt.datetime(2026, 11, 16, 0, 0, tzinfo=dt.timezone.utc)


def deep(f):
    return copy.deepcopy(f)


GOOD = {
    "iron_pairing": {"env": {"AGENT_RBAC_MODE": "enforce", "AGENT_DELEGATION_MODE": "enforce"}},
    "jurisdiction_coherent": {"profile": {"name": "p", "version": 1, "features": {"exchange": False}, "limits": {}},
                              "env": {"EXCHANGE_ENABLED": "false", "FX_ENABLED": "true", "GUILD_ENABLED": "true",
                                      "FORGE_ENABLED": "false", "FIAT_ONRAMP_ENABLED": "true"}},
    "fiat_buy_only": {"paths": ["/api/v1/fiat/quote", "/api/v1/fiat/tiers"], "purchases_not_in": 0, "purchases_issued": 0},
    "merge_needs_the_record": {
        "change": {"id": "cc1", "commit": "a" * 40, "state": "merged", "code_distribution_id": None,
                   "proposer_developer_id": 1, "paths": ["agentvault_registry/x.py"],
                   "acceptance": {"ok": True, "record": {"commit": "a" * 40, "read_from": "checker", "checker_kid": "k1",
                                                         "touched": ["agentvault_registry/x.py"]}},
                   "passed_at": NOW - dt.timedelta(hours=48), "go": None, "veto": None, "ballot_result": None,
                   "merged": {"commit": "a" * 40, "into": "main", "at": NOW.isoformat()}, "proposal_status": "PASSED"},
        "reviews": [{"reviewer_developer_id": 2, "verdict": "approve", "commit": "a" * 40, "at": 1.0}],
        "env": {"CODE_CHANGE_VETO_HOURS": "24"}},
    "deletion_on_schedule": {"account": {"deletion_status": "pending_deletion", "deletion_requested_at": NOW - dt.timedelta(days=3),
                                         "anonymized_at": None},
                             "env": {"ACCOUNT_DELETION_COOLING_OFF_DAYS": "14"}, "now": NOW},
}

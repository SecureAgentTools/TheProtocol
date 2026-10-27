"""§MCPTEST30 (V0641): the four admin tools at routes only a federation peer can call are said by design on their rows.

blockFederationAgent, unblockFederationAgent, ironhandRegisterAgentProxy and ironhandDeleteAgentProxy reach routes that
take only a federation peer's identity (require_peer_registry_identity: 401 to the admin's developer token, the request
survey's PEER_ROUTE). lifecycle_admin_destructive_safe probed each under its own name and the contracts pinned the
refusal, so each passed on a refusal alone ("refusal only" on both sandbox operators, V0639's read, 2026-10-25).
Pinned: each row is NOT MEASURED with the reason, the 401 is a refusal row held to "Federation authentication required",
the contracts pin nothing, and the rows survive the admin sweep's merge.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as A
from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract

PEER_ONLY = ("theprotocol_blockFederationAgent", "theprotocol_unblockFederationAgent",
             "theprotocol_ironhandRegisterAgentProxy", "theprotocol_ironhandDeleteAgentProxy")


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _run(peer_answer=("401", "HTTP 401: Federation authentication required (mTLS certificate, internal secret, or "
                             "federation license)")):
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool in PEER_ONLY:
            return False, _error(peer_answer[1]), peer_answer[0]
        return False, _error("HTTP 404: Not Found"), "404"

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", sentinel_did="did:theprotocol:sentinel", sentinel_jwt="s", flow_values={})
    asyncio.run(A.lifecycle_admin_destructive_safe(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes, calls


def _ref(tool):
    return f"refusal: {tool[len('theprotocol_'):]} a caller without a federation peer's identity"


def test_each_is_said_by_design_and_its_401_is_a_refusal_row():
    outcomes, calls = _run()
    assert {t for t, _ in A.ADMIN_PEER_ONLY_TOOLS} == set(PEER_ONLY)
    for tool in PEER_ONLY:
        row = outcomes[tool]
        assert row["healthy"] is False and str(row["skip_reason"]).startswith("NOT MEASURED"), (tool, row)
        assert "federation peer's identity" in row["skip_reason"]
        ref = outcomes[_ref(tool)]
        assert ref["healthy"] is True and ref["status_code"] == 401, (tool, ref)
    sent = {t: a for t, a in calls if t in PEER_ONLY}
    assert set(sent) == set(PEER_ONLY) and all(a.get("agent_did") for a in sent.values())
    assert [t for t, _ in calls].count("theprotocol_blockFederationAgent") == 1, "probed once, as its refusal row"


def test_a_refusal_for_another_reason_is_red():
    outcomes, _calls = _run(peer_answer=("404", "HTTP 404: Not Found"))
    for tool in PEER_ONLY:
        assert outcomes[_ref(tool)]["healthy"] is False, tool


def test_the_contracts_pin_nothing_and_the_rows_survive_the_admin_merge():
    outcomes, _calls = _run()
    pinned = lambda n: bool(get_contract(n).override_coverage_fan)  # noqa: E731
    for tool in PEER_ONLY:
        c = get_contract(tool)
        assert not c.override_coverage_fan and c.success_path_unmeasured, tool
        d = F._fan_row_verdict(outcomes[tool], tool)
        assert d["healthy"] is False and str(d["skip_reason"]).startswith("NOT MEASURED"), (tool, d)
    kept = dict(F.kept_lifecycle_rows(outcomes, set(PEER_ONLY), set(), pinned))
    for tool in PEER_ONLY:
        assert _ref(tool) in kept and kept[_ref(tool)]["healthy"], tool
        assert "earned: " + tool[len("theprotocol_"):] not in kept
    assert json.dumps(kept, default=str)

"""§MCPTEST30 (V0640): the two public federation reads are said by design on their own rows, their 401 a refusal row.

getFederationPolicyCompliance and listFederationRegistryCards call routes that take only a federation peer's identity.
Their contracts named that in success_path_unmeasured, but the History read their rows as "refusal only" (the router's
generic sentence: aa's pair run nt261024x5a, 2026-10-24 20:26Z, two of its 64). Pinned: both are in BY_DESIGN (tier 1,
NOT MEASURED with the reason), and the by-design lifecycle keeps their refusal as a refusal row that passes only on a
401 saying "Federation authentication required".
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_agent_public as EAP

READS = ("theprotocol_getFederationPolicyCompliance", "theprotocol_listFederationRegistryCards")
# §MCPTEST30 (V0641): the developer-tier peer-only tools, said by design the same way
DEV = tuple(t for t, _ in getattr(EAP, "PEER_ONLY_DEV_TOOLS", ()))


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _run(read_answer=("401", "HTTP 401: Federation authentication required (mTLS certificate, internal secret, or "
                             "licence)")):
    async def rpc(tool, args, jwt="", timeout=20):
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _answer({"federation_ballot_mode": True}), "200"
        if tool == "theprotocol_federationVoteProposal":
            return False, _error("HTTP 409: federation_ballot_pending: registries decide by ballot"), "409"
        if tool == "theprotocol_guildCrossRegistryBid":
            return False, _error("HTTP 400: price is required"), "400"
        if tool in READS or tool in DEV:
            return False, _error(read_answer[1]), read_answer[0]
        if tool in {t for t, _, _ in getattr(EAP, "NOT_DRIVEN", ())}:   # §MCPTEST30 (V0641)
            return False, _error("HTTP 404: not found"), "404"
        raise AssertionError(tool)

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", sentinel_jwt="s", flow_values={})
    asyncio.run(EAP.lifecycle_earned_by_design(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes


def test_both_reads_are_said_by_design_on_their_own_rows():
    by_design = {tool: (tier, why) for tool, tier, why in EAP.BY_DESIGN}
    for tool in READS:
        assert by_design[tool][0] == "1" and "federation peer's identity" in by_design[tool][1]
    outcomes = _run()
    for tool in READS:
        assert outcomes[tool]["skip_reason"].startswith("NOT MEASURED") and not outcomes[tool]["healthy"]


def test_their_refusal_is_a_refusal_row_held_to_its_401():
    outcomes = _run()
    for tool in READS:
        row = outcomes[f"refusal: {tool[len('theprotocol_'):]} a caller without a federation peer's identity"]
        assert row["healthy"] and row["status_code"] == 401
    # control: the same row fails when the route answers anything else
    other = _run(read_answer=("404", "HTTP 404: Not Found"))
    assert not other["refusal: getFederationPolicyCompliance a caller without a federation peer's identity"]["healthy"]


def test_no_row_the_lifecycle_says_by_design_is_one_the_sweep_drops():
    """§MCPTEST30 (V0640): a sweep takes a tool's lifecycle row unless the tool's contract pins a refusal
    (override_coverage_fan), and kept_lifecycle_rows keeps a pinned tool's lifecycle row only when it is a real
    success. Both reads were pinned, so their NOT MEASURED rows never reached a run: V0640's operator preview
    (2026-10-24 23:1xZ) still read them "refusal only" on the contract's 401. No tool this lifecycle says NOT MEASURED
    may be pinned, in either governance mode."""
    from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract
    for config in ({"federation_ballot_mode": True}, {}):
        async def rpc(tool, args, jwt="", timeout=20, _config=config):
            if tool == "theprotocol_getPublicRegistryConfig":
                return True, _answer(_config), "200"
            return False, _error("HTTP 400: refused (not found)"), "400"
        outcomes = {}
        asyncio.run(EAP.lifecycle_earned_by_design(rpc, F._parse_rpc_result,
                                                   SimpleNamespace(developer_jwt="d", sentinel_jwt="s",
                                                                   flow_values={}), outcomes))
        said = [n for n, r in outcomes.items() if n.startswith("theprotocol_")
                and str(r.get("skip_reason") or "").startswith("NOT MEASURED")]
        assert set(READS) <= set(said) and set(DEV) <= set(said)
        pinned = [n for n in said if get_contract(n).override_coverage_fan]
        assert not pinned, f"said by design, dropped by the sweep for a pinned contract: {pinned}"
        # what the sweep keeps beside its own rows: the lifecycle's own-name rows are not dropped for a pin
        kept = F.kept_lifecycle_rows(outcomes, set(said), set(), lambda n: bool(get_contract(n).override_coverage_fan))
        assert not [k for k, _ in kept if k.startswith("earned: ")], "nothing is re-filed under earned:"


def test_the_developer_tier_peer_only_tools_are_said_by_design_and_their_401_is_a_refusal_row():
    """§MCPTEST30 (V0641): getFederationSyncStatusDev, federationSlashRequest and federationSlashConfirmation take only
    a federation peer's identity (get_federation_identity, 401 to a developer token): "refusal only" on both sandbox
    operators in V0639's read. Their rows say so by design; their refusal is a refusal row held to its 401, sending
    every argument the tool requires so the call reaches the route."""
    from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract
    assert set(DEV) == {"theprotocol_getFederationSyncStatusDev", "theprotocol_federationSlashRequest",
                        "theprotocol_federationSlashConfirmation"}
    by_design = {tool: (tier, why) for tool, tier, why in EAP.BY_DESIGN}
    outcomes = _run()
    for tool, args in getattr(EAP, "PEER_ONLY_DEV_TOOLS", ()):
        assert by_design[tool][0] == "3" and "federation" in by_design[tool][1]
        assert outcomes[tool]["skip_reason"].startswith("NOT MEASURED") and not outcomes[tool]["healthy"]
        row = outcomes[f"refusal: {tool[len('theprotocol_'):]} a caller without a federation peer's identity"]
        assert row["healthy"] and row["status_code"] == 401, (tool, row)
        assert not get_contract(tool).override_coverage_fan and get_contract(tool).success_path_unmeasured
        assert set(args) >= set(get_contract(tool).arguments), "the refusal sends what the tool requires"
    other = _run(read_answer=("404", "HTTP 404: Not Found"))
    assert not other["refusal: federationSlashRequest a caller without a federation peer's identity"]["healthy"]

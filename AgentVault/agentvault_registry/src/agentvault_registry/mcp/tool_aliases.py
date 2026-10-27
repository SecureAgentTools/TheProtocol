"""§AGORAWORDS (V0419): the MCP tools that were renamed keep executing under their old names.

AGORA's tools used securities words (`buyExchangeIpo`, `declareExchangeDividend`, `getMyExchangePortfolio` ...).
They now carry the AGORA names (`buyAgoraLaunch`, `declareAgoraDistribution`, `getMyAgoraHoldings` ...). Every
dispatch table, schema, tier set, audit tier set and category map holds ONLY the new names, so the tool count does not
change and `tools/list` never advertises an old one. A client that still calls an old name is resolved here.

A name reaches a dispatch key through FOUR doors, and an alias must resolve at every one of them or that door refuses
it: the public `tools/call` (mcp/server.py), the internal `_handle_tools_call` (tasks re-enter there), the admin
`tools/call` (mcp/server_admin.py) and the gateway's `invokeTool` / `describeTools` (mcp/tools_gateway.py). All four
call `resolve_alias()`. `tests/test_mcp_tool_aliases.py` pins that every alias target is a dispatch key, that no alias
key is advertised, and that an old name executes directly and through invokeTool.

`agora_legacy_name_total{kind="mcp"}` counts resolutions (and `kind="http"` the old `/api/v1/exchange` prefix, see
main.py): the instrument for dropping the old names in a later release, once it reads zero.

W3 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "i want the illegal wording completly gone before
opening"): the tools named with staking, reward, APY, token-as-value or earnings words carry compliant names the same
way (_W3_RENAMED, the names agreed with agentvault2-69's vocabulary: locks and locked units, payouts on locked units,
units, income, payment authorizations); an old name still executes, counted as `kind="mcp_w3"`. Which of them are
LISTED depends on the registry's switches (mcp/tool_switches.py), never which execute.
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

_PREFIX = "theprotocol_"

_RENAMED: Dict[str, str] = {
    "adminExchangeApproveListing": "adminAgoraApproveListing",
    "adminExchangeDelistListing": "adminAgoraDelistListing",
    "adminExchangeGlobalHalt": "adminAgoraGlobalHalt",
    "adminExchangeHaltListing": "adminAgoraHaltListing",
    "adminExchangeInvariant": "adminAgoraInvariant",
    "adminExchangeOverview": "adminAgoraOverview",
    "adminExchangeParticipants": "adminAgoraParticipants",
    "buyExchangeIpo": "buyAgoraLaunch",
    "cancelExchangeOrder": "cancelAgoraOrder",
    "createExchangeListing": "createAgoraListing",
    "declareExchangeDividend": "declareAgoraDistribution",
    "getExchangeCandles": "getAgoraCandles",
    "getExchangeListing": "getAgoraListing",
    "getExchangeListings": "getAgoraListings",
    "getExchangeOrderBook": "getAgoraOrderBook",
    "getExchangeTrades": "getAgoraTrades",
    "getMyExchangeOrders": "getMyAgoraOrders",
    "getMyExchangePortfolio": "getMyAgoraHoldings",
    "placeExchangeOrder": "placeAgoraOrder",
}

_AGORA_RENAMED: Dict[str, str] = dict(_RENAMED)

# W3 (2026-10-25): old name -> compliant name
_W3_RENAMED: Dict[str, str] = {
    "stakeTokens": "lockUnits",
    "unstakeTokens": "unlockUnits",
    "tegStakeDirect": "tegLockDirect",
    "tegUnstakeDirect": "tegUnlockDirect",
    "getMyStakes": "getMyLocks",
    "getMyStakeStats": "getMyLockStats",
    "getMyStakingHistory": "getMyLockHistory",
    "getMyStakingStatus": "getMyLockStatus",
    "getAgentStakingBalance": "getAgentLockedBalance",
    "getAgentStakingHistory": "getAgentLockHistory",
    "getStakingGlobalStats": "getLockStats",
    "claimStakingRewards": "claimLockPayouts",
    "estimateMyStakingRewards": "estimateMyLockPayouts",
    "getApyRates": "getLockPayoutTiers",
    "getStakingApyTiersTeg": "getLockPayoutTiersTeg",
    "getStakingDistributions": "getLockPayoutRuns",
    "getStakingDistributionRecords": "getLockPayoutRecords",
    "getStakingDistributionStats": "getLockPayoutStats",
    "getMyRewardHistory": "getMyPayoutHistory",
    "getAgentRewardsHistory": "getAgentPayoutHistory",
    "getAgentPendingRewards": "getAgentPendingPayouts",
    "claimTegRewards": "claimTegPayouts",
    "getTokenomicsRewards": "getUnitPayouts",
    "transferTokens": "transferUnits",
    "getMyEarnings": "getMyIncome",
    "getTokenomicsTransactions": "getUnitTransactions",
    "getTokenomicsTreasury": "getRegistryTreasury",
    "getMyA2APaymentTokens": "getMyPaymentAuthorizations",
    "tegReputationSignalToken": "tegReputationSignal",
    "getMyAutoCompound": "getMyPayoutRelock",
    "updateAutoCompound": "updatePayoutRelock",
    "getAutoCompoundForAgent": "getPayoutRelockForAgent",
    "triggerManualDistribution": "triggerLockPayoutRun",
    "slashAgentStake": "slashAgent",
    "previewSlashStake": "previewSlash",
    "pauseAgentRewards": "pauseAgentPayouts",
    "resumeAgentRewards": "resumeAgentPayouts",
    "getRewardFundingPolicy": "getPayoutFundingPolicy",
    # "issue" where units are meant, as the ledger already says (his word through agentvault2-69, 2026-10-25 21:15Z)
    "tegTreasuryMint": "tegTreasuryIssue",
    "bridgeMintWrapped": "bridgeIssueWrapped",
    "mintFrameBSimulation": "issueFrameBSimulation",
}
_RENAMED = {**_AGORA_RENAMED, **_W3_RENAMED}

# Wire form (what dispatch tables key on): old full name -> new full name.
TOOL_ALIASES: Dict[str, str] = {f"{_PREFIX}{old}": f"{_PREFIX}{new}" for old, new in _RENAMED.items()}

try:
    from prometheus_client import Counter as _Counter

    AGORA_LEGACY_NAME_TOTAL = _Counter(
        "agora_legacy_name_total",
        "Calls that used a pre-V0419 AGORA name (kind=mcp: an old MCP tool name; kind=http: the old /api/v1/exchange prefix)",
        labelnames=["kind"],
    )
except Exception:  # pragma: no cover - metrics are best-effort
    AGORA_LEGACY_NAME_TOTAL = None


def count_legacy(kind: str) -> None:
    if AGORA_LEGACY_NAME_TOTAL is not None:
        try:
            AGORA_LEGACY_NAME_TOTAL.labels(kind=kind).inc()
        except Exception:
            pass


def resolve_alias(name: str) -> str:
    """Return the current tool name for `name` (bare or `theprotocol_`-prefixed); unknown names pass through.

    The bare form keeps its bareness (`getExchangeListings` -> `getAgoraListings`) because the gateway resolves bare
    names itself afterwards."""
    if not isinstance(name, str) or not name:
        return name
    hit = TOOL_ALIASES.get(name)
    bare = name[len(_PREFIX):] if name.startswith(_PREFIX) else name
    kind = "mcp_w3" if bare in _W3_RENAMED else "mcp"
    if hit is None and not name.startswith(_PREFIX):
        bare_hit = _RENAMED.get(name)
        if bare_hit is not None:
            count_legacy(kind)
            return bare_hit
        return name
    if hit is None:
        return name
    count_legacy(kind)
    return hit

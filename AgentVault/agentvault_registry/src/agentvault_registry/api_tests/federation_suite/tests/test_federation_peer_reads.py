"""§MCPTEST30 (tester batch 2 item 4, agentvault2-d3, Guild order gwo_e3bad842b1a5943022b01d40): two reads only a
federation peer may make, made by a peer.

getFederationPolicyCompliance and getFederationSyncStatusDev are NOT MEASURED in the MCP tester, by design: their routes
take a federation peer's identity (require_peer_registry_identity), which no MCP caller holds. Nothing read them as a
peer either: the compliance poller of another frame reads /federation/policy-compliance, and no row of the suite did.
Here sandbox-B's registry reads each with its own SVID at the address its own peer row names for sandbox-A (the
registry-card feed's probe, peer_feed_probe), and a caller with no certificate must be refused. The policy hash a peer
reads must be the one sandbox-A's own self-check names. The probe prints key names and the values asked for by name,
never a card or a secret.
"""
from __future__ import annotations

import re

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.peer_feed_probe import peer_feed_row
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, FederationTestRig

_SHA256 = re.compile(r"[0-9a-f]{64}")


@federation_test(
    name="federation_policy_compliance_read_by_a_peer",
    category="federation_discovery",
    budget_sec=90.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["policy-compliance", "federation-listing", "mtls", "read-only"],
)
async def test_policy_compliance_read_by_a_peer(rig: FederationTestRig) -> AssertionResult:
    """sandbox-B reads sandbox-A's policy hash as its compliance poller does; it is the hash sandbox-A names itself."""
    async def same_as_own(values):
        seen = values.get("policy_hash")
        if not (isinstance(seen, str) and _SHA256.fullmatch(seen)):
            return f"sandbox-A's policy-compliance answer names policy_hash={seen!r}, no sha256"
        own = await rig.mcp("sandbox-A-admin").call("getAdminFederationPolicyCompliance")
        mine = own.get("policy_hash") if isinstance(own, dict) else None
        if not (isinstance(mine, str) and _SHA256.fullmatch(mine)):
            return (f"sandbox-A's own self-check (getAdminFederationPolicyCompliance) names policy_hash={mine!r}, no "
                    f"sha256 to compare the peer's read with")
        if mine != seen:
            return (f"BUG-FIND: a peer reads sandbox-A's policy hash {seen[:12]}..., while sandbox-A's own self-check "
                    f"names {mine[:12]}...: the two answers of one registry disagree")
        return None
    return await peer_feed_row(rig, "/api/v1/federation/policy-compliance", "policy-compliance answer",
                               want_keys=("registry_did", "policy_hash", "policy_version"), echo=("policy_hash",),
                               check=same_as_own)


@federation_test(
    name="federation_sync_status_read_by_a_peer",
    category="federation_discovery",
    budget_sec=90.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["sync-status", "federation-listing", "mtls", "read-only"],
)
async def test_sync_status_read_by_a_peer(rig: FederationTestRig) -> AssertionResult:
    """sandbox-B reads sandbox-A's sync status; sandbox-A federates with sandbox-B, so it counts at least one peer."""
    async def counts_its_peers(values):
        n = values.get("total_peers")
        if not (isinstance(n, int) and n >= 1):
            return f"sandbox-A's sync status counts total_peers={n!r}, while sandbox-B, its peer, is reading it"
        if values.get("federation_enabled") is not True:
            return f"sandbox-A's sync status reads federation_enabled={values.get('federation_enabled')!r}"
        return None
    return await peer_feed_row(rig, "/api/v1/federation/sync-status", "sync status",
                               want_keys=("federation_enabled", "total_peers", "peer_status"),
                               echo=("federation_enabled", "total_peers"), check=counts_its_peers)

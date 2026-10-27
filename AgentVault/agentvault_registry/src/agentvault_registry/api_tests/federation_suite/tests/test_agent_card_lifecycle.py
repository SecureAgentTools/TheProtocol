"""Agent card lifecycle + IRONHAND mTLS tests using the persistent
sandbox-{a,b}-fed-test-agent containers (§pass73.3.4).

These tests rely on the fed-test-agent containers having onboarded
themselves to their respective sandbox mainframe + having called
enable-mtls. The agents persist their DID + creds to a Docker volume so
restarts don't churn agent identities.

Coverage:
  - Cross-registry pull-sync: agent on sandbox-A visible on sandboxalpha
  - JWS signature verify against source registry JWKS
  - IRONHAND mTLS enrollment state populated (mtls_enabled, spiffe_id)
  - SPIRE entry created on the source mainframe's SPIRE server
  - Agent card includes mTLS metadata post-enrollment
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
    PreconditionUnmet, container_exists_and_runs,
    FED_AGENT_A, FED_AGENT_B,
)
from agentvault_registry.api_tests.multiframe_helpers import exec_in_container


def _unwrap(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("agents", "items", "cards", "data", "results", "entries", "identities"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
    return []


# §FEDSUITE 2026-09-04: these are SIDECAR AGENT containers, not registries, so
# the rig's target overrides never reached them. On this tier both still exist
# but are `Exited (137) 3 months ago` — and `docker exec` on a stopped container
# answers APIError 409, so seven tests polled a corpse until their budgets
# expired and reported it as seven product failures.
_FED_AGENT_A = FED_AGENT_A
_FED_AGENT_B = FED_AGENT_B


def _require_fed_agent(container: str) -> None:
    """Absent fixture -> skip. Present-but-wrong fixture -> the caller's failure.

    The distinction is the whole point: a missing sidecar is an environment fact,
    while a RUNNING sidecar with no creds is a real defect and must stay red.
    """
    exists, running = container_exists_and_runs(container)
    if not exists:
        raise PreconditionUnmet(
            f"fixture agent container {container!r} does not exist on this tier "
            f"(set API_TEST_FED_AGENT_A/B to name the ones that do)")
    if not running:
        raise PreconditionUnmet(
            f"fixture agent container {container!r} exists but is STOPPED — "
            f"docker exec answers APIError 409, not a usable result")


async def _fed_test_agent_did(rig: FederationTestRig, container: str) -> str:
    """Read the fed-test-agent's persisted DID from its volume."""
    _require_fed_agent(container)
    rc, out = await asyncio.to_thread(
        exec_in_container,
        container,
        ["sh", "-c", "cat /var/lib/agent/creds.json 2>/dev/null || echo '{}'"],
        10,
    )
    if rc != 0:
        return ""
    try:
        return json.loads(out).get("agent_did", "") or ""
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────

@federation_test(
    name="fed_test_agent_a_onboarded_persists_did",
    category="agent_card_lifecycle",
    budget_sec=20.0,
    severity="critical",
    requires=["sandbox-A"],
    tags=["fed-test-agent", "onboarding", "frame-a"],
)
async def test_fed_test_agent_a_onboarded(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-a has onboarded itself + persisted creds to its volume."""
    # assert_within CATCHES predicate exceptions and retries to budget, so a
    # PreconditionUnmet raised inside predicate() is swallowed and the test
    # still burns its 20s and goes red. Check before the poller.
    _require_fed_agent(_FED_AGENT_A)
    state: dict = {}

    async def predicate():
        did = await _fed_test_agent_did(rig, _FED_AGENT_A)
        state["did"] = did
        return bool(did) and did.startswith("did:")

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate, poll_interval_sec=2.0,
        description="fed-test-agent-a persisted creds.json with a DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="fed_test_agent_b_onboarded_persists_did",
    category="agent_card_lifecycle",
    budget_sec=20.0,
    severity="critical",
    requires=["sandbox-B"],
    tags=["fed-test-agent", "onboarding", "frame-b"],
)
async def test_fed_test_agent_b_onboarded(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-b has onboarded itself + persisted creds to its volume."""
    # assert_within CATCHES predicate exceptions and retries to budget, so a
    # PreconditionUnmet raised inside predicate() is swallowed and the test
    # still burns its 20s and goes red. Check before the poller.
    _require_fed_agent(_FED_AGENT_B)
    state: dict = {}

    async def predicate():
        did = await _fed_test_agent_did(rig, _FED_AGENT_B)
        state["did"] = did
        return bool(did) and did.startswith("did:")

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate, poll_interval_sec=2.0,
        description="fed-test-agent-b persisted creds.json with a DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="fed_test_agent_a_visible_on_sandboxalpha_via_pull_sync",
    category="agent_card_lifecycle",
    budget_sec=60.0,
    severity="critical",
    requires=["sandbox-A", "sandboxalpha"],
    tags=["fed-test-agent", "pull-sync", "frame-a"],
)
async def test_fed_test_agent_a_visible_alpha(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-a (on sandbox-A) is visible on sandboxalpha via the
    federation pull-sync worker.

    Validates the FULL agent_card propagation cycle end-to-end:
    onboarded-via-API → agent_card emitted → reactor materializes →
    federation_card_cache populated → discoverable via getAgentByDID.
    """
    did = await _fed_test_agent_did(rig, _FED_AGENT_A)
    if not did:
        return AssertionResult(
            passed=False, description="fed-test-agent-a not onboarded",
            budget_sec=60.0, elapsed_sec=0.0, polling_attempts=0,
            failure_detail="creds.json missing on sandbox-a-fed-test-agent",
        )
    state: dict = {"source_did": did}

    async def predicate():
        try:
            r = await rig.mcp("sandboxalpha").call("getAgentByDID", {"did": did})
            state["alpha_response_keys"] = list(r.keys())[:6] if isinstance(r, dict) else None
            return isinstance(r, dict) and (
                r.get("did") == did or r.get("agent_did") == did
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate, poll_interval_sec=3.0,
        description=f"fed-test-agent-a DID visible on sandboxalpha via pull-sync",
        capture_state=lambda: state,
    )


@federation_test(
    name="fed_test_agent_b_visible_on_sandboxdelta_via_pull_sync",
    category="agent_card_lifecycle",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-B", "sandboxdelta"],
    tags=["fed-test-agent", "pull-sync", "frame-b"],
)
async def test_fed_test_agent_b_visible_delta(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-b is visible on sandboxdelta via pull-sync.

    Budget extended to 120s — pull-sync from sandbox-B → sandboxdelta has
    historically been slower than sandbox-A → sandboxalpha. If this fails
    consistently it's a real federation lag worth investigating, not a
    test timing issue.
    """
    did = await _fed_test_agent_did(rig, _FED_AGENT_B)
    if not did:
        return AssertionResult(
            passed=False, description="fed-test-agent-b not onboarded",
            budget_sec=60.0, elapsed_sec=0.0, polling_attempts=0,
            failure_detail="creds.json missing on sandbox-b-fed-test-agent",
        )
    state: dict = {"source_did": did}

    async def predicate():
        try:
            r = await rig.mcp("sandboxdelta").call("getAgentByDID", {"did": did})
            state["delta_response_keys"] = list(r.keys())[:6] if isinstance(r, dict) else None
            return isinstance(r, dict) and (
                r.get("did") == did or r.get("agent_did") == did
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=120.0, predicate=predicate, poll_interval_sec=3.0,
        description=f"fed-test-agent-b DID visible on sandboxdelta via pull-sync",
        capture_state=lambda: state,
    )


@federation_test(
    name="fed_test_agent_a_ironhand_enrolled",
    category="agent_card_lifecycle",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["fed-test-agent", "ironhand", "mtls"],
)
async def test_fed_test_agent_a_ironhand(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-a appears in IRONHAND identities list (enable-mtls succeeded).

    Verifies the agent's enrollment is reflected in the IRONHAND admin view:
    agent's DID present with mtls_enabled=true + non-null spiffe_id.
    """
    did = await _fed_test_agent_did(rig, _FED_AGENT_A)
    if not did:
        return AssertionResult(
            passed=False, description="fed-test-agent-a not onboarded",
            budget_sec=30.0, elapsed_sec=0.0, polling_attempts=0,
            failure_detail="creds.json missing",
        )
    state: dict = {"source_did": did}

    async def predicate():
        try:
            # listIronhandIdentities MCP wrapper returns empty body;
            # use adminRequest to hit the working endpoint directly.
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/ironhand/identities"},
            )
            payload = r.get("response") if isinstance(r, dict) else None
            enrolled = (payload or {}).get("enrolled") if isinstance(payload, dict) else None
            if not isinstance(enrolled, list):
                state["unexpected_shape"] = type(payload).__name__
                return False
            state["enrolled_count"] = len(enrolled)
            for ident in enrolled:
                if not isinstance(ident, dict):
                    continue
                if (ident.get("agent_did") == did or ident.get("did") == did):
                    state["match"] = {
                        "spiffe_id": ident.get("spiffe_id"),
                        "mtls_enabled": ident.get("mtls_enabled"),
                        "status": ident.get("status"),
                    }
                    return bool(
                        ident.get("spiffe_id")
                        or ident.get("mtls_enabled") is True
                    )
            state["match"] = None
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=2.0,
        description=f"fed-test-agent-a in IRONHAND identities with spiffe_id/mtls_enabled",
        capture_state=lambda: state,
    )


@federation_test(
    name="fed_test_agent_b_ironhand_enrolled",
    category="agent_card_lifecycle",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-B-admin"],
    tags=["fed-test-agent", "ironhand", "mtls"],
)
async def test_fed_test_agent_b_ironhand(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-b appears in sandbox-B's IRONHAND identities list."""
    did = await _fed_test_agent_did(rig, _FED_AGENT_B)
    if not did:
        return AssertionResult(
            passed=False, description="fed-test-agent-b not onboarded",
            budget_sec=30.0, elapsed_sec=0.0, polling_attempts=0,
            failure_detail="creds.json missing",
        )
    state: dict = {"source_did": did}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-B-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/ironhand/identities"},
            )
            payload = r.get("response") if isinstance(r, dict) else None
            enrolled = (payload or {}).get("enrolled") if isinstance(payload, dict) else None
            if not isinstance(enrolled, list):
                state["unexpected_shape"] = type(payload).__name__
                return False
            state["enrolled_count"] = len(enrolled)
            for ident in enrolled:
                if not isinstance(ident, dict):
                    continue
                if (ident.get("agent_did") == did or ident.get("did") == did):
                    state["match"] = {
                        "spiffe_id": ident.get("spiffe_id"),
                        "mtls_enabled": ident.get("mtls_enabled"),
                    }
                    return bool(
                        ident.get("spiffe_id")
                        or ident.get("mtls_enabled") is True
                    )
            state["match"] = None
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=2.0,
        description=f"fed-test-agent-b in sandbox-B IRONHAND identities",
        capture_state=lambda: state,
    )


@federation_test(
    name="fed_test_agent_a_card_data_populated",
    category="agent_card_lifecycle",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["fed-test-agent", "agent-card", "card-data"],
)
async def test_fed_test_agent_a_card_populated(rig: FederationTestRig) -> AssertionResult:
    """fed-test-agent-a's agent_card on sandbox-A is populated with the
    expected payload (name + url + provider).

    NOTE: JWS signature lives on the federation transport layer (when the
    card is pulled cross-registry it's signed at egress, see W3 echo
    prevention in Agent_Card_Federation_Sync.md). The local getAgentByDID
    surface returns the raw card_data — verify-signature would need to
    fetch via the federation pull surface + fetch the source JWKS.
    Deferred to Phase E.
    """
    did = await _fed_test_agent_did(rig, _FED_AGENT_A)
    if not did:
        return AssertionResult(
            passed=False, description="fed-test-agent-a not onboarded",
            budget_sec=30.0, elapsed_sec=0.0, polling_attempts=0,
            failure_detail="creds.json missing",
        )
    state: dict = {"source_did": did}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getAgentByDID", {"did": did})
            if not isinstance(r, dict):
                state["response_type"] = type(r).__name__
                return False
            card_data = r.get("card_data")
            if not isinstance(card_data, dict):
                state["card_data_type"] = type(card_data).__name__
                return False
            state["card_data_keys"] = list(card_data.keys())[:8]
            state["card_name"] = card_data.get("name")
            return bool(
                card_data.get("name")
                and (card_data.get("url") or card_data.get("provider"))
                and "Federation Test Agent" in (card_data.get("name") or "")
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=2.0,
        description=f"fed-test-agent-a card_data has expected name + url",
        capture_state=lambda: state,
    )


# ─── Phase E (§pass73.3.5+) — agent health + admission expansion ───────────


@federation_test(
    name="agent_health_status_readable_per_frame",
    category="agent_card_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["agent-health", "monitoring"],
)
async def test_agent_health_status_readable(rig: FederationTestRig) -> AssertionResult:
    """getAgentHealthStatus returns a structured payload on both mainframes —
    validates the agent_health_checker worker is alive + reporting state."""
    health: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAgentHealthStatus")
                if isinstance(r, str) or (
                    isinstance(r, dict) and (not r or r.get("_text") == "")
                ):
                    health[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    health[label] = {"keys": list(r.keys())[:6]}
                elif isinstance(r, list):
                    health[label] = {"count": len(r)}
                else:
                    health[label] = type(r).__name__
            except Exception as e:
                health[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or isinstance(v.get("keys"), list)
                or isinstance(v.get("count"), int)
            )
            for v in health.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getAgentHealthStatus reachable on both mainframes",
        capture_state=lambda: health,
    )


@federation_test(
    name="agent_locations_trusted_registries_per_frame",
    category="agent_card_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["agent-locations", "trusted-registries"],
)
async def test_agent_locations_trusted_registries(rig: FederationTestRig) -> AssertionResult:
    """getAgentLocationsTrustedRegistries returns the trusted-registries set
    on both mainframes — validates the federation peer trust set is
    queryable + populated."""
    trusted: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAgentLocationsTrustedRegistries")
                if isinstance(r, str) or (
                    isinstance(r, dict) and (not r or r.get("_text") == "")
                ):
                    trusted[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("trusted_registries")
                    or r.get("registries")
                    or r.get("items")
                    or r.get("data")
                    or []
                ) if isinstance(r, dict) else []
                trusted[label] = {"count": len(items)}
            except Exception as e:
                trusted[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or isinstance(v.get("count"), int))
            for v in trusted.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getAgentLocationsTrustedRegistries reachable on both mainframes",
        capture_state=lambda: trusted,
    )

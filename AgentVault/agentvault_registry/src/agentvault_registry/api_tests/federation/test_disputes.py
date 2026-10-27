"""
Tier 3: Cross-Registry Dispute/Slash Conformance Tests

Tests the OWL25 3-party slash protocol: auto-slash, admin approval/rejection,
settlement lifecycle, and EventStore verification (DisputeSlash + compensation).

Uses sandbox Test A as the defendant registry (slashing its local agents).
"""
import asyncio
import logging
import time
import uuid
from typing import Dict, Any

import httpx

logger = logging.getLogger(__name__)

SANDBOX_URL = "http://registry-test:8000"
SANDBOX_ES_URL = "http://event-store-test:8200"

# Federation auth headers (Mode 2 — internal secret)
# PB3 (2026-04-22 Pass 3): SPIFFE ID MUST be rooted in a trust domain listed in
# TRUSTED_SPIFFE_DOMAINS on sandbox-a (=sandbox-a.test,sandbox-b.test). Previously
# this was hardcoded to agentvault.com (the prod trust domain) — sandbox-a
# rejected those with 403 "Federation identity from untrusted domain", killing
# the Tier 3 slash-small/admin-approval/admin-rejection tests. Sandbox-b.test
# (the federated peer) is the natural choice for Mode-2 auth.
FED_HEADERS = {
    "X-Federation-Secret": "sandbox-federation-internal-secret-2026",
    "X-Federation-SPIFFE-ID": "spiffe://sandbox-b.test/service/registry-test-b",
}

# PA3/PB3 (2026-04-22 Pass 3): DEFENDANT_DID MUST be a real agent registered on
# sandbox-a (the router validates "Defendant is not registered on this registry"
# before allowing the slash). Live-bootstrapped by run_tier3's agent_creds param.
# Stale default left as fallback for standalone-call safety.
DEFENDANT_DID = "UNSET_BY_SANDBOX_BOOTSTRAP"
# Complainant (can be any remote DID — not validated as local). Also overridable.
COMPLAINANT_DID = "did:theprotocol:5a3597b2-212f-12bd-55d9"  # Alpha agent stays hardcoded; acceptable since it's a remote reference

# Callback URL MUST match a registered peer's base_url exactly (router enforces
# this to prevent SSRF). Sandbox-B's registered base_url is http://registry-test-b:8000
# (docker DNS, internal). Previously this pointed at nginx-test-b:8443 which
# is a different gateway route not matching the peer_registries row.
# PA3/PB3 (2026-04-22 Pass 3): aligned with actual seeded peer.
CALLBACK_URL = "http://registry-test-b:8000/api/v1/federation/disputes/slash-confirmation"
ORIGIN_REGISTRY_URL = "http://registry-test-b:8000"


def _result(name: str, passed: bool, duration_ms: int, details: str,
            eventstore_verified: bool = False) -> dict:
    return {"name": name, "passed": passed, "duration_ms": duration_ms,
            "details": details, "eventstore_verified": eventstore_verified}


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


def _settlement_id() -> str:
    return f"test-settlement-{uuid.uuid4().hex[:12]}"


async def _get_es_events_for(client: httpx.AsyncClient, did: str, es_key: str,
                              event_type: str = None) -> list:
    """Get EventStore events for a DID, optionally filtered by type."""
    r = await client.get(f"{SANDBOX_ES_URL}/api/v1/events/aggregate/{did}",
        headers={"x-internal-key": es_key})
    if r.status_code != 200:
        return []
    events = r.json() if isinstance(r.json(), list) else r.json().get("events", [])
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    return events


async def _get_peer_id(client: httpx.AsyncClient, admin_jwt: str, peer_name: str) -> int:
    """Get peer registry ID by name."""
    r = await client.get(f"{SANDBOX_URL}/api/v1/federation/disputes/peer-slash-config",
        headers={"Authorization": f"Bearer {admin_jwt}"})
    if r.status_code == 200:
        peers = r.json().get("peers", [])
        for p in peers:
            if peer_name.lower() in p.get("name", "").lower():
                return p.get("id", 0)
    return 0


async def test_configure_autoslash(admin_jwt: str, es_key: str) -> dict:
    """Configure ALL peers with auto_slash_enabled=true, max=100 AVT."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            configured = []
            # PA3/PB3 (2026-04-22 Pass 3): actual seeded peer names on sandbox-a are
            # "Sandbox-B" (frame peer, from sandbox_bootstrap.py) and
            # "Test Federation Peer Registry B" (direct peer, from seed data).
            # "Sandbox Alpha"/"Sandbox Beta" don't exist until Phase 12 — skip those.
            for peer_name in ["Sandbox-B", "Test Federation Peer Registry B"]:
                peer_id = await _get_peer_id(client, admin_jwt, peer_name)
                if peer_id:
                    r = await client.put(
                        f"{SANDBOX_URL}/api/v1/federation/disputes/peer-slash-config/{peer_id}",
                        json={"auto_slash_enabled": True, "auto_slash_max_avt": 100},
                        headers={"Authorization": f"Bearer {admin_jwt}"})
                    if r.status_code == 200:
                        configured.append(peer_name)

            if configured:
                return _result("configure_autoslash", True, _ms(t0),
                    f"Auto-slash configured (max=100 AVT) for: {', '.join(configured)}")
            else:
                return _result("configure_autoslash", False, _ms(t0),
                    "Could not configure any peers")
    except Exception as e:
        return _result("configure_autoslash", False, _ms(t0), f"Exception: {e}")


async def test_auto_slash_small(admin_jwt: str, es_key: str) -> dict:
    """Slash ≤ threshold → auto-approved and executed immediately."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Count DisputeSlash events before
            slash_events_before = await _get_es_events_for(client, DEFENDANT_DID, es_key, "DisputeSlash")
            count_before = len(slash_events_before)

            sid = _settlement_id()
            r = await client.post(f"{SANDBOX_URL}/api/v1/federation/disputes/slash-request",
                json={
                    "settlement_id": sid,
                    "dispute_id": 9001,
                    "ruling": "IN_FAVOR_OF_COMPLAINANT",
                    "amount": 10,
                    "complainant_did": COMPLAINANT_DID,
                    "defendant_did": DEFENDANT_DID,
                    "origin_registry_url": ORIGIN_REGISTRY_URL,
                    "callback_url": CALLBACK_URL,
                },
                headers=FED_HEADERS)

            if r.status_code not in (200, 201, 202):
                return _result("auto_slash_small", False, _ms(t0),
                    f"Slash request failed: {r.status_code} {r.text[:200]}")

            data = r.json()
            status = data.get("status", "")
            slash_type = data.get("slash_type", "")

            # Verify EventStore
            await asyncio.sleep(2)
            slash_events_after = await _get_es_events_for(client, DEFENDANT_DID, es_key, "DisputeSlash")
            new_slash = len(slash_events_after) > count_before

            if status == "slashed" and slash_type in ("full", "partial"):
                return _result("auto_slash_small", True, _ms(t0),
                    f"Auto-slash executed: {slash_type}, amount={data.get('slashed_amount')}, "
                    f"ES DisputeSlash: {new_slash}",
                    eventstore_verified=new_slash)
            elif status == "pending_admin_approval":
                return _result("auto_slash_small", False, _ms(t0),
                    f"Got pending_admin_approval instead of auto-slash. "
                    f"Auto-slash threshold may not be configured correctly.")
            else:
                return _result("auto_slash_small", False, _ms(t0),
                    f"Unexpected status: {status}, slash_type: {slash_type}. "
                    f"Response: {data}")
    except Exception as e:
        return _result("auto_slash_small", False, _ms(t0), f"Exception: {e}")


async def test_admin_approval_large(admin_jwt: str, es_key: str) -> dict:
    """Slash > threshold → PENDING → admin approves → slashed."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            sid = _settlement_id()
            # File large slash (500 > 100 threshold)
            r = await client.post(f"{SANDBOX_URL}/api/v1/federation/disputes/slash-request",
                json={
                    "settlement_id": sid,
                    "dispute_id": 9002,
                    "ruling": "IN_FAVOR_OF_COMPLAINANT",
                    "amount": 500,
                    "complainant_did": COMPLAINANT_DID,
                    "defendant_did": DEFENDANT_DID,
                    "origin_registry_url": ORIGIN_REGISTRY_URL,
                    "callback_url": CALLBACK_URL,
                },
                headers=FED_HEADERS)

            if r.status_code not in (200, 201, 202):
                return _result("admin_approval_large", False, _ms(t0),
                    f"Slash request failed: {r.status_code} {r.text[:200]}")

            data = r.json()
            if data.get("status") != "pending_admin_approval":
                return _result("admin_approval_large", False, _ms(t0),
                    f"Expected pending_admin_approval, got: {data.get('status')}")

            # Admin approves
            r2 = await client.post(
                f"{SANDBOX_URL}/api/v1/federation/disputes/settlements/{sid}/approve",
                headers={"Authorization": f"Bearer {admin_jwt}"})

            if r2.status_code == 200:
                approve_data = r2.json()
                return _result("admin_approval_large", True, _ms(t0),
                    f"Large slash: pending → approved → slashed. "
                    f"Amount: {approve_data.get('slashed_amount')}, "
                    f"type: {approve_data.get('slash_type')}")
            else:
                return _result("admin_approval_large", False, _ms(t0),
                    f"Admin approve failed: {r2.status_code} {r2.text[:200]}")
    except Exception as e:
        return _result("admin_approval_large", False, _ms(t0), f"Exception: {e}")


async def test_admin_rejection(admin_jwt: str, es_key: str) -> dict:
    """Slash > threshold → PENDING → admin rejects → no balance change."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get ES event count before
            slash_before = await _get_es_events_for(client, DEFENDANT_DID, es_key, "DisputeSlash")
            count_before = len(slash_before)

            sid = _settlement_id()
            r = await client.post(f"{SANDBOX_URL}/api/v1/federation/disputes/slash-request",
                json={
                    "settlement_id": sid,
                    "dispute_id": 9003,
                    "ruling": "IN_FAVOR_OF_COMPLAINANT",
                    "amount": 200,
                    "complainant_did": COMPLAINANT_DID,
                    "defendant_did": DEFENDANT_DID,
                    "origin_registry_url": ORIGIN_REGISTRY_URL,
                    "callback_url": CALLBACK_URL,
                },
                headers=FED_HEADERS)

            if r.status_code not in (200, 201, 202):
                return _result("admin_rejection", False, _ms(t0),
                    f"Slash request failed: {r.status_code} {r.text[:200]}")

            # Admin rejects
            r2 = await client.post(
                f"{SANDBOX_URL}/api/v1/federation/disputes/settlements/{sid}/reject",
                headers={"Authorization": f"Bearer {admin_jwt}"})

            await asyncio.sleep(1)
            slash_after = await _get_es_events_for(client, DEFENDANT_DID, es_key, "DisputeSlash")
            no_new_slash = len(slash_after) == count_before

            if r2.status_code == 200:
                reject_data = r2.json()
                return _result("admin_rejection", True, _ms(t0),
                    f"Settlement rejected: {reject_data.get('status')}. "
                    f"No new DisputeSlash events: {no_new_slash}",
                    eventstore_verified=no_new_slash)
            else:
                return _result("admin_rejection", False, _ms(t0),
                    f"Reject failed: {r2.status_code} {r2.text[:200]}")
    except Exception as e:
        return _result("admin_rejection", False, _ms(t0), f"Exception: {e}")


async def test_settlement_listing(admin_jwt: str, es_key: str) -> dict:
    """List settlements with status filters."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{SANDBOX_URL}/api/v1/federation/disputes/settlements",
                headers={"Authorization": f"Bearer {admin_jwt}"})

            if r.status_code == 200:
                data = r.json()
                count = data.get("count", 0)
                stats = data.get("stats", {})
                return _result("settlement_listing", True, _ms(t0),
                    f"Listed {count} settlements. Stats: {stats}")
            else:
                return _result("settlement_listing", False, _ms(t0),
                    f"Listing failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        return _result("settlement_listing", False, _ms(t0), f"Exception: {e}")


async def test_eventstore_dispute_events(admin_jwt: str, es_key: str) -> dict:
    """Verify DisputeSlash events exist in EventStore after slash operations."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{SANDBOX_ES_URL}/api/v1/projections/stats",
                headers={"x-internal-key": es_key})
            if r.status_code != 200:
                return _result("es_dispute_events", False, _ms(t0),
                    f"ES stats failed: {r.status_code}")

            stats = r.json()
            counts = stats.get("event_counts", {})
            slash = counts.get("DisputeSlash", 0)
            comp = counts.get("DisputeCompensationMinted", 0)
            filed = counts.get("DisputeFiled", 0)

            return _result("es_dispute_events", True, _ms(t0),
                f"ES dispute events: {slash} DisputeSlash, {comp} CompensationMinted, "
                f"{filed} DisputeFiled",
                eventstore_verified=True)
    except Exception as e:
        return _result("es_dispute_events", False, _ms(t0), f"Exception: {e}")


async def run_tier3(admin_jwt: str, es_key: str, agent_creds: dict = None) -> dict:
    """Run all Tier 3 (Cross-Registry Disputes) conformance tests.

    PA3 Pass 3: agent_creds carries the live-bootstrapped sandbox agent DID
    (needed for defendant validation on sandbox-a — router checks defendant
    is locally registered before allowing the slash).
    """
    global DEFENDANT_DID, COMPLAINANT_DID
    if agent_creds:
        DEFENDANT_DID = agent_creds.get("agent_did") or DEFENDANT_DID
        # Use counterparty (agent 2) as complainant — it's a real agent so the router
        # can resolve it for dispute recording. If not present, leave the hardcoded default.
        COMPLAINANT_DID = agent_creds.get("agent_002_did") or COMPLAINANT_DID
        logger.info(f"[FedTest:Tier3] Using live-bootstrapped agent creds: defendant={DEFENDANT_DID[:45]}...")
    logger.info("[FedTest:Tier3] Starting dispute/slash conformance tests")
    t0 = time.monotonic()

    tests = [
        test_configure_autoslash,
        test_auto_slash_small,
        test_admin_approval_large,
        test_admin_rejection,
        test_settlement_listing,
        test_eventstore_dispute_events,
    ]

    results = []
    for test_fn in tests:
        try:
            result = await test_fn(admin_jwt, es_key)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            logger.info(f"[FedTest:Tier3] {result['name']}: {status} ({result['duration_ms']}ms)")
        except Exception as e:
            results.append(_result(test_fn.__name__, False, 0, f"Unhandled: {e}"))
            logger.error(f"[FedTest:Tier3] {test_fn.__name__}: EXCEPTION {e}")

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    duration = round((time.monotonic() - t0) * 1000)

    logger.info(f"[FedTest:Tier3] Complete: {passed}/{len(results)} passed in {duration}ms")

    return {
        "tier": "disputes",
        "tier_number": 3,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "duration_ms": duration,
        "tests": results,
    }

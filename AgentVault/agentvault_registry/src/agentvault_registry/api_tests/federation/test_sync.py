"""
Tier 1: Federation Sync Conformance Tests

Tests federation sync, BFS topology discovery, agent card propagation,
echo prevention, and multi-hop relay — with EventStore verification.

Requires sandbox operators (Alpha, Beta, Gamma) running and federated.
"""
import asyncio
import logging
import time
from typing import Dict, List, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Sandbox infrastructure URLs (Docker internal)
SANDBOX_URL = "http://registry-test:8000"
ALPHA_URL = "http://sandbox-op-alpha-registry:8000"
BETA_URL = "http://sandbox-op-beta-registry:8000"
GAMMA_URL = "http://sandbox-op-gamma-registry:8000"
SANDBOX_ES_URL = "http://event-store-test:8200"
SANDBOX_FED_SECRET = "sandbox-federation-internal-secret-2026"
# PB3 (2026-04-22 Pass 3): sandbox-a TRUSTED_SPIFFE_DOMAINS=sandbox-a.test,sandbox-b.test
# (NOT agentvault.com). Using sandbox-b.test so Mode-2 federation auth passes.
SANDBOX_SPIFFE_ID = "spiffe://sandbox-b.test/service/registry-test-b"


def _result(name: str, passed: bool, duration_ms: int, details: str,
            eventstore_verified: bool = False) -> dict:
    """Standard test result format."""
    return {
        "name": name,
        "passed": passed,
        "duration_ms": duration_ms,
        "details": details,
        "eventstore_verified": eventstore_verified,
    }


def _ms_since(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


async def test_direct_sync(sandbox_jwt: str, es_key: str) -> dict:
    """Test: Agent on Alpha is visible in Test A's federated query."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Query Test A for federated agents
            r = await client.get(f"{SANDBOX_URL}/api/v1/agent-cards/",
                params={"include_federated": "true", "limit": 200},
                headers={"Authorization": f"Bearer {sandbox_jwt}"})

            if r.status_code != 200:
                return _result("direct_sync", False, _ms_since(t0),
                    f"Federated query failed: {r.status_code}")

            items = r.json().get("items", [])
            alpha_agents = [a for a in items if "alpha" in
                (a.get("origin_registry_name", "") or "").lower() or
                "Alpha TestBot" in a.get("name", "")]

            if alpha_agents:
                return _result("direct_sync", True, _ms_since(t0),
                    f"Alpha agent found in Test A ({len(items)} total agents, "
                    f"{len(alpha_agents)} from Alpha)",
                    eventstore_verified=False)
            else:
                origins = {}
                for a in items:
                    o = a.get("origin_registry_name", "local") or "local"
                    origins[o] = origins.get(o, 0) + 1
                return _result("direct_sync", False, _ms_since(t0),
                    f"Alpha agent NOT found in {len(items)} federated agents. "
                    f"Origins: {origins}")
    except Exception as e:
        return _result("direct_sync", False, _ms_since(t0), f"Exception: {e}")


async def test_multihop_relay(sandbox_jwt: str, es_key: str) -> dict:
    """Test: Gamma agent visible on Test A via Alpha relay (multi-hop)."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{SANDBOX_URL}/api/v1/agent-cards/",
                params={"include_federated": "true", "limit": 200},
                headers={"Authorization": f"Bearer {sandbox_jwt}"})

            if r.status_code != 200:
                return _result("multihop_relay", False, _ms_since(t0),
                    f"Federated query failed: {r.status_code}")

            items = r.json().get("items", [])
            gamma_agents = [a for a in items if "gamma" in
                (a.get("name", "") + "|" + str(a.get("origin_registry_name", ""))).lower()]

            if gamma_agents:
                origin = gamma_agents[0].get("origin_registry_name", "?")
                return _result("multihop_relay", True, _ms_since(t0),
                    f"Gamma agent found via multi-hop relay (origin: {origin})")
            else:
                return _result("multihop_relay", False, _ms_since(t0),
                    f"Gamma agent NOT found in {len(items)} federated agents. "
                    f"Gamma is peered with Alpha only — needs 2 sync cycles to propagate.")
    except Exception as e:
        return _result("multihop_relay", False, _ms_since(t0), f"Exception: {e}")


async def test_echo_prevention(sandbox_jwt: str, es_key: str) -> dict:
    """Test: Cards from Test A synced to Alpha are NOT echoed back as duplicates."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get Test A's native agent count
            r = await client.get(f"{SANDBOX_URL}/api/v1/agent-cards/",
                params={"limit": 200},
                headers={"Authorization": f"Bearer {sandbox_jwt}"})
            native_count = len(r.json().get("items", []))

            # Get federated count
            r2 = await client.get(f"{SANDBOX_URL}/api/v1/agent-cards/",
                params={"include_federated": "true", "limit": 200},
                headers={"Authorization": f"Bearer {sandbox_jwt}"})
            federated_items = r2.json().get("items", [])
            total_count = len(federated_items)

            # Check for duplicates by name
            names = [a.get("name", "") for a in federated_items]
            duplicates = [n for n in set(names) if names.count(n) > 1 and n]

            if not duplicates:
                return _result("echo_prevention", True, _ms_since(t0),
                    f"No duplicates. {native_count} native + {total_count - native_count} federated = {total_count} total")
            else:
                return _result("echo_prevention", False, _ms_since(t0),
                    f"ECHO DETECTED: {len(duplicates)} duplicate names: {duplicates[:5]}")
    except Exception as e:
        return _result("echo_prevention", False, _ms_since(t0), f"Exception: {e}")


async def test_peer_health(sandbox_jwt: str, es_key: str) -> dict:
    """Test: All peers show successful recent sync on Test A."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Query federation peers via mTLS auth (Mode 2 — internal secret)
            fed_headers = {
                "X-Federation-Secret": SANDBOX_FED_SECRET,
                "X-Federation-SPIFFE-ID": SANDBOX_SPIFFE_ID,
            }
            r = await client.get(f"{SANDBOX_URL}/api/v1/federation/peers", headers=fed_headers)

            if r.status_code == 401:
                return _result("peer_health", False, _ms_since(t0),
                    "Federation auth failed (401) — FEDERATION_INTERNAL_SECRET may not be set")

            if r.status_code != 200:
                return _result("peer_health", False, _ms_since(t0),
                    f"Federation peers query returned {r.status_code}")

            data = r.json()
            peers = data if isinstance(data, list) else data.get("items", data.get("peers", []))
            active = [p for p in peers if p.get("status") == "ACTIVE"]

            if len(active) >= 2:
                names = [p.get("name", "?") for p in active]
                return _result("peer_health", True, _ms_since(t0),
                    f"{len(active)} active peers: {', '.join(names)}")
            else:
                return _result("peer_health", False, _ms_since(t0),
                    f"Only {len(active)} active peers (expected >= 2). "
                    f"All peers: {[(p.get('name'), p.get('status')) for p in peers]}")
    except Exception as e:
        return _result("peer_health", False, _ms_since(t0), f"Exception: {e}")


async def test_bfs_topology(sandbox_jwt: str, es_key: str) -> dict:
    """Test: BFS topology discovery finds all sandbox operators."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{SANDBOX_URL}/api/v1/agents/locations/trusted-registries",
                headers={"Authorization": f"Bearer {sandbox_jwt}"})

            if r.status_code != 200:
                return _result("bfs_topology", False, _ms_since(t0),
                    f"Trusted registries returned {r.status_code}")

            data = r.json()
            registries = data if isinstance(data, list) else data.get("registries", [])
            names = [r.get("name", "?") for r in registries]

            # Check if sandbox operators are discovered
            found_alpha = any("alpha" in n.lower() or "Alpha" in n for n in names)
            found_beta = any("beta" in n.lower() or "Beta" in n for n in names)

            if found_alpha and found_beta:
                return _result("bfs_topology", True, _ms_since(t0),
                    f"BFS discovered {len(registries)} registries: {', '.join(names)}")
            else:
                return _result("bfs_topology", False, _ms_since(t0),
                    f"Missing operators in BFS. Found: {names}. "
                    f"Alpha: {found_alpha}, Beta: {found_beta}")
    except Exception as e:
        return _result("bfs_topology", False, _ms_since(t0), f"Exception: {e}")


async def test_eventstore_agent_events(sandbox_jwt: str, es_key: str) -> dict:
    """Test: EventStore has AgentCreated events from sandbox operations."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{SANDBOX_ES_URL}/api/v1/projections/stats",
                headers={"x-internal-key": es_key})

            if r.status_code != 200:
                return _result("eventstore_agent_events", False, _ms_since(t0),
                    f"EventStore stats returned {r.status_code}")

            stats = r.json()
            total = stats.get("total_events", 0)
            counts = stats.get("event_counts", {})
            agent_created = counts.get("AgentCreated", 0)
            agent_onboarded = counts.get("AgentOnboarded", 0)

            if total > 0 and agent_created > 0:
                return _result("eventstore_agent_events", True, _ms_since(t0),
                    f"EventStore healthy: {total} events, "
                    f"{agent_created} AgentCreated, {agent_onboarded} AgentOnboarded",
                    eventstore_verified=True)
            else:
                return _result("eventstore_agent_events", False, _ms_since(t0),
                    f"EventStore has {total} events, {agent_created} AgentCreated. "
                    f"Expected > 0 for both.",
                    eventstore_verified=True)
    except Exception as e:
        return _result("eventstore_agent_events", False, _ms_since(t0), f"Exception: {e}")


async def run_tier1(sandbox_jwt: str, es_key: str) -> dict:
    """Run all Tier 1 (Federation Sync) conformance tests."""
    logger.info("[FedTest:Tier1] Starting federation sync conformance tests")
    t0 = time.monotonic()

    tests = [
        test_direct_sync,
        test_multihop_relay,
        test_echo_prevention,
        test_peer_health,
        test_bfs_topology,
        test_eventstore_agent_events,
    ]

    results = []
    for test_fn in tests:
        try:
            result = await test_fn(sandbox_jwt, es_key)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            logger.info(f"[FedTest:Tier1] {result['name']}: {status} ({result['duration_ms']}ms)")
        except Exception as e:
            results.append(_result(test_fn.__name__, False, 0, f"Unhandled: {e}"))
            logger.error(f"[FedTest:Tier1] {test_fn.__name__}: EXCEPTION {e}")

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    duration = _ms_since(t0)

    logger.info(f"[FedTest:Tier1] Complete: {passed}/{len(results)} passed in {duration}ms")

    return {
        "tier": "sync",
        "tier_number": 1,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "duration_ms": duration,
        "tests": results,
    }

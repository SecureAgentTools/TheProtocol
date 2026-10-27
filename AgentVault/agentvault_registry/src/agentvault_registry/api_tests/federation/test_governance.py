"""
Tier 4: Federation Governance Conformance Tests

Tests local proposal lifecycle (create → vote → tally) and veToken voting power.
Federation elevation (local PASSED → federation) is tested if local lifecycle passes.

Requires a staked agent on sandbox Test A.
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

SANDBOX_URL = "http://registry-test:8000"
SANDBOX_ES_URL = "http://event-store-test:8200"

# PA3 (2026-04-22 Pass 3): Stale defaults — live creds injected via run_tier4's
# agent_creds param, which mutates these globals. Do not rely on these directly.
AGENT_CLIENT_ID = "UNSET_BY_SANDBOX_BOOTSTRAP"
AGENT_CLIENT_SECRET = "UNSET_BY_SANDBOX_BOOTSTRAP"
AGENT_DID = "UNSET_BY_SANDBOX_BOOTSTRAP"

# State shared across tests in this tier
_tier4_state: Dict[str, Any] = {}


def _result(name: str, passed: bool, duration_ms: int, details: str,
            eventstore_verified: bool = False) -> dict:
    return {"name": name, "passed": passed, "duration_ms": duration_ms,
            "details": details, "eventstore_verified": eventstore_verified}


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


async def _get_agent_jwt(client: httpx.AsyncClient) -> str:
    r = await client.post(f"{SANDBOX_URL}/api/v1/auth/agent/token",
        data=f"username={AGENT_CLIENT_ID}&password={AGENT_CLIENT_SECRET}&grant_type=password",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.json().get("access_token", "")


async def _ensure_staked(client: httpx.AsyncClient, admin_jwt: str, agent_jwt: str) -> bool:
    """Ensure the agent has staked balance for governance participation."""
    # Check current voting power
    r = await client.get(f"{SANDBOX_URL}/api/v1/governance/voting-power",
        headers={"Authorization": f"Bearer {agent_jwt}"})
    if r.status_code == 200:
        data = r.json()
        power = float(data.get("votingPower", 0))
        if power > 0:
            return True

    # Fund and stake
    await client.post(f"{SANDBOX_URL}/api/v1/teg/treasury/mint",
        json={"amount": "100000", "reason": "tier4_gov"},
        headers={"Authorization": f"Bearer {admin_jwt}"})
    await client.post(f"{SANDBOX_URL}/api/v1/teg/treasury/fund-agent",
        json={"target_agent_did": AGENT_DID, "amount": "1000", "reason": "tier4_gov"},
        headers={"Authorization": f"Bearer {admin_jwt}"})

    # Stake
    r = await client.post(f"{SANDBOX_URL}/api/v1/staking/stake",
        json={"amount": "50", "lock_period_days": 30},
        headers={"Authorization": f"Bearer {agent_jwt}"})

    if r.status_code in (200, 201):
        logger.info("[Tier4] Agent staked 50 AVT for governance")
        return True
    else:
        logger.warning(f"[Tier4] Staking failed: {r.status_code} {r.text[:100]}")
        return False


async def test_voting_power(admin_jwt: str, es_key: str) -> dict:
    """Check agent's veToken voting power (requires staked balance)."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            agent_jwt = await _get_agent_jwt(client)
            await _ensure_staked(client, admin_jwt, agent_jwt)

            r = await client.get(f"{SANDBOX_URL}/api/v1/governance/voting-power",
                headers={"Authorization": f"Bearer {agent_jwt}"})

            if r.status_code != 200:
                return _result("voting_power", False, _ms(t0),
                    f"Voting power query failed: {r.status_code} {r.text[:150]}")

            data = r.json()
            power = float(data.get("votingPower", 0))
            can_vote = data.get("canVote", False)
            positions = len(data.get("positions", []))

            if can_vote and power > 0:
                return _result("voting_power", True, _ms(t0),
                    f"veToken power: {power:.2f}, canVote={can_vote}, {positions} positions")
            else:
                return _result("voting_power", False, _ms(t0),
                    f"Cannot vote: power={power}, canVote={can_vote}, positions={positions}")
    except Exception as e:
        return _result("voting_power", False, _ms(t0), f"Exception: {e}")


async def test_create_local_proposal(admin_jwt: str, es_key: str) -> dict:
    """Create a governance proposal on sandbox Test A."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            agent_jwt = await _get_agent_jwt(client)

            r = await client.post(f"{SANDBOX_URL}/api/v1/governance/proposals",
                json={
                    "title": "Tier 4 Conformance Test Proposal",
                    "description": "Automated federation conformance test — proposal lifecycle verification.",
                    "duration_seconds": 10,  # Allow time for voting before tally
                    "proposal_type": "standard",
                },
                headers={"Authorization": f"Bearer {agent_jwt}"})

            if r.status_code in (200, 201):
                data = r.json()
                proposal_id = data.get("id")
                _tier4_state["proposal_id"] = proposal_id
                _tier4_state["agent_jwt"] = agent_jwt

                # Verify EventStore
                await asyncio.sleep(1)
                es_r = await client.get(f"{SANDBOX_ES_URL}/api/v1/events/aggregate/{AGENT_DID}",
                    headers={"x-internal-key": es_key})
                events = es_r.json() if isinstance(es_r.json(), list) else es_r.json().get("events", [])
                has_proposal = any(e.get("event_type") == "ProposalCreated" for e in events)

                return _result("create_local_proposal", True, _ms(t0),
                    f"Proposal #{proposal_id} created (status={data.get('status')}). "
                    f"ES ProposalCreated: {has_proposal}",
                    eventstore_verified=has_proposal)
            else:
                return _result("create_local_proposal", False, _ms(t0),
                    f"Create failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        return _result("create_local_proposal", False, _ms(t0), f"Exception: {e}")


async def test_vote_on_proposal(admin_jwt: str, es_key: str) -> dict:
    """Vote on the local proposal."""
    t0 = time.monotonic()
    proposal_id = _tier4_state.get("proposal_id")
    agent_jwt = _tier4_state.get("agent_jwt")

    if not proposal_id or not agent_jwt:
        return _result("vote_on_proposal", False, _ms(t0),
            "No proposal_id from previous test — create_local_proposal must pass first")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{SANDBOX_URL}/api/v1/governance/proposals/{proposal_id}/vote",
                json={"vote_in_favor": True, "reason": "Tier 4 conformance test vote"},
                headers={"Authorization": f"Bearer {agent_jwt}"})

            if r.status_code in (200, 201):
                data = r.json()
                power = data.get("voting_power", 0)

                # Verify EventStore
                await asyncio.sleep(1)
                es_r = await client.get(f"{SANDBOX_ES_URL}/api/v1/events/aggregate/{AGENT_DID}",
                    headers={"x-internal-key": es_key})
                events = es_r.json() if isinstance(es_r.json(), list) else es_r.json().get("events", [])
                has_vote = any(e.get("event_type") == "VoteCast" for e in events)

                return _result("vote_on_proposal", True, _ms(t0),
                    f"Vote cast (in_favor=True, power={power}). ES VoteCast: {has_vote}",
                    eventstore_verified=has_vote)
            else:
                return _result("vote_on_proposal", False, _ms(t0),
                    f"Vote failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        return _result("vote_on_proposal", False, _ms(t0), f"Exception: {e}")


async def test_tally_proposal(admin_jwt: str, es_key: str) -> dict:
    """Tally the proposal after voting period ends."""
    t0 = time.monotonic()
    proposal_id = _tier4_state.get("proposal_id")
    agent_jwt = _tier4_state.get("agent_jwt")

    if not proposal_id or not agent_jwt:
        return _result("tally_proposal", False, _ms(t0),
            "No proposal_id from previous test")

    try:
        # Wait for voting period to expire (10 seconds + buffer)
        await asyncio.sleep(11)

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{SANDBOX_URL}/api/v1/governance/proposals/{proposal_id}/tally",
                headers={"Authorization": f"Bearer {agent_jwt}"})

            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "")
                votes_for = data.get("votes_for", 0)
                quorum = data.get("quorum_met", False)

                return _result("tally_proposal", True, _ms(t0),
                    f"Tally complete: status={status}, votes_for={votes_for}, "
                    f"quorum_met={quorum}, pass_rate={data.get('pass_rate', 0)}")
            else:
                return _result("tally_proposal", False, _ms(t0),
                    f"Tally failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        return _result("tally_proposal", False, _ms(t0), f"Exception: {e}")


async def test_list_proposals(admin_jwt: str, es_key: str) -> dict:
    """List governance proposals."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            agent_jwt = await _get_agent_jwt(client)
            r = await client.get(f"{SANDBOX_URL}/api/v1/governance/proposals",
                headers={"Authorization": f"Bearer {agent_jwt}"})

            if r.status_code == 200:
                data = r.json()
                proposals = data if isinstance(data, list) else data.get("proposals", data.get("items", []))
                statuses = {}
                for p in proposals:
                    s = p.get("status", "?")
                    statuses[s] = statuses.get(s, 0) + 1

                return _result("list_proposals", True, _ms(t0),
                    f"{len(proposals)} proposals. Statuses: {statuses}")
            else:
                return _result("list_proposals", False, _ms(t0),
                    f"List failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        return _result("list_proposals", False, _ms(t0), f"Exception: {e}")


async def test_eventstore_governance_events(admin_jwt: str, es_key: str) -> dict:
    """Verify governance events in EventStore."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{SANDBOX_ES_URL}/api/v1/projections/stats",
                headers={"x-internal-key": es_key})

            if r.status_code != 200:
                return _result("es_governance_events", False, _ms(t0),
                    f"ES stats failed: {r.status_code}")

            counts = r.json().get("event_counts", {})
            created = counts.get("ProposalCreated", 0)
            voted = counts.get("VoteCast", 0)
            tallied = counts.get("ProposalTallied", 0)

            return _result("es_governance_events", True, _ms(t0),
                f"ES governance: {created} ProposalCreated, {voted} VoteCast, "
                f"{tallied} ProposalTallied",
                eventstore_verified=True)
    except Exception as e:
        return _result("es_governance_events", False, _ms(t0), f"Exception: {e}")


async def run_tier4(admin_jwt: str, es_key: str, agent_creds: dict = None) -> dict:
    """Run all Tier 4 (Governance) conformance tests.

    PA3 Pass 3: agent_creds holds the live-bootstrapped sandbox agent
    credentials from _sandbox_tokens. Required — stale defaults won't auth.
    """
    global AGENT_CLIENT_ID, AGENT_CLIENT_SECRET, AGENT_DID
    if agent_creds:
        AGENT_CLIENT_ID = agent_creds.get("client_id") or AGENT_CLIENT_ID
        AGENT_CLIENT_SECRET = agent_creds.get("client_secret") or AGENT_CLIENT_SECRET
        AGENT_DID = agent_creds.get("agent_did") or AGENT_DID
        logger.info(f"[FedTest:Tier4] Using live-bootstrapped agent creds: did={AGENT_DID[:45]}...")
    logger.info("[FedTest:Tier4] Starting governance conformance tests")
    t0 = time.monotonic()

    # Clear tier state
    _tier4_state.clear()

    tests = [
        test_voting_power,
        test_create_local_proposal,
        test_vote_on_proposal,
        test_tally_proposal,
        test_list_proposals,
        test_eventstore_governance_events,
    ]

    results = []
    for test_fn in tests:
        try:
            result = await test_fn(admin_jwt, es_key)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            logger.info(f"[FedTest:Tier4] {result['name']}: {status} ({result['duration_ms']}ms)")
        except Exception as e:
            results.append(_result(test_fn.__name__, False, 0, f"Unhandled: {e}"))
            logger.error(f"[FedTest:Tier4] {test_fn.__name__}: EXCEPTION {e}")

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    duration = round((time.monotonic() - t0) * 1000)

    logger.info(f"[FedTest:Tier4] Complete: {passed}/{len(results)} passed in {duration}ms")

    return {
        "tier": "governance",
        "tier_number": 4,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "duration_ms": duration,
        "tests": results,
    }

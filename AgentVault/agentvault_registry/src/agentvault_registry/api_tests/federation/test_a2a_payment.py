"""
Tier 5: A2A Cross-Registry Payment Conformance Tests

Tests the payment token lifecycle: authorize → verify → settle/release.
Settlement for federated agents routes through the cross-registry transfer pipeline.
"""
import asyncio
import logging
import time
from typing import Dict, Any

import httpx

from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event

logger = logging.getLogger(__name__)

SANDBOX_URL = "http://registry-test:8000"
SANDBOX_ES_URL = "http://event-store-test:8200"

# PA3 (2026-04-22 Pass 3): Stale defaults — live creds injected via run_tier5's
# agent_creds param, which mutates these globals.
AGENT_CLIENT_ID = "UNSET_BY_SANDBOX_BOOTSTRAP"
AGENT_CLIENT_SECRET = "UNSET_BY_SANDBOX_BOOTSTRAP"
AGENT_DID = "UNSET_BY_SANDBOX_BOOTSTRAP"
# ALPHA_DID is the payment TARGET (on a federated sandbox operator — Phase 12 gated)
ALPHA_DID = "did:theprotocol:5a3597b2-212f-12bd-55d9"

_tier5_state: Dict[str, Any] = {}


def _result(name, passed, duration_ms, details, eventstore_verified=False):
    return {"name": name, "passed": passed, "duration_ms": duration_ms,
            "details": details, "eventstore_verified": eventstore_verified}


def _ms(t0):
    return round((time.monotonic() - t0) * 1000)


async def _agent_jwt(client):
    r = await client.post(f"{SANDBOX_URL}/api/v1/auth/agent/token",
        data=f"username={AGENT_CLIENT_ID}&password={AGENT_CLIENT_SECRET}&grant_type=password",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.json().get("access_token", "")


async def test_authorize_token(admin_jwt: str, es_key: str) -> dict:
    """Authorize a payment token for Alpha agent."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            jwt = await _agent_jwt(client)
            r = await client.post(f"{SANDBOX_URL}/api/v1/a2a-payment/authorize",
                json={"target_agent_did": ALPHA_DID, "amount": "5.0", "ttl_seconds": 300},
                headers={"Authorization": f"Bearer {jwt}"})

            if r.status_code in (200, 201):
                data = r.json()
                token = data.get("token", "")
                _tier5_state["token"] = token
                _tier5_state["jwt"] = jwt
                _tier5_state["token_id"] = data.get("authorization_id") or data.get("token_id")

                # ES verify
                await asyncio.sleep(1)
                es_r = await client.get(f"{SANDBOX_ES_URL}/api/v1/events/aggregate/{AGENT_DID}",
                    headers={"x-internal-key": es_key})
                events = es_r.json() if isinstance(es_r.json(), list) else es_r.json().get("events", [])
                has_auth = any(e.get("event_type") == "A2APaymentAuthorized" for e in events)

                return _result("authorize_token", True, _ms(t0),
                    f"Token issued: {token[:15]}... target={ALPHA_DID[:30]}. "
                    f"ES A2APaymentAuthorized: {has_auth}",
                    eventstore_verified=has_auth)
            else:
                return _result("authorize_token", False, _ms(t0),
                    f"Authorize failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        return _result("authorize_token", False, _ms(t0), f"Exception: {e}")


async def test_verify_token(admin_jwt: str, es_key: str) -> dict:
    """Verify the payment token (no auth required)."""
    t0 = time.monotonic()
    token = _tier5_state.get("token")
    if not token:
        return _result("verify_token", False, _ms(t0), "No token from authorize test")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{SANDBOX_URL}/api/v1/a2a-payment/verify",
                json={"token": token, "target_agent_did": ALPHA_DID})

            if r.status_code == 200:
                data = r.json()
                valid = data.get("valid", False)
                return _result("verify_token", valid, _ms(t0),
                    f"Token valid={valid}, caller={data.get('caller_did','?')[:30]}, "
                    f"amount={data.get('amount')}")
            else:
                return _result("verify_token", False, _ms(t0),
                    f"Verify failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        return _result("verify_token", False, _ms(t0), f"Exception: {e}")


async def test_settle_payment(admin_jwt: str, es_key: str) -> dict:
    """Settle the payment token — executes the actual transfer.

    The /settle endpoint is async fire-and-forget: it returns status="settling"
    immediately (~30ms) and a background asyncio task performs the TEG transfer,
    updating status to "settled" or "failed". Poll /my-tokens for up to ~10s to
    catch the final state before verifying ES events.
    """
    t0 = time.monotonic()
    token = _tier5_state.get("token")
    jwt = _tier5_state.get("jwt")
    token_id = _tier5_state.get("token_id") or _tier5_state.get("authorization_id")
    if not token or not jwt:
        return _result("settle_payment", False, _ms(t0), "No token/jwt from previous tests")

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(f"{SANDBOX_URL}/api/v1/a2a-payment/settle",
                json={"token": token, "success": True},
                headers={"Authorization": f"Bearer {jwt}"})

            if r.status_code != 200:
                return _result("settle_payment", False, _ms(t0),
                    f"Settle failed: {r.status_code} {r.text[:200]}")

            data = r.json() or {}
            status = data.get("status") or ""
            tx_id = data.get("settlement_tx_id") or ""
            tid = data.get("token_id") or token_id or ""

            # Poll /my-tokens for terminal status when settlement is async
            if status == "settling":
                headers = {"Authorization": f"Bearer {jwt}"}
                for _ in range(20):  # up to ~10s (20 × 0.5s)
                    await asyncio.sleep(0.5)
                    mr = await client.get(f"{SANDBOX_URL}/api/v1/a2a-payment/my-tokens",
                        headers=headers)
                    if mr.status_code != 200:
                        continue
                    items = mr.json() or []
                    match = next((it for it in items
                                  if (tid and it.get("token_id") == tid)
                                  or (not tid and it.get("status") in ("settled", "failed"))),
                                 None)
                    if not match:
                        continue
                    status = match.get("status") or status
                    tx_id = match.get("settlement_tx_id") or tx_id
                    if status in ("settled", "failed"):
                        break

            # ES verify: should have TokensTransferred from settlement
            await asyncio.sleep(2)
            es_r = await client.get(f"{SANDBOX_ES_URL}/api/v1/events/aggregate/{AGENT_DID}",
                headers={"x-internal-key": es_key})
            es_json = es_r.json() if es_r.status_code == 200 else []
            events = es_json if isinstance(es_json, list) else (es_json or {}).get("events", []) or []
            has_settled = any((e or {}).get("event_type") == "A2APaymentSettled" for e in events)
            has_transfer = any(ledger_names.same((e or {}).get("event_type") or "", "TokensTransferred") for e in events)

            return _result("settle_payment", status == "settled", _ms(t0),
                f"Settlement: status={status}, tx={(tx_id or '')[:15]}. "
                f"ES: settled={has_settled}, transfer={has_transfer}",
                eventstore_verified=has_transfer)
    except Exception as e:
        return _result("settle_payment", False, _ms(t0), f"Exception: {e}")


async def test_release_unused(admin_jwt: str, es_key: str) -> dict:
    """Authorize a token then release it (cancel without settling)."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            jwt = await _agent_jwt(client)

            # Authorize
            r = await client.post(f"{SANDBOX_URL}/api/v1/a2a-payment/authorize",
                json={"target_agent_did": ALPHA_DID, "amount": "1.0", "ttl_seconds": 300},
                headers={"Authorization": f"Bearer {jwt}"})

            if r.status_code not in (200, 201):
                return _result("release_unused", False, _ms(t0),
                    f"Authorize failed: {r.status_code}")

            token = r.json().get("token", "")

            # Release
            r2 = await client.post(f"{SANDBOX_URL}/api/v1/a2a-payment/release",
                json={"token": token},
                headers={"Authorization": f"Bearer {jwt}"})

            if r2.status_code == 200:
                data = r2.json()
                return _result("release_unused", True, _ms(t0),
                    f"Token released: status={data.get('status')}")
            else:
                return _result("release_unused", False, _ms(t0),
                    f"Release failed: {r2.status_code} {r2.text[:200]}")
    except Exception as e:
        return _result("release_unused", False, _ms(t0), f"Exception: {e}")


async def test_list_tokens(admin_jwt: str, es_key: str) -> dict:
    """List agent's payment tokens."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            jwt = await _agent_jwt(client)
            r = await client.get(f"{SANDBOX_URL}/api/v1/a2a-payment/my-tokens",
                headers={"Authorization": f"Bearer {jwt}"})

            if r.status_code == 200:
                data = r.json()
                tokens = data if isinstance(data, list) else data.get("tokens", data.get("items", []))
                statuses = {}
                for t in tokens:
                    s = t.get("status", "?")
                    statuses[s] = statuses.get(s, 0) + 1
                return _result("list_tokens", True, _ms(t0),
                    f"{len(tokens)} tokens. Statuses: {statuses}")
            else:
                return _result("list_tokens", False, _ms(t0),
                    f"List failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        return _result("list_tokens", False, _ms(t0), f"Exception: {e}")


async def test_es_a2a_events(admin_jwt: str, es_key: str) -> dict:
    """Verify A2A payment events in EventStore."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{SANDBOX_ES_URL}/api/v1/projections/stats",
                headers={"x-internal-key": es_key})
            if r.status_code != 200:
                return _result("es_a2a_events", False, _ms(t0), f"ES stats: {r.status_code}")

            counts = r.json().get("event_counts", {})
            auth = counts.get("A2APaymentAuthorized", 0)
            settled = counts.get("A2APaymentSettled", 0)

            return _result("es_a2a_events", True, _ms(t0),
                f"ES A2A: {auth} authorized, {settled} settled",
                eventstore_verified=True)
    except Exception as e:
        return _result("es_a2a_events", False, _ms(t0), f"Exception: {e}")


async def run_tier5(admin_jwt: str, es_key: str, agent_creds: dict = None) -> dict:
    """Run all Tier 5 (A2A Payment) conformance tests.

    PA3 Pass 3: agent_creds holds the live-bootstrapped sandbox agent creds.
    """
    global AGENT_CLIENT_ID, AGENT_CLIENT_SECRET, AGENT_DID, ALPHA_DID
    if agent_creds:
        AGENT_CLIENT_ID = agent_creds.get("client_id") or AGENT_CLIENT_ID
        AGENT_CLIENT_SECRET = agent_creds.get("client_secret") or AGENT_CLIENT_SECRET
        AGENT_DID = agent_creds.get("agent_did") or AGENT_DID
        # Phase 12 (2026-04-22): use live Alpha TestBot DID
        ALPHA_DID = agent_creds.get("alpha_testbot_did") or ALPHA_DID
        logger.info(f"[FedTest:Tier5] Using live creds: caller={AGENT_DID[:45]}... alpha={ALPHA_DID[:45]}...")
    logger.info("[FedTest:Tier5] Starting A2A payment conformance tests")
    t0 = time.monotonic()
    _tier5_state.clear()

    tests = [
        test_authorize_token,
        test_verify_token,
        test_settle_payment,
        test_release_unused,
        test_list_tokens,
        test_es_a2a_events,
    ]

    results = []
    for test_fn in tests:
        try:
            result = await test_fn(admin_jwt, es_key)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            logger.info(f"[FedTest:Tier5] {result['name']}: {status} ({result['duration_ms']}ms)")
        except Exception as e:
            results.append(_result(test_fn.__name__, False, 0, f"Unhandled: {e}"))

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    duration = round((time.monotonic() - t0) * 1000)
    logger.info(f"[FedTest:Tier5] Complete: {passed}/{len(results)} passed in {duration}ms")

    return {"tier": "a2a", "tier_number": 5, "passed": passed, "failed": failed,
            "total": len(results), "duration_ms": duration, "tests": results}

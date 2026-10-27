"""Token fixtures (AAA+ refactor 2026-05-21).

Replaces the inline _onboard_agent_and_get_token + _fund_and_stake_agent
+ get_sandbox_tokens logic in admin_api_test.py:40-549.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from ..core.fixtures import fixture
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE

logger = logging.getLogger(__name__)

API_TEST_TARGET_URL = os.environ.get("API_TEST_TARGET_URL", "http://registry-test:8000")
SANDBOX_ADMIN_EMAIL = os.environ.get("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox")
SANDBOX_ADMIN_PASSWORD = os.environ.get("SANDBOX_ADMIN_PASSWORD", SANDBOX_ADMIN_PASSWORD)


async def _post(client: httpx.AsyncClient, path: str, **kwargs):
    return await client.post(f"{API_TEST_TARGET_URL.rstrip('/')}{path}", **kwargs)


@fixture(scope="session")
async def admin_token() -> str:
    """Sandbox-A commander developer JWT. Form-encoded login."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        r = await _post(
            client,
            "/api/v1/auth/login",
            data={"username": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        logger.info(f"admin_token fixture: acquired sandbox-A admin JWT (len={len(token)})")
        return token


@fixture(scope="session")
async def primary_agent(admin_token: str) -> Dict[str, Any]:
    """Onboard a primary test agent. Returns {did, client_id, client_secret}."""
    ts = int(time.time() * 1000)
    label = "primary"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Bootstrap
        r = await _post(
            client,
            "/api/v1/onboard/bootstrap/request-token",
            json={"agent_type_hint": "api_test_agent", "requested_by": f"api_tester_{label}"},
            headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        bootstrap_token = r.json()["bootstrap_token"]

        # Create
        card = _make_agent_card(label, ts)
        r = await _post(
            client,
            "/api/v1/onboard/create_agent",
            json={"agent_did_method": "theprotocol", "agent_card": card},
            headers={"Bootstrap-Token": bootstrap_token, "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        agent = {
            "did": data["agent_did"],
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
        }
        logger.info(f"primary_agent fixture: onboarded {agent['did']}")
        return agent


@fixture(scope="session")
async def counterparty(admin_token: str) -> Dict[str, Any]:
    """Onboard a counterparty agent (for transfers, disputes, contracts)."""
    ts = int(time.time() * 1000)
    label = "counterparty"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await _post(
            client,
            "/api/v1/onboard/bootstrap/request-token",
            json={"agent_type_hint": "api_test_agent", "requested_by": f"api_tester_{label}"},
            headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        bootstrap_token = r.json()["bootstrap_token"]

        card = _make_agent_card(label, ts)
        r = await _post(
            client,
            "/api/v1/onboard/create_agent",
            json={"agent_did_method": "theprotocol", "agent_card": card},
            headers={"Bootstrap-Token": bootstrap_token, "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        return {
            "did": data["agent_did"],
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
        }


@fixture(scope="session")
async def primary_agent_token(primary_agent: Dict[str, Any]) -> str:
    """Mint an agent JWT for the primary agent."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        r = await _post(
            client,
            "/api/v1/auth/agent/token",
            data={
                "grant_type": "password",
                "username": primary_agent["client_id"],
                "password": primary_agent["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        logger.info(f"primary_agent_token fixture: minted agent JWT")
        return token


@fixture(scope="session")
async def counterparty_token(counterparty: Dict[str, Any]) -> str:
    """Mint an agent JWT for the counterparty agent."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        r = await _post(
            client,
            "/api/v1/auth/agent/token",
            data={
                "grant_type": "password",
                "username": counterparty["client_id"],
                "password": counterparty["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        return r.json()["access_token"]


def _make_agent_card(label: str, ts: int) -> Dict[str, Any]:
    """Standard test agent card payload."""
    from datetime import datetime, timezone
    return {
        "schemaVersion": "1.0",
        "agentVersion": "1.0",
        "name": f"API Test Agent {label.title()} {ts}",
        "description": f"Auto-onboarded {label} agent for AAA+ tester",
        "url": f"http://localhost:8100/agents/api-test-{label}-{ts}",
        "humanReadableId": f"api-test-{label}-{ts}",
        "provider": {
            "name": "API Test Framework",
            "organization": "AgentVault",
            "contact": "test@theprotocol.cloud",
        },
        "capabilities": {
            "a2aVersion": "1.0",
            "inbound_protocols": ["cosv1", "avtp"],
            "outbound_protocols": ["cosv1", "avtp"],
            "tags": ["test", "api-tester", "automated", label],
        },
        "authSchemes": [{
            "scheme": "oauth2",
            "client_id": "pending",
            "tokenUrl": f"{API_TEST_TARGET_URL}/api/v1/auth/agent/token",
        }],
        "service_endpoints": [{
            "type": "messaging",
            "url": f"http://localhost:8100/agents/api-test-{label}-{ts}",
        }],
        "metadata": {
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "status": "active",
            "teg_enabled": True,
            "test_type": "api_tester",
        },
    }

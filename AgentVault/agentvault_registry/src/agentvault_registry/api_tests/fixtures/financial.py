"""Financial fixtures: funding + staking (AAA+ refactor 2026-05-21).

Funds agents from the treasury so financial tests have working balances.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Dict

import httpx

from ..core.fixtures import fixture

logger = logging.getLogger(__name__)

API_TEST_TARGET_URL = os.environ.get("API_TEST_TARGET_URL", "http://registry-test:8000")


async def _balance(client: httpx.AsyncClient, did: str, admin_token: str) -> Decimal:
    r = await client.get(
        f"{API_TEST_TARGET_URL.rstrip('/')}/api/v1/teg/balance",
        params={"agent_did": did},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    if r.status_code != 200:
        return Decimal("0")
    try:
        return Decimal(str(r.json().get("balance", "0")))
    except Exception:
        return Decimal("0")


@fixture(scope="session")
async def funded_primary(primary_agent: Dict[str, Any], admin_token: str) -> Dict[str, Any]:
    """Ensure primary_agent has at least 100 AVT liquid balance. Returns primary_agent dict."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        cur = await _balance(client, primary_agent["did"], admin_token)
        target = Decimal("100")
        if cur < target:
            need = target - cur
            r = await client.post(
                f"{API_TEST_TARGET_URL.rstrip('/')}/api/v1/teg/treasury/fund-agent",
                json={"agent_did": primary_agent["did"], "amount": str(need), "memo": "AAA+ fixture"},
                headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
            )
            if r.status_code == 200:
                logger.info(
                    f"funded_primary: topped up {primary_agent['did']} by {need} AVT (was {cur})"
                )
            else:
                logger.warning(f"funded_primary: top-up failed ({r.status_code}): {r.text[:160]}")
        return primary_agent


@fixture(scope="session")
async def funded_counterparty(counterparty: Dict[str, Any], admin_token: str) -> Dict[str, Any]:
    """Ensure counterparty has at least 100 AVT liquid balance."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        cur = await _balance(client, counterparty["did"], admin_token)
        target = Decimal("100")
        if cur < target:
            need = target - cur
            r = await client.post(
                f"{API_TEST_TARGET_URL.rstrip('/')}/api/v1/teg/treasury/fund-agent",
                json={"agent_did": counterparty["did"], "amount": str(need), "memo": "AAA+ fixture"},
                headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
            )
            if r.status_code != 200:
                logger.warning(f"funded_counterparty: top-up failed ({r.status_code})")
        return counterparty

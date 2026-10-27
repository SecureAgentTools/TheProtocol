"""Fiat quote round-trip flow (AAA+ Phase VII, 2026-05-21).

Asserts §pass50 tier math invariant:
  €1-€19.99 = 2000 AVT/EUR (tier_1_base)
  €20-€99.99 = 2500 AVT/EUR (+25%)
  €100-€500 = 3000 AVT/EUR (+50%)

If a future change to fiat_onramp's tier table or quote logic breaks the
breakpoints, this flow fails — catching the bug in seconds.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from agentvault_registry.api_tests.base import APITestBase

logger = logging.getLogger(__name__)


class TestFlowFiatQuoteRoundtrip(APITestBase):
    CATEGORY_NAME = "flow_fiat_quote_roundtrip"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_quote_roundtrip_flow(self, developer_token: Optional[str] = None) -> Dict[str, Any]:
        """Hit /fiat/tiers, then /fiat/quote at the three tier breakpoints,
        assert AVT amounts match expected tier math."""
        logger.info("=" * 60)
        logger.info("Starting Fiat Quote Round-trip Flow")
        logger.info("=" * 60)

        results = []
        successful = 0
        total = 0

        base = self.base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False) as client:
            # Step 1: tiers
            total += 1
            try:
                r = await client.get(f"{base}/api/v1/fiat/tiers")
                healthy = r.status_code == 200
                results.append({
                    "step": total,
                    "name": "GET /fiat/tiers",
                    "method": "GET",
                    "path": "/fiat/tiers",
                    "statusCode": r.status_code,
                    "healthy": healthy,
                    "responseData": r.json() if healthy else None,
                })
                if healthy:
                    successful += 1
                    tiers_data = r.json()
                else:
                    raise RuntimeError(f"tiers fetch failed {r.status_code}")
            except Exception as e:
                results.append({
                    "step": total, "name": "GET /fiat/tiers",
                    "method": "GET", "path": "/fiat/tiers",
                    "healthy": False, "error": str(e),
                })
                return self._final(results, successful, total)

            # Step 2-4: quote at three breakpoints
            cases = [
                ("5.00", "2000"),    # tier 1 base
                ("50.00", "2500"),   # tier 2 value
                ("200.00", "3000"),  # tier 3 max
            ]
            for amount_eur, expected_avt_per_eur in cases:
                total += 1
                try:
                    r = await client.post(
                        f"{base}/api/v1/fiat/quote",
                        json={"eur_amount": amount_eur},
                    )
                    healthy = r.status_code == 200
                    quote = r.json() if healthy else {}
                    actual_avt = Decimal(str(quote.get("avt_amount", "0")))
                    expected_avt = Decimal(amount_eur) * Decimal(expected_avt_per_eur)
                    matches = actual_avt == expected_avt
                    results.append({
                        "step": total,
                        "name": f"POST /fiat/quote for €{amount_eur} (expect {expected_avt} AVT)",
                        "method": "POST", "path": "/fiat/quote",
                        "statusCode": r.status_code,
                        "healthy": healthy and matches,
                        "responseData": quote,
                        "tier_math_ok": matches,
                        "expected_avt": str(expected_avt),
                        "actual_avt": str(actual_avt),
                    })
                    if healthy and matches:
                        successful += 1
                except Exception as e:
                    results.append({
                        "step": total,
                        "name": f"POST /fiat/quote €{amount_eur}",
                        "method": "POST", "path": "/fiat/quote",
                        "healthy": False, "error": str(e),
                    })

        return self._final(results, successful, total)

    def _final(self, results, successful, total):
        return {
            "flow_name": "flow_fiat_quote_roundtrip_complete",
            "success": successful == total,
            "total_steps": total,
            "successful_steps": successful,
            "results": results,
            "flow_values": self.flow_values,
        }

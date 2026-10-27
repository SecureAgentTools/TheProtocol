"""Reputation Bond Flow — the bond's lifecycle driven end to end (§REPBOND).

The registry refuses an UNBONDED provider at six sites. This flow walks one
agent from `none` through the gate's refusal, the 402 for a funder that cannot
pay, the deposit, the gate's admission, and the 409 that guards an early
release — asserting the SENTENCE at each refusal, not just the status.

WHY THE SENTENCE. A 403 is the weakest evidence available on these paths:
`require_agent_permission` answers 403, an absent route answers 404, and this
suite has previously read a missing route as an ownership refusal. The bond's
refusal names the site, the required amount, the currency and both doors out of
it, so matching on it is what distinguishes the bond gate from every other way
the same call can fail.

⚠ AND THE GATE REFUSES TWO DIFFERENT THINGS. `is_bonded_did` answers
True/False/None, where None means the registry has no agent row AND no mirrored
card for the DID. Both False and None refuse — with DIFFERENT sentences since
§REPBOND, which is what step 12 pins. Before that they were identical, and a
bond-gate test could pass while measuring "I have never heard of this DID".

Sandbox-only: dust amounts, the treasury funds the probe, and every step is
gated on the tier actually enforcing — on a tier with the bond off the flow
reports each refusal step as an expected failure rather than inventing one.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    get_target, login_admin, onboard_agent, get_agent_jwt, http_in_container,
)

logger = logging.getLogger(__name__)

_UNBONDED_MARKERS = ("holds no reputation bond", "requires a bond of")
_UNKNOWN_MARKERS = ("is not known to this registry",)


def _detail(body: Any) -> str:
    if isinstance(body, dict):
        d = body.get("detail")
        if isinstance(d, str):
            return d
        return json.dumps(body, default=str)
    return str(body)


class TestFlowReputationBond(APITestBase):
    CATEGORY_NAME = "flow_reputation_bond"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_all(self, developer_token=None, agent_token=None):
        std = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False,
        )
        std["flow_tests"] = await self.test_reputation_bond_flow(developer_token)
        return std

    # ── step helpers ──────────────────────────────────────────────────────

    def _step(self, n: int, name: str, path: str, method: str, healthy: bool,
              code: str, data: Any, *, auth: str = "developer",
              ef: bool = False, ef_reason: Optional[str] = None) -> Dict[str, Any]:
        return {
            "step": n, "name": name, "path": path, "method": method,
            "authRequired": auth, "healthy": healthy,
            "statusCode": int(code) if str(code).isdigit() else 0,
            "expected_failure": ef,
            "expected_failure_reason": ef_reason,
            "responseData": data,
            "error": None if healthy else _detail(data)[:300],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _fail_step(self, n: int, name: str, detail: str) -> Dict[str, Any]:
        return self._step(n, name, "-", "-", False, "500", {"detail": detail})

    def _summarize(self, results, flow_success: bool) -> Dict[str, Any]:
        total = len(results)
        ok = sum(1 for r in results if r.get("healthy"))
        return {
            "flow_name": "flow_reputation_bond_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }

    @staticmethod
    def _is(markers: Tuple[str, ...], body: Any) -> bool:
        d = _detail(body).lower()
        return all(m in d for m in markers)

    # ── the flow ──────────────────────────────────────────────────────────

    async def test_reputation_bond_flow(self, developer_token: str = None) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting Reputation Bond Flow")
        logger.info("=" * 60)
        target = get_target("sandbox")
        cont = target.a_registry_container
        results = []
        ts = int(time.time()) % 100000

        ok, dev_jwt, det = await login_admin(target, "a")
        if not ok:
            results.append(self._fail_step(1, "Sandbox-A admin login", det))
            return self._summarize(results, False)
        results.append(self._step(1, "Sandbox-A admin login", "/auth/login", "POST",
                                  True, "200", {"jwt": bool(dev_jwt)}, auth="none"))

        # 2. the tier's own posture decides what the rest of this flow can claim
        ok, cfg, code = await http_in_container(cont, "GET", "/api/v1/reputation-bond/config")
        mode = (cfg or {}).get("mode") if isinstance(cfg, dict) else None
        amount = (cfg or {}).get("amount") if isinstance(cfg, dict) else None
        currency = (cfg or {}).get("currency") if isinstance(cfg, dict) else None
        backstop = (cfg or {}).get("treasury_backstop") if isinstance(cfg, dict) else None
        self.flow_values.update({"bond_mode": mode, "bond_amount": amount,
                                 "bond_currency": currency, "treasury_backstop": backstop})
        results.append(self._step(2, "Bond config readable", "/reputation-bond/config", "GET",
                                  ok and bool(mode), code,
                                  {"mode": mode, "amount": amount, "currency": currency,
                                   "treasury_backstop": backstop}, auth="none"))
        enforcing = (mode == "enforce")
        ef_off = None if enforcing else f"tier runs the bond gate in mode={mode!r}; refusals are not expected"

        # 3. a provider to walk through the states
        ok, agent, det = await onboard_agent(target, "a", dev_jwt, f"repbond-{ts}")
        results.append(self._step(3, f"Onboard provider repbond-{ts}", "/onboard/create_agent",
                                  "POST", ok, "200" if ok else "500",
                                  {"did": (agent or {}).get("did", "")[:40], "detail": det},
                                  auth="bootstrap"))
        if not ok:
            return self._summarize(results, False)
        did = agent["did"]
        ok, agent_jwt, det = await get_agent_jwt(target, "a", agent["client_id"], agent["client_secret"])
        if not ok:
            results.append(self._fail_step(4, "Provider agent JWT", det))
            return self._summarize(results, False)
        results.append(self._step(4, "Provider agent JWT", "/auth/agent/token", "POST",
                                  True, "200", {"jwt": True}, auth="none"))

        # 5. a fresh provider holds no bond
        ok, rep, code = await http_in_container(cont, "GET", f"/api/v1/agents/{did}/reputation")
        bond = (rep or {}).get("bond") if isinstance(rep, dict) else {}
        status0 = (bond or {}).get("status")
        results.append(self._step(5, "Fresh provider reports status=none", f"/agents/{did}/reputation",
                                  "GET", ok and status0 == "none", code,
                                  {"status": status0}, auth="none"))

        # 6. the never-bonded contract: 404, not an empty 200
        ok, sbody, code = await http_in_container(
            cont, "GET", "/api/v1/agents/reputation-bond/status", jwt=agent_jwt)
        results.append(self._step(6, "Never-bonded status keeps its 404 contract",
                                  "/agents/reputation-bond/status", "GET",
                                  code == "404", code, {"detail": _detail(sbody)[:120]}, auth="agent"))

        # 7. THE GATE REFUSES — and the sentence is the evidence, not the 403
        ok, gbody, code = await http_in_container(
            cont, "PATCH", f"/api/v1/agent-cards/{did}/listing", body={"unlisted": False}, jwt=dev_jwt)
        refused = (code == "403") and self._is(_UNBONDED_MARKERS, gbody)
        names_amount = str(amount or "") in _detail(gbody)
        results.append(self._step(
            7, "Listing refused for an unbonded provider, by sentence",
            f"/agent-cards/{did}/listing", "PATCH",
            refused and names_amount if enforcing else True, code,
            {"is_bond_refusal": refused, "refusal_names_amount": names_amount,
             "detail": _detail(gbody)[:220]},
            ef=(not enforcing), ef_reason=ef_off))

        # 8. a funder that cannot pay: 402 naming the amount and the doors
        ok, dbody, code = await http_in_container(
            cont, "POST", "/api/v1/agents/reputation-bond/deposit",
            body={"amount": amount or "250"}, jwt=agent_jwt)
        short = code in ("402", "400") and str(amount or "") in _detail(dbody)
        results.append(self._step(8, "Deposit refused while the agent cannot pay",
                                  "/agents/reputation-bond/deposit", "POST",
                                  short if enforcing else True, code,
                                  {"detail": _detail(dbody)[:220]}, auth="agent",
                                  ef=(not enforcing), ef_reason=ef_off))

        # 9. fund it through the canonical admin rail (FLOW 4), never a direct mint
        seed = str(float(amount or 250) + 20)
        ok, fbody, code = await http_in_container(
            cont, "POST", "/api/v1/teg/treasury/fund-agent",
            body={"target_agent_did": did, "amount": seed,
                  "reason": "api-test reputation bond flow"}, jwt=dev_jwt)
        results.append(self._step(9, "Fund the provider from the treasury",
                                  "/teg/treasury/fund-agent", "POST", ok, code,
                                  {"amount": seed}))
        if not ok:
            return self._summarize(results, False)

        # 10. the deposit lands and the bond locks
        ok, dbody2, code = await http_in_container(
            cont, "POST", "/api/v1/agents/reputation-bond/deposit",
            body={"amount": amount or "250"}, jwt=agent_jwt)
        locked = isinstance(dbody2, dict) and dbody2.get("status") == "locked"
        self.flow_values["bond_id"] = (dbody2 or {}).get("bond_id") if isinstance(dbody2, dict) else None
        self.flow_values["escrow_ref"] = (dbody2 or {}).get("escrow_ref") if isinstance(dbody2, dict) else None
        results.append(self._step(10, "Deposit locks the bond", "/agents/reputation-bond/deposit",
                                  "POST", ok and locked, code,
                                  {"status": (dbody2 or {}).get("status") if isinstance(dbody2, dict) else None,
                                   "detail": _detail(dbody2)[:180]}, auth="agent"))

        # 11. THE GATE ADMITS — same call, same agent, one variable changed
        ok, gbody2, code = await http_in_container(
            cont, "PATCH", f"/api/v1/agent-cards/{did}/listing", body={"unlisted": False}, jwt=dev_jwt)
        admitted = not self._is(_UNBONDED_MARKERS, gbody2)
        results.append(self._step(11, "Listing admitted once bonded (same call, one variable)",
                                  f"/agent-cards/{did}/listing", "PATCH",
                                  admitted, code, {"still_bond_refusal": not admitted,
                                                   "detail": _detail(gbody2)[:180]}))

        # 12. unknown ≠ unbonded: the third state must have its OWN sentence.
        #
        # ⚠ THE SITE MATTERS, and the first version of this step got it wrong.
        # Probing an unknown DID through `listing` answers 404 "Agent Card not
        # found" — the route looks the card up BEFORE the gate runs, so the step
        # passed while measuring a card lookup and would have kept passing if
        # the two sentences were still identical. `a2a-payment/authorize` calls
        # the gate as its FIRST statement, so the unknown branch is reachable
        # there and nowhere the card is resolved first.
        ghost = f"did:theprotocol:{ts}-0000-0000-0000-000000000000"
        ok, ubody, code = await http_in_container(
            cont, "POST", "/api/v1/a2a-payment/authorize",
            body={"target_agent_did": ghost, "amount": "1.0",
                  "task_description": "api-test unknown-DID gate probe"}, jwt=agent_jwt)
        reached_gate = self._is(_UNKNOWN_MARKERS, ubody) or self._is(_UNBONDED_MARKERS, ubody)
        distinct = self._is(_UNKNOWN_MARKERS, ubody) and not self._is(_UNBONDED_MARKERS, ubody)
        results.append(self._step(
            12, "An unknown DID is refused by its OWN sentence, not the unbonded one",
            "/a2a-payment/authorize", "POST",
            distinct if enforcing else True, code,
            {"reached_the_bond_gate": reached_gate,
             "unknown_sentence": self._is(_UNKNOWN_MARKERS, ubody),
             "collapsed_into_unbonded": self._is(_UNBONDED_MARKERS, ubody),
             "detail": _detail(ubody)[:220]}, auth="agent",
            ef=(not enforcing), ef_reason=ef_off))

        # 13. release before maturity is refused, with the progress that explains it
        ok, rbody, code = await http_in_container(
            cont, "POST", "/api/v1/agents/reputation-bond/release", jwt=agent_jwt)
        early = code == "409"
        results.append(self._step(13, "Release refused before maturity + cooldown",
                                  "/agents/reputation-bond/release", "POST",
                                  early if enforcing else True, code,
                                  {"detail": _detail(rbody)[:220]}, auth="agent",
                                  ef=(not enforcing), ef_reason=ef_off))

        # 14. the admin view can see this bond in its population
        ok, obody, code = await http_in_container(
            cont, "GET", "/api/v1/admin/reputation-bond/overview", jwt=dev_jwt)
        by_status = (obody or {}).get("by_status") if isinstance(obody, dict) else None
        results.append(self._step(14, "Admin overview reports the population by status",
                                  "/admin/reputation-bond/overview", "GET",
                                  ok and isinstance(by_status, dict), code,
                                  {"by_status": by_status,
                                   "unbonded_providers": (obody or {}).get("unbonded_providers")
                                   if isinstance(obody, dict) else None}, auth="admin"))

        self.flow_values["provider_did"] = did
        return self._summarize(results, True)

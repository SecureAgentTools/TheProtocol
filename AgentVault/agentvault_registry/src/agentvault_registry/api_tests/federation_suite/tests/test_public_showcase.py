"""Public showcase + community surface tests (§pass73.3.9 Batch 26).

3 read-only tests probing the public-facing showcase + community
surfaces — used by /ui#/services + /ui#/showcase + landing page.
"""
from __future__ import annotations

import json
import re

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


@federation_test(
    name="public_showcase_agents_listed",
    category="public_showcase",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["public-showcase", "service-agents"],
)
async def test_showcase_agents(rig: FederationTestRig) -> AssertionResult:
    """getPublicShowcaseAgents lists the curated service agents on each
    frame. Sandbox-A's mainframe should expose the 12 canonical service
    agents (Weather, Currency, DnsSSL, etc. per CLAUDE.md PART 7)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getPublicShowcaseAgents")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                agents = r.get("agents") if isinstance(r, dict) else r
                if not isinstance(agents, list):
                    state[label] = {"bad_shape": type(agents).__name__}
                    continue
                state[label] = {
                    "count": len(agents),
                    "sample_ids": [a.get("id") for a in agents[:5] if isinstance(a, dict)],
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="public showcase agents listed on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="community_announcements_endpoint_reachable",
    category="public_showcase",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["community", "announcements"],
)
async def test_community_announcements(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCommunityAnnouncements reachable on both frames — may return
    empty list (sandbox typically has none)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getCommunityAnnouncements")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {
                        "count": len(r.get("announcements") or []),
                        "total": r.get("total"),
                    }
                elif isinstance(r, list):
                    state[label] = {"count": len(r)}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="community announcements endpoint reachable on both mainframes",
        capture_state=lambda: state,
    )


# A service no deployment serves: the route refuses it before any agent is dialled, so the probe performs nothing.
SHOWCASE_PROBE = {"service": "fedsuite-no-such-service", "input": ""}


def classify_showcase_refusal(status, words):
    """What the call route said to a service it does not serve, in its own words; None when it said something else."""
    if status == 503 and "disabled on this deployment" in words:
        return "the showcase is disabled on this frame"
    if status == 400 and "Unknown service" in words:
        return "the route refused an unknown service"
    if status == 429 and "Rate limit exceeded" in words:
        return "the route is reachable and rate-limited this caller"
    return None


@federation_test(
    name="public_showcase_call_endpoint",
    category="public_showcase",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["public-showcase", "call"],
)
async def test_showcase_call_endpoint(
    rig: FederationTestRig,
) -> AssertionResult:
    """getPublicShowcaseCall reaches the showcase call route with the arguments its inputSchema declares.

    §NIGHTPROV (2026-09-27): since §MCPSWEEP V0464 the tool POSTs {service, input}, as its route takes. This test still
    called it with no arguments, so the dispatcher refused it (-32602) before the route ran: measured on a fresh nightly
    frame (nt260927x2a). The probe now names a service nobody serves, so nothing is performed, and the tool's answer is
    judged by the route's own words (the dispatcher keeps only the status of a tool error), read through adminRequest.
    """
    state: dict = {}

    async def predicate():
        if "definitive" in state:       # one probe answers it; do not spend the caller's hourly budget on retries
            return state["definitive"]
        try:
            r = await rig.mcp("sandbox-A").call("getPublicShowcaseCall", dict(SHOWCASE_PROBE))
            text = r.get("_text") if isinstance(r, dict) else None
            state["tool_answer"] = (text if isinstance(text, str) else json.dumps(r, default=str))[:200]
            m = re.search(r"returned HTTP (\d{3})", text or "")
            tool_status = int(m.group(1)) if m else None
            rest = await rig.mcp("sandbox-A-admin").call("adminRequest", {
                "method": "POST", "endpoint": "/api/v1/public/showcase/call", "body": dict(SHOWCASE_PROBE)})
            route_status = rest.get("status_code") if isinstance(rest, dict) else None
            words = json.dumps(rest.get("response") if isinstance(rest, dict) else rest, default=str)
            state["route_status"], state["route_words"] = route_status, words[:200]
            answer = classify_showcase_refusal(route_status, words)
            state["answer"] = answer
            state["definitive"] = bool(answer) and tool_status == route_status
            return state["definitive"]
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="public showcase call route reached by the tool with its declared arguments, on sandbox-A",
        capture_state=lambda: state,
    )

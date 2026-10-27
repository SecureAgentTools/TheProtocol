"""§MCPSWEEP 2026-09-27 — an MCP tool whose request its own route always refuses can never succeed.

Measured live on sbx-alpha (V0462) through the admin bridge, then offline over both surfaces: 22 admin and 30 public
tools sent a request their route refused with 422 before any handler ran (a missing body field, a field under another
name, a query parameter sent in the body, a DELETE with no body), 5 + 2 more whenever a caller followed the schema's
required list, 2 called a path no route serves and 2 used a method their path does not take. The sweep read most of
them green: a refusal is a refusal. This gate calls every admin and public tool offline (tests/mcp_request_survey.py,
in a fresh process: nothing leaves it), captures the request each one makes and runs FastAPI's own path, query and
body validation of the route it reaches.

Gated: NO_ROUTE, METHOD, MISSING_ALWAYS, MISSING_OPTIONAL and (since V0466) BOUND, a page size the schema allows and
the route refuses (25 tools clamped to 500 or 200 against routes serving 200, 100 or 50), and (since V0511) UNDECLARED: a
query parameter the route does not declare, which FastAPI drops without a word while the request answers 200 (15 tools,
2026-10-01: an `offset` sent to routes paged by `skip`, `cursor` or `since`; `lines`/`limit` to routes reading `tail`;
filters the route never read; found by the pagination partition probe on listAgentCards, whose page 2 was page 1).
UNDECLARED_RAW (the handler takes the raw Request and may read it itself) is reported, not gated. And (since V0512)
BODY_UNDECLARED, the same class in a JSON body: a field the route's model does not declare, dropped by pydantic while the
request answers 200 (13 tools on 2026-10-01 beyond the pass-through dummy: 11 fixed in V0512, the bridge pair
named below; among them lockUnits' idempotency key in the body, runDiagnosticsSubset's
`checks` for `check_ids` (it ran every check), forkBundle's `new_name`, authSetNewPassword's token for a bearer). And
(since V0538) TIER, a credential the route can never accept: the survey gives each tool its tier's credential, and the
route's dependency tree names whom it authenticates. 2026-10-01: claimTegPayouts, getRelayStatus and relayAction sent an
agent's token to routes that authenticate the agent's developer, resolveTegDispute a developer's to a route that
authenticates an agent, getCommunityAnnouncements none to a developer route (it turned the 401 into an empty feed);
round 10 read three of them as passes because their contracts pinned the refusal. The exceptions below are named
with their reason and may
only shrink. TYPE, PASSTHROUGH, RAISED and NO_REQUEST are reported by the survey, not gated: a dummy value can cause
them, and a pass-through tool's body is the caller's to shape.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
# BODY_UNREAD (V0550): a key sent in an untyped dict body that the handler never reads (generateTutorialProof sent
# tutorial_id to a handler reading circuit_id, testApiEndpoint endpoint_path to one reading path)
GATED = ("NO_ROUTE", "METHOD", "MISSING_ALWAYS", "MISSING_OPTIONAL", "BOUND", "UNDECLARED", "BODY_UNDECLARED", "BODY_UNREAD",
         "TIER")

# FIX ONE, REMOVE IT HERE. Never add a tool to this list to make the gate pass.
KNOWN = {
    "theprotocol_adminRequest": "a generic proxy: the survey's dummy endpoint is not a route, a caller's is",
    "theprotocol_bridgeIssueWrapped": "the Token Bridge is on the D8 RETIRE? list, his decision; its minting wrapper "
                                     "is left as it is until then",
    "theprotocol_bridgeRedeem": "the Token Bridge is on the D8 RETIRE? list, his decision; its wrapper is left as "
                                "it is until then (since V0538 also TIER: an admin tool at an agent route)",
}


@pytest.fixture(scope="module")
def survey():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "survey.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(HERE.parent / "src") + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run([sys.executable, str(HERE / "mcp_request_survey.py"), "all", "--json", str(out)],
                           env=env, cwd=str(HERE.parent), capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, f"the survey did not run:\n{r.stderr[-3000:]}"
        return json.loads(out.read_text())


def _failing(survey) -> dict:
    out: dict = {}
    for surface in ("admin", "public"):
        for cls in GATED:
            for tool, details in survey["surfaces"][surface]["classes"][cls].items():
                out.setdefault(tool, []).extend(f"{cls}: {d}" for d in details)
    return out


def test_the_instrument_finds_what_its_controls_carry(survey):
    c = survey["controls"]
    assert any(k == "MISSING" and "query -> ruling" in d for k, d in c["missing_query"]), c["missing_query"]
    assert any(k == "NO_ROUTE" for k, _ in c["no_route"]), c["no_route"]
    assert any(k == "MISSING" and "body -> tier" in d for k, d in c["missing_body_field"]), c["missing_body_field"]
    assert any(k == "TYPE" and "query -> limit" in d and "less than or equal to" in d for k, d in c["page_too_large"]), \
        c["page_too_large"]
    assert any(k == "UNDECLARED" and "?phase6_no_such" in d for k, d in c["undeclared_query"]), c["undeclared_query"]
    assert [k for k, d in c["undeclared_body"] if "body.phase6_no_such" in d] == ["BODY_UNDECLARED"], c["undeclared_body"]
    # (the good request is an admin's at an admin route: ADMIN_ROUTE, which is reported and never gated, is all it carries)
    assert [x for x in c["good"] if x[0] != "ADMIN_ROUTE"] == [], f"a well-formed request was refused by the instrument: {c['good']}"
    # (both tier controls ask the TEG's reward claim, which STAKING_REWARDS_ENABLED switches: SWITCHED, never gated)
    assert [k for k, _ in c["tier_agent_at_developer_route"]] == ["SWITCHED", "TIER"], c["tier_agent_at_developer_route"]
    assert [k for k, _ in c["tier_good"]] == ["SWITCHED"], \
        f"a developer's token at a developer route read as TIER or admin-only: {c['tier_good']}"
    assert [k for k, _ in c["admin_route"]] == ["ADMIN_ROUTE"], c["admin_route"]
    # §MCPTEST30 (V0547): the peers' feed carries PEER_ROUTE, and no other control does
    assert [k for k, _ in c["peer_route"]] == ["PEER_ROUTE"], c["peer_route"]
    # §MCPTEST30 (V0549): so does a route whose handler checks a federation licence header itself, and the same request
    # WITH the header carries nothing: the header is all that separates the two
    assert [k for k, _ in c["licence_header"]] == ["PEER_ROUTE"], c["licence_header"]
    assert "X-Federation-License" in c["licence_header"][0][1], c["licence_header"]
    assert c["licence_header_sent"] == [], c["licence_header_sent"]
    # §MCPTEST30 (V0550): an untyped dict body: the key the handler never reads, and the one it reads
    assert [k for k, d in c["unread_body"] if "body.endpoint_path" in d] == ["BODY_UNREAD"], c["unread_body"]
    assert [x for x in c["read_body"] if x[0] != "ADMIN_ROUTE"] == [], c["read_body"]
    assert not [n for n, found in c.items() if n not in ("peer_route", "licence_header")
                and any(k == "PEER_ROUTE" for k, _ in found)], c
    # §MCPTEST30 (V0550): the stake carries its switch and nothing else; no control but the stake and the reward claim does
    assert [k for k, _ in c["switched"]] == ["SWITCHED"], c["switched"]
    assert c["switched"][0][1].startswith("require_staking_enabled at "), c["switched"]
    assert not [n for n, found in c.items() if n not in ("switched", "tier_good", "tier_agent_at_developer_route")
                and any(k == "SWITCHED" for k, _ in found)], c


def test_the_switch_map_is_the_routes_switches(survey):
    """§MCPTEST30 (V0550): the tester holds a tool its target switched off to its switch's refusal
    (api_tests/contracts/mcp_switches.py). Its map must be the code's: every tool whose route carries a §BAFIN switch
    dependency is in it with that dependency, and every dependency it names is one the survey found on the tool's route.
    A new switched route, or a tool moved to one, fails here until the map says so (the inline switches, which no
    dependency carries, are held to their handlers by tests/test_mcp_switches.py; the unmounted ones, a router create_app
    leaves out, by tests/test_mcp_bridge_switch.py)."""
    from agentvault_registry.api_tests.contracts import mcp_switches as M
    found: dict = {}
    for surface in ("admin", "public"):
        for tool, details in survey["surfaces"][surface]["classes"]["SWITCHED"].items():
            found.setdefault(tool, set()).update(d.split(" at ", 1)[0] for d in details)
    mapped = {t: {sw.where} for t, sw in M.SWITCHED_TOOLS.items() if not sw.where.startswith(("inline:", "unmounted:"))}
    assert found == mapped, (f"in the survey, not the map: {sorted(set(found) - set(mapped))}; in the map, not the "
                             f"survey: {sorted(set(mapped) - set(found))}; different: "
                             f"{sorted(t for t in set(found) & set(mapped) if found[t] != mapped[t])}")
    for t, sw in M.SWITCHED_TOOLS.items():
        if not sw.where.startswith(("inline:", "unmounted:")):
            assert M.DEPENDENCY_KEYS[sw.where] == sw.key, (t, sw)


def test_the_survey_reached_both_surfaces(survey):
    for surface, floor in (("admin", 300), ("public", 400)):
        s = survey["surfaces"][surface]
        assert s["tools"] >= floor, f"{surface}: only {s['tools']} tools surveyed"
        assert s["requests"] >= 250, f"{surface}: only {s['requests']} requests captured: the recorder is not seeing them"


def test_no_tool_sends_a_request_its_route_always_refuses(survey):
    failing = _failing(survey)
    new = {t: d for t, d in failing.items() if t not in KNOWN}
    assert not new, "tools whose route refuses the request they make (fix the tool, never list it):\n" + "\n".join(
        f"  {t}:\n    " + "\n    ".join(d) for t, d in sorted(new.items()))
    fixed = sorted(set(KNOWN) - set(failing))
    assert not fixed, f"these pass now: remove them from KNOWN: {fixed}"


# §MCPTEST30 (V0547): MCP tools whose route authenticates only a federation PEER (mTLS, the internal secret or a
# federation licence), measured 2026-10-02 on V0545: no MCP caller holds such an identity, so none of these can ever
# succeed. Three turned the 401 into an empty list and read as passes (V0547 makes them say the refusal). Whether each
# leaves the MCP surface or gains a route its caller may call is his decision. THIS LIST MAY ONLY SHRINK: a new tool at
# a peer route fails here, and a tool that leaves the class must leave the list.
PEER_ROUTE_BASELINE = {
    "theprotocol_blockFederationAgent", "theprotocol_unblockFederationAgent",          # admin: the peer blocklist entry
    "theprotocol_ironhandRegisterAgentProxy", "theprotocol_ironhandDeleteAgentProxy",  # admin: the operators' SPIRE proxy
    "theprotocol_bridgeIssueWrapped", "theprotocol_bridgeUnlock",                       # admin: the bridge (D8, his)
    "theprotocol_crossTegBalanceSync", "theprotocol_federationSyncRequest",            # public: peer protocol calls
    "theprotocol_federationSlashRequest", "theprotocol_federationSlashConfirmation",
    "theprotocol_getFederationSyncStatusDev", "theprotocol_getFederationPolicyCompliance",
    "theprotocol_listFederationAgentCards", "theprotocol_listFederationRegistryCards",  # public: the peers' feeds
    # V0549: the survey reads a header a handler checks itself (tests/mcp_handler_headers.py). These three were in the
    # class all along and could not be seen: their routes take a federation licence (X-Federation-License) the tool
    # never sends, so each answers 401 or 400 to every MCP caller. The first two are a cloud operator's own-licence
    # routes (a frame admin has getCloudOperatorLogs / restartCloudOperatorService, an operator's admin
    # operatorPortalSelfLogs / operatorPortalSelfRestart); the third is the operator CLI's audit entry.
    "theprotocol_getCloudOperatorSelfLogs", "theprotocol_cloudOperatorSelfRestart",    # admin: own-licence routes
    "theprotocol_federationCliAudit",                                                   # admin: the CLI's audit entry
}


def test_tools_at_peer_routes_only_shrink(survey):
    found = {t for surface in ("admin", "public") for t in survey["surfaces"][surface]["classes"]["PEER_ROUTE"]}
    new = sorted(found - PEER_ROUTE_BASELINE)
    assert not new, f"MCP tools at a route only a federation peer can call (no MCP caller can succeed): {new}"
    gone = sorted(PEER_ROUTE_BASELINE - found)
    assert not gone, f"these no longer reach a peer-only route: remove them from PEER_ROUTE_BASELINE: {gone}"

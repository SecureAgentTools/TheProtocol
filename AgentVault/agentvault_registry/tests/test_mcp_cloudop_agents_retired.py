"""§MCPTEST30 (V0528, 2026-10-01) — the MCP tester's operator phase retires the agents it makes.

Measured on the sandbox operators: every run of the phase created `cloudop-sentinel-<epoch>-<hex>` and
`cloudop-second-<epoch>-<hex>`, funded each 5000 from the operator's treasury, staked 100 and bonded 250 from the
sentinel, and removed neither. By 2026-10-01: 97 active on sbxbetaop and 213 on sbxalphaop, 509,142 units liquid.
One of them became the receiver of agentvault2-21's Forex lifecycle and its FX quote answered 503.

The phase now returns what each of its agents holds to the operator's treasury and revokes it: this run's two at the
end, and a few of the earlier runs' leftovers at the start (oldest first, only past the sweep age, so a concurrent
run's agents are never touched). An agent whose balance could not be read is left alone.
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

NOW = 1_790_900_000.0
OLD = int(NOW) - 4 * 3600     # past the sweep age
FRESH = int(NOW) - 600        # a live run's


def _agent(name, did, status="active"):
    return {"name": name, "did": did, "status": status}


def test_only_old_active_phase_agents_are_picked_oldest_first():
    listing = [
        _agent(f"cloudop-sentinel-{OLD}-abc123", "did:a"),
        _agent(f"cloudop-second-{OLD - 50}-def456", "did:b"),
        _agent(f"cloudop-sentinel-{FRESH}-aaaaaa", "did:fresh"),               # a live run's: kept
        _agent(f"cloudop-sentinel-{OLD}-bbbbbb", "did:revoked", "revoked"),    # already gone
        _agent(f"cloudop-fixture-{OLD} Treasury ($CO39DD)", "did:org-treasury"),  # its organization's, not the phase's
        _agent(f"cloudop-sentinel-{OLD - 90}", "did:pre-suffix"),             # the name before the hex suffix existed
        _agent("canary/sbxbetaop-sender", "did:canary"),
        _agent(f"cloudop-sentinel-{OLD}-cccccc", "did:kept"),
    ]
    assert F.old_cloudop_fixtures(listing, NOW, keep={"did:kept"}) == ["did:pre-suffix", "did:b", "did:a"]
    assert F.old_cloudop_fixtures({"detail": "refused"}, NOW) == [], "an error body picks nothing"


def test_the_cap_bounds_one_run():
    listing = [_agent(f"cloudop-second-{OLD - i}-{i:06x}", f"did:{i}") for i in range(100)]
    picked = F.old_cloudop_fixtures(listing, NOW)
    assert len(picked) == F._CLOUDOP_FIXTURE_CAP and picked[0] == "did:99", "the oldest go first"


def _envelope(inner):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(inner)}]}}


def _drive(balances, refuse_return=()):
    log = []

    async def call(tool, args):
        log.append((tool, args.get("agent_did") or tuple(args.get("agent_dids") or ())))
        if tool == "theprotocol_getBatchAgentBalances":
            return True, _envelope({"balances": balances}), "200"
        return True, _envelope({}), "204"

    async def call_admin(tool, args):
        log.append((tool, args["source_agent_did"], args["amount"]))
        if args["source_agent_did"] in refuse_return:
            return False, _envelope({"error": "refused"}), "409"
        return True, _envelope({"ok": True}), "200"

    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(F._retire_cloudop_agents(call, call_admin, list(balances) + ["did:missing"]))
    finally:
        loop.close()
    return out, log


def test_holdings_go_back_then_the_agent_is_revoked():
    out, log = _drive({
        "did:funded": {"balance": "5000", "currency": "SBXB"},
        "did:sci": {"balance": "1E+3", "currency": "SBXB"},
        "did:empty": {"balance": "0", "currency": "SBXB"},
        "did:unread": {"balance": "0", "currency": "SBXB", "error": "Request timeout"},
        "did:stuck": {"balance": "7", "currency": "SBXB"},
    }, refuse_return={"did:stuck"})
    returns = [e for e in log if e[0] == "theprotocol_tegTreasuryReceive"]
    revokes = [e[1] for e in log if e[0] == "theprotocol_deleteMyAgentByDev"]
    assert ("theprotocol_tegTreasuryReceive", "did:funded", "5000") in returns
    assert ("theprotocol_tegTreasuryReceive", "did:sci", "1000") in returns, "a scientific balance goes back in plain digits"
    assert not any(e[1] == "did:empty" for e in returns), "nothing to return from an empty agent"
    assert revokes == ["did:funded", "did:sci", "did:empty"], (
        "revoked only after its holdings went back; never an unread balance, a refused return, or a DID with no row")
    assert log.index(("theprotocol_tegTreasuryReceive", "did:funded", "5000")) < log.index(
        ("theprotocol_deleteMyAgentByDev", "did:funded")), "the return comes first"
    assert out["returned"] == "6000" and out["returned_from"] == 2 and out["revoked"] == 3
    assert out["left_unread"] == 2 and out["refused"] == ["return HTTP 409"]


def test_the_phase_retires_earlier_agents_first_and_its_own_after_the_agora_fixture():
    tree = ast.parse(pathlib.Path(F.__file__).with_suffix(".py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_cloudop_mcp_sweep")

    def lines(callee):
        return sorted(c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                      and getattr(c.func, "id", getattr(c.func, "attr", "")) == callee)
    retire = lines("_retire_cloudop_agents")
    boot = lines("_bootstrap_cloudop_agent")
    agora = lines("_retire_scratch_org")
    assert len(retire) == 2 and boot and agora
    assert retire[0] < boot[0], "earlier runs' agents are retired before this run makes its own"
    assert retire[1] > agora[-1], "this run's agents are retired after the AGORA fixture's sweep pays the sentinel"

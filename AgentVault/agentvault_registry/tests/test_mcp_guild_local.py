"""§MCPTEST30 (V0644, agentvault2-66 on agentvault2-aa's conditions, 2026-10-26): the local Guild on an operator's run.

On V0641's read of both sandbox operators the guild family was NOT MEASURED (guildPostOrder, guildGetOrder, guildBid,
guildAward, guildSubmitWork, guildVerify, guildCancelOrder): an operator's own order table is empty and the operator sweep
runs no phase 3. earned_agent_public.lifecycle_earned_guild_local stages the orders itself, under four conditions:
  (a) only where the target ITSELF states "sandbox" (registry-config's `environment`; exactly that string), the treasury
      funds the poster and the poster then holds every bounty; otherwise every guild row is NOT MEASURED with what was read;
  (b) five dust orders, each closed in the same run (cancelled, or carried through award, submit and verify to
      settlement) and read back: nothing is left awarded or submitted (phase 3 leaves three per run on a frame);
  (c) the closing pass is pinned here, with a control where one order left open fails the run's own row;
  (d) every leg through the guild's own routes; a frame (phase 3's orders in the bag) is left to phase 3.
A fake guild keeps the routes' state machine (routers/guild.py): open, awarded, submitted, settled, cancelled.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_agent_public as E
from agentvault_registry.api_tests.contracts import earned_fixtures as ef

AGENTS = {"poster": {"did": "did:theprotocol:poster", "agent_jwt": "jwt-poster"},
          "worker": {"did": "did:theprotocol:worker", "agent_jwt": "jwt-worker"}}
WHO = {a["agent_jwt"]: a["did"] for a in AGENTS.values()}


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


# ── (a) the marker: only the target's own exact "sandbox" ───────────────────────────────────────────────────────────

def test_the_exact_word_sandbox_stages():
    assert E.sandbox_stated(True, "200", {"environment": "sandbox"}) == (True, "")


@pytest.mark.parametrize("read,code,cfg,names", [
    (True, "200", {"environment": "production"}, "'production'"),
    (True, "200", {"registry_name": "sbxalphaop"}, "states no environment"),
    (True, "200", {"environment": "staging"}, "'staging'"),
    (True, "200", {"environment": "Sandbox"}, "'Sandbox'"),
    (False, "503", None, "could not be read (HTTP 503)"),
])
def test_anything_else_is_no_sandbox_and_names_what_was_read(read, code, cfg, names):
    staged, why = E.sandbox_stated(read, code, cfg)
    assert staged is False and names in why


# ── the fake guild ──────────────────────────────────────────────────────────────────────────────────────────────────

class _Guild:
    """routers/guild.py's state machine for the tools the lifecycle calls, and the reads around them. `refuse` names
    (tool, order role) pairs the fake answers 409 for: an order that cannot be moved."""

    def __init__(self, env="sandbox", refuse=(), list_ok=True, balance="0.10"):
        self.env, self.refuse, self.list_ok, self.balance = env, set(refuse), list_ok, balance
        self.orders, self.calls, self.n = {}, [], 0

    def _role(self, oid):
        return self.orders.get(oid, {}).get("title", "").split()[3:4][0] if oid in self.orders else ""

    async def rpc(self, tool, args, jwt="", timeout=20):
        self.calls.append((tool, dict(args)))
        oid = str(args.get("order_id") or "")
        o = self.orders.get(oid)
        if (tool, self._role(oid)) in self.refuse:
            return False, _answer({"detail": f"refused by the test ({tool})"}), "409"
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _answer({} if self.env is None else {"environment": self.env}), "200"
        if tool == "theprotocol_guildListOrders":
            if not self.list_ok:
                return False, _answer({"detail": "The Guild is disabled on this registry"}), "503"
            return True, _answer({"orders": []}), "200"
        if tool == "theprotocol_getBatchAgentBalances":
            return True, _answer({"balances": {d: {"balance": self.balance} for d in args["agent_dids"]}}), "200"
        if tool == "theprotocol_guildPostOrder":
            self.n += 1
            new = f"gwo_{self.n}"
            self.orders[new] = {"id": new, "title": args["title"], "status": "open", "poster": WHO[args["agent_jwt"]],
                                "bids": []}
            return True, _answer({"order_id": new, "status": "open", "bounty": float(args["bounty"])}), "200"
        if tool == "theprotocol_guildGetOrder":
            if not o:
                return False, _answer({"detail": "Order not found"}), "404"
            return True, _answer({"order": {"id": oid, "status": o["status"]}, "bids": list(o["bids"]),
                                  "events": []}), "200"
        if not o:
            return False, _answer({"detail": "Order not found"}), "404"
        if tool == "theprotocol_guildBid" and o["status"] == "open":
            self.n += 1
            o["bids"].append({"id": self.n, "bidder_did": WHO[args["agent_jwt"]]})
            return True, _answer({"ok": True, "order_id": oid, "bidder": WHO[args["agent_jwt"]], "bid_id": self.n}), "200"
        if tool == "theprotocol_guildAward" and o["status"] == "open":
            o["status"] = "awarded"
            return True, _answer({"ok": True, "order_id": oid, "status": "awarded"}), "200"
        if tool == "theprotocol_guildSubmitWork" and o["status"] == "awarded":
            o["status"] = "submitted"
            return True, _answer({"ok": True, "order_id": oid, "status": "submitted"}), "200"
        if tool == "theprotocol_guildVerify" and o["status"] == "submitted":
            o["status"] = "settled"
            return True, _answer({"ok": True, "order_id": oid, "status": "settled", "payout": 0.00995}), "200"
        if tool == "theprotocol_guildCancelOrder" and o["status"] == "open" and WHO[args["agent_jwt"]] == o["poster"]:
            o["status"] = "cancelled"
            return True, _answer({"ok": True, "order_id": oid, "status": "cancelled", "refund": 0.01}), "200"
        return False, _answer({"detail": f"Order is {o['status']}"}), "409"


def _run(monkeypatch, guild, flow_values=None):
    rest = []

    async def fake_rest(bag, parse, method, endpoint, body=None, **kw):
        rest.append((method, endpoint, dict(body or {})))
        if endpoint.endswith("/fund-agent"):
            return 200, {"ok": True}
        if endpoint.endswith("/reputation-bond/backstop"):
            return 200, {"status": "locked"}
        return 404, {"detail": "not in this test"}

    closed = []

    class _Throwaways:
        def __init__(self, *a, **k):
            pass

        async def agent(self, dev, label=""):
            return dict(AGENTS[label])

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(E, "_rest", fake_rest)
    monkeypatch.setattr(ef, "Throwaways", _Throwaways)
    bag = SimpleNamespace(developer_jwt="d", developer_id="1", rpc_admin=None, flow_values=dict(flow_values or {}))
    outcomes = {}
    asyncio.run(E.lifecycle_earned_guild_local(guild.rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes, rest, closed


# ── (b) and (c): five orders, each tool measured, every order closed and read back ──────────────────────────────────

def test_on_a_sandbox_every_tool_is_measured_and_every_order_ends_terminal(monkeypatch):
    g = _Guild()
    outcomes, rest, closed = _run(monkeypatch, g)
    for tool, _tier in E.GUILD_LOCAL_TOOLS:
        assert outcomes[tool].get("healthy") is True, (tool, outcomes[tool])
    assert len(g.orders) == 5 and {o["status"] for o in g.orders.values()} <= set(E.GUILD_TERMINAL)
    row = outcomes[E.GUILD_CLOSED_ROW]
    assert row.get("healthy") is True and len(row["result_excerpt"]["orders"]) == 5
    assert E.GUILD_CLOSED_ROW.startswith(F._SYNTHETIC_ROW_PREFIXES), "a row named for no tool is kept under its prefix"
    assert [m for m, e, _b in rest if e.endswith("/fund-agent")] == ["POST"] and closed == [True]
    posts = [a for t, a in g.calls if t == "theprotocol_guildPostOrder"]
    assert len(posts) == 5 and {a["agent_jwt"] for a in posts} == {"jwt-poster"} and {a["bounty"] for a in posts} == {E.DUST}


def test_an_order_left_open_fails_the_runs_own_row(monkeypatch):
    # control: the poster cannot cancel the read order (the fake refuses), so it stays open; the closing row fails and
    # names it, while the five tools' own rows stand
    g = _Guild(refuse={("theprotocol_guildCancelOrder", "read")})
    outcomes, _rest, closed = _run(monkeypatch, g)
    row = outcomes[E.GUILD_CLOSED_ROW]
    left = [oid for oid, o in g.orders.items() if o["status"] not in E.GUILD_TERMINAL]
    assert len(left) == 1 and row.get("healthy") is False
    assert f"{left[0]} open" in row["fail_reason"] and "1 of the 5 orders" in row["fail_reason"]
    assert outcomes["theprotocol_guildGetOrder"].get("healthy") is True and closed == [True]


def test_an_order_the_run_cannot_verify_is_named_as_it_reads(monkeypatch):
    # the verify order: every verify refused, so it stays submitted and so does the closing pass's submit order
    g = _Guild(refuse={("theprotocol_guildVerify", "verify"), ("theprotocol_guildVerify", "submit"),
                       ("theprotocol_guildVerify", "award")})
    outcomes, _rest, _closed = _run(monkeypatch, g)
    assert outcomes["theprotocol_guildVerify"].get("healthy") is False
    row = outcomes[E.GUILD_CLOSED_ROW]
    assert row.get("healthy") is False and "3 of the 5 orders" in row["fail_reason"] and "submitted" in row["fail_reason"]


# ── (a) and (d): where it does not stage ───────────────────────────────────────────────────────────────────────────

def test_a_frame_run_is_left_to_phase_3(monkeypatch):
    g = _Guild()
    outcomes, rest, closed = _run(monkeypatch, g, flow_values={"guild_order_id": "gwo_phase3"})
    assert g.calls == [] and outcomes == {} and rest == [] and closed == []


@pytest.mark.parametrize("env,names", [("production", "'production'"), (None, "states no environment")])
def test_a_target_that_states_no_sandbox_stages_nothing_and_says_what_it_read(monkeypatch, env, names):
    g = _Guild(env=env)
    outcomes, rest, closed = _run(monkeypatch, g)
    assert [t for t, _a in g.calls] == ["theprotocol_getPublicRegistryConfig"] and rest == [] and closed == []
    for tool, _tier in E.GUILD_LOCAL_TOOLS:
        row = outcomes[tool]
        assert row.get("healthy") is False and "states 'sandbox'" in str(row) and names in str(row), tool
    assert E.GUILD_CLOSED_ROW not in outcomes


def test_a_poster_the_treasury_leaves_short_posts_nothing(monkeypatch):
    g = _Guild(balance="0.01")
    outcomes, _rest, closed = _run(monkeypatch, g)
    assert g.orders == {} and closed == [True] and E.GUILD_CLOSED_ROW not in outcomes
    assert "the poster holds 0.01" in str(outcomes["theprotocol_guildPostOrder"])


def test_a_guild_that_is_off_stages_nothing(monkeypatch):
    g = _Guild(list_ok=False)
    outcomes, _rest, closed = _run(monkeypatch, g)
    assert g.orders == {} and closed == []
    assert "HTTP 503" in str(outcomes["theprotocol_guildBid"]) and "not usable here" in str(outcomes["theprotocol_guildBid"])


def test_the_lifecycle_is_one_an_operator_run_takes():
    names = {lc["name"] for lc in E.LIFECYCLES}
    assert "earned_guild_local" in names
    lc = next(lc for lc in E.LIFECYCLES if lc["name"] == "earned_guild_local")
    assert not lc.get("needs"), "it needs only the two bridges an operator run gives"

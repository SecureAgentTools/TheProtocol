"""§MCPTEST30 V0662 Wave 1 (gwo_fe22d7e8c391ce1abedc10c7, session-tester): refusal-only slice 1's success legs
(api_tests/contracts/earned_refusal_slice1.py), offline against a scripted target that answers as the routes do.

The first three: getQuantumWorkload on the DID discovery names, updateSlashOrder changed by one and written back,
guildSetOrderRoom on an order of the run's own. Each defect a rule guards is planted once and must turn its own row
red. RED on f569f6a6e (the module does not exist).
"""
from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_refusal_slice1 as S

DEV = "dev-jwt"
QDID = "did:theprotocol:sandbox-a:quantum-provider"
ORDER = [{"source": "bond", "max_percent": 100, "enabled": True},
         {"source": "stake", "max_percent": 50, "enabled": True},
         {"source": "liquid", "max_percent": 100, "enabled": False},
         {"source": "cascade", "max_percent": 100, "enabled": True}]


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


def _no(code: str, error: str):
    return False, _body({"error": error}), code


class _World:
    def __init__(self, env: str = "sandbox", **defects: bool):
        self.env, self.d = env, defects
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.order = copy.deepcopy(ORDER)
        self.version = 7
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.thread: List[Dict[str, Any]] = []

    async def rpc(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _body({"environment": self.env} if self.env else {}), "200"
        if tool == "theprotocol_discoverQuantumAgents":
            if self.d.get("quantum_off"):
                return _no("403", "quantum_workloads_off: Quantum workloads are not enabled on this registry")
            agents = [] if self.d.get("no_quantum_agent") else [{"did": QDID, "quantum": {"kind": "provider"}}]
            return True, _body({"agents": agents, "total": len(agents)}), "200"
        if tool == "theprotocol_getQuantumWorkload":
            if args["did"] != QDID:
                return _no("404", f"agent_card_not_found: no active agent card for {args['did']} on this registry.")
            did = "did:theprotocol:someone-else" if self.d.get("wrong_did") else QDID
            return True, _body({"agent_did": did, "uri": "https://theprotocol.cloud/extensions/quantum-workload/v1",
                                "params": {"version": "1.0"}, "check": {"valid": True, "problems": []}}), "200"
        if tool == "theprotocol_guildPostOrder":
            assert "room_id" not in args, "the order is posted WITHOUT a room"
            self.orders["gwo_run1"] = {"id": "gwo_run1", "status": "open", "announce_conversation_id": None}
            return True, _body({"order_id": "gwo_run1", "status": "open"}), "200"
        if tool == "theprotocol_sendChatMessage":
            assert args.get("target_agent_did") == "did:peer" and args.get("agent_jwt") == "jwt:poster"
            return True, _body({"conversation_id": "conv-run-1", "created": True}), "201"
        if tool == "theprotocol_guildSetOrderRoom":
            o = self.orders.get(args["order_id"])
            if o is None:
                return _no("404", "guildSetOrderRoom returned HTTP 404: Order not found")
            if not self.d.get("room_not_kept"):
                o["announce_conversation_id"] = args["room_id"]
            if not self.d.get("no_card"):
                self.thread.append({"kind": "card", "card": {"type": "guild_order", "order_id": o["id"]}})
            return True, _body({"order_id": o["id"], "room_id": args["room_id"], "card": True}), "200"
        if tool == "theprotocol_guildGetOrder":
            return True, _body({"order": self.orders.get(args["order_id"], {})}), "200"
        if tool == "theprotocol_readThread":
            return True, _body({"messages": [{"kind": "text", "body": "MCP tester: the room order gwo_run1 shows in"}]
                                + self.thread}), "200"
        if tool == "theprotocol_guildCancelOrder":
            self.orders[args["order_id"]]["status"] = "cancelled"
            return True, _body({"status": "cancelled"}), "200"
        raise AssertionError(f"unexpected public call {tool}")

    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_getSlashOrder":
            return True, _body({"section": "slash_waterfall", "value": self.order, "version": self.version}), "200"
        if tool == "theprotocol_updateSlashOrder":
            original = args["reason"].endswith("as it was")
            if self.d.get("writeback_refused") and original:
                return _no("422", "policy refused")
            if not (original and self.d.get("writeback_ignored")):
                self.order = copy.deepcopy(args["order"])
            self.version += 1
            return True, _body({"version": self.version, "slash_waterfall_changed": not self.d.get("unchanged")}), "200"
        if tool == "theprotocol_adminRequest":
            assert args["endpoint"] == "/api/v1/teg/treasury/fund-agent"
            return True, _body({"status_code": 200, "response": {"ok": True}}), "200"
        raise AssertionError(f"unexpected admin call {tool}")


class _Throwaways:
    closed = 0

    def __init__(self, *_a, **_k):
        pass

    async def agent(self, dev, label=""):
        return {"did": f"did:{label}", "agent_jwt": f"jwt:{label}"}

    async def close(self):
        _Throwaways.closed += 1


class _Bag:
    def __init__(self, w: _World, admin: bool = True):
        self.developer_jwt, self.developer_id = DEV, 1
        self.rpc_admin = w.admin if admin else None
        self.event_verifier = None


def _run(fn, w: _World, admin: bool = True) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    asyncio.run(fn(w.rpc, _parse, _Bag(w, admin), out))
    return out


@pytest.fixture(autouse=True)
def _fake_throwaways(monkeypatch):
    monkeypatch.setattr(S.ef, "Throwaways", _Throwaways)


def _healthy(out: Dict[str, dict], name: str) -> bool:
    r = out.get(name) or {}
    return bool(r.get("healthy")) and not r.get("skip_reason")


# ── the module is one of the earned lists ──────────────────────────────────────────────────────────────────────────

def test_the_three_lifecycles_run_with_the_earned_ones():
    names = {lc["name"] for lc in earned_admin_dev.LIFECYCLES}
    assert {"earn_quantum_workload", "earn_slash_order", "earn_guild_order_room"} <= names


# ── getQuantumWorkload ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_workload_is_read_for_the_did_discovery_names_and_the_refusal_is_kept():
    w = _World()
    out = _run(S.lifecycle_earn_quantum_workload, w)
    assert _healthy(out, S.QUANTUM)
    assert ("theprotocol_getQuantumWorkload", {"did": QDID}) in w.calls
    ref = [n for n in out if n.startswith("refusal: getQuantumWorkload")]
    assert ref and _healthy(out, ref[0])


def test_an_answer_for_another_did_is_a_bug_find():
    out = _run(S.lifecycle_earn_quantum_workload, _World(wrong_did=True))
    assert not out[S.QUANTUM]["healthy"] and "BUG-FIND" in out[S.QUANTUM]["fail_reason"]


def test_no_quantum_agent_is_not_measured_and_off_writes_nothing():
    out = _run(S.lifecycle_earn_quantum_workload, _World(no_quantum_agent=True))
    assert out[S.QUANTUM]["skip_reason"].startswith("NOT MEASURED") and "quantum workload" in out[S.QUANTUM]["skip_reason"]
    assert _run(S.lifecycle_earn_quantum_workload, _World(quantum_off=True)) == {}


# ── updateSlashOrder ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_order_changes_by_one_and_is_written_back():
    w = _World()
    out = _run(S.lifecycle_earn_slash_order, w)
    row = out["admin_effect: updateSlashOrder"]
    assert row["healthy"], row.get("fail_reason")
    writes = [a["order"] for t, a in w.calls if t == "theprotocol_updateSlashOrder"]
    assert len(writes) == 2 and writes[0][0]["max_percent"] == 99 and writes[1] == ORDER
    assert w.order == ORDER, "the target's order reads as it was"


def test_a_write_back_that_does_not_hold_is_a_bug_find_even_after_a_good_change():
    for defect in ("writeback_refused", "writeback_ignored"):
        out = _run(S.lifecycle_earn_slash_order, _World(**{defect: True}))
        row = out["admin_effect: updateSlashOrder"]
        assert not row["healthy"] and "could not be written back" in row["fail_reason"], defect


def test_a_change_the_answer_does_not_report_is_a_bug_find_and_still_written_back():
    w = _World(unchanged=True)
    out = _run(S.lifecycle_earn_slash_order, w)
    assert not out["admin_effect: updateSlashOrder"]["healthy"]
    assert w.order == ORDER


def test_the_slash_order_is_never_touched_off_a_stated_sandbox():
    for env in ("production", ""):
        w = _World(env=env)
        out = _run(S.lifecycle_earn_slash_order, w)
        assert "NOT MEASURED" in out["admin_effect: updateSlashOrder"]["skip_reason"]
        assert not [t for t, _ in w.calls if t == "theprotocol_updateSlashOrder"], env


# ── guildSetOrderRoom ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_order_is_named_into_a_room_of_the_poster_read_back_and_cancelled():
    w = _World()
    _Throwaways.closed = 0
    out = _run(S.lifecycle_earn_guild_order_room, w)
    assert _healthy(out, S.ROOM), out.get(S.ROOM)
    assert w.orders["gwo_run1"]["status"] == "cancelled" and _Throwaways.closed == 1
    ref = [n for n in out if n.startswith("refusal: guildSetOrderRoom")]
    assert ref and _healthy(out, ref[0])


@pytest.mark.parametrize("defect", ["room_not_kept", "no_card"])
def test_a_room_the_order_does_not_show_in_is_a_bug_find(defect):
    w = _World(**{defect: True})
    out = _run(S.lifecycle_earn_guild_order_room, w)
    assert not out[S.ROOM]["healthy"] and "BUG-FIND" in out[S.ROOM]["fail_reason"]
    assert w.orders["gwo_run1"]["status"] == "cancelled"


def test_no_order_is_posted_off_a_stated_sandbox():
    w = _World(env="production")
    out = _run(S.lifecycle_earn_guild_order_room, w)
    assert "NOT MEASURED" in out[S.ROOM]["skip_reason"]
    assert not [t for t, _ in w.calls if t == "theprotocol_guildPostOrder"]


# ── A2 (his seq 3182): the three manufactured states, each on the run's own subject, sandbox or pair only ───────────

from agentvault_registry.api_tests.contracts import earned_agent_public as EAP           # noqa: E402
from agentvault_registry.api_tests.contracts import earned_ad_developers as DEVS         # noqa: E402
from agentvault_registry.api_tests.contracts import mcp_lifecycles as ML                 # noqa: E402


class _FlagWorld(_World):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.flags: Dict[str, Dict[str, Any]] = {}
        self.sql: List[str] = []

    async def db_write(self, bag, sql, params):
        self.sql.append(sql)
        if sql.startswith("INSERT INTO agent_flags"):
            assert params["did"] == "did:flagged" and "'mcp_tester'" in sql
            self.flags[params["id"]] = {"id": params["id"], "acknowledged_at": None}
            return 1, None
        if sql.startswith("DELETE FROM agent_flags"):
            assert "source = 'mcp_tester'" in sql
            return (1 if self.flags.pop(params["id"], None) else 0), None
        raise AssertionError(sql)

    async def admin(self, tool, args, jwt="", timeout=20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_getAdminAgentFlags":
            return True, _body({"agent_did": args["agent_did"], "flags": list(self.flags.values())}), "200"
        if tool == "theprotocol_acknowledgeAgentFlag":
            f = self.flags[args["flag_id"]]
            if not self.d.get("ack_not_kept"):
                f["acknowledged_at"] = "2026-11-13T23:00:00+00:00"
            return True, _body({"status": "acknowledged", "flag": {**f, "acknowledged_at": "2026-11-13T23:00:00+00:00"}}), "200"
        return await super().admin(tool, args, jwt, timeout)


def _run_flag(w: _FlagWorld, monkeypatch) -> Dict[str, dict]:
    monkeypatch.setattr(EAP, "_db_write", w.db_write)

    class _T(_Throwaways):
        async def agent(self, dev, label=""):
            return {"did": "did:flagged", "agent_jwt": "jwt:flagged"}
    monkeypatch.setattr(S.ef, "Throwaways", _T)
    return _run(S.lifecycle_earn_agent_flag, w)


def test_a_flag_raised_on_the_runs_own_agent_is_acknowledged_read_back_and_removed(monkeypatch):
    w = _FlagWorld()
    out = _run_flag(w, monkeypatch)
    row = out["admin_effect: acknowledgeAgentFlag"]
    assert row["healthy"], row.get("fail_reason")
    assert w.flags == {} and w.sql[-1].startswith("DELETE"), "the flag is gone with the agent"


def test_an_acknowledge_the_list_does_not_keep_is_a_bug_find_and_the_flag_still_removed(monkeypatch):
    w = _FlagWorld(ack_not_kept=True)
    out = _run_flag(w, monkeypatch)
    assert not out["admin_effect: acknowledgeAgentFlag"]["healthy"] and w.flags == {}


def test_no_flag_is_raised_off_a_stated_sandbox(monkeypatch):
    w = _FlagWorld(env="production")
    out = _run_flag(w, monkeypatch)
    assert "NOT MEASURED" in out["admin_effect: acknowledgeAgentFlag"]["skip_reason"] and w.sql == []


def _dev_world(env="sandbox", verified=True, n=1):
    state = {"verified": verified, "writes": []}

    async def detail(bag, parse, dev_id):
        return True, {"is_verified": state["verified"]}, "200"

    async def db_write(bag, sql, params):
        state["writes"].append((sql, dict(params)))
        if n == 1:
            state["verified"] = False
        return n, None

    async def rpc(tool, args, jwt="", timeout=20):
        assert tool == "theprotocol_getPublicRegistryConfig"
        return True, _body({"environment": env}), "200"
    return state, detail, db_write, rpc


@pytest.mark.parametrize("env,verified,n,want_none,writes", [
    ("sandbox", True, 1, True, 1),      # the sandbox's verified mint, set unverified for the run's own developer
    ("sandbox", False, 1, True, 0),     # a registration that left it unverified: nothing to write
    ("production", True, 1, False, 0),  # never off a stated sandbox
    ("sandbox", True, 0, False, 1),     # a write that changed nothing is said, never a pass
])
def test_the_unverified_account_is_made_only_on_a_sandbox_and_only_for_the_runs_own(monkeypatch, env, verified, n,
                                                                                     want_none, writes):
    state, detail, db_write, rpc = _dev_world(env, verified, n)
    monkeypatch.setattr(DEVS, "_dev_detail", detail)
    monkeypatch.setattr(EAP, "_db_write", db_write)
    dev = {"email": "mcp-throwaway-developer-admin-1@example.com", "name": "mcp-throwaway-developer-admin-1"}
    why = asyncio.run(DEVS._unverified_own(rpc, _parse, _Bag(_World()), dev, 42))
    assert (why is None) == want_none, why
    assert len(state["writes"]) == writes
    for sql, params in state["writes"]:
        assert "name LIKE 'mcp-throwaway-%'" in sql and params == {"id": 42, "email": dev["email"]}


def test_the_failed_commons_award_is_made_on_the_runs_own_struck_submission_and_written_off(monkeypatch):
    seen: List[str] = []

    async def target_db(bag, sql, params, write=False):
        seen.append(sql)
        if write:
            assert "'failed'" in sql and " 0, 0, 0, 0," in sql and params == {"x": 77, "s": 9}
            return 1, None
        return 501, None

    async def effect(bag, parse, tool, args, outcomes, check=None, **kw):
        assert tool == "theprotocol_adminCommonsWriteOffAward" and args["award_id"] == 501 and args["season_id"] == 9
        ans = {"id": 501, "status": "written_off", "unpaid_awards": 1}
        outcomes["admin_effect: adminCommonsWriteOffAward"] = {"healthy": check(ans) is None}
        return True, ans
    monkeypatch.setattr(ML, "_target_db", target_db)
    monkeypatch.setattr(ML._ef, "effect", effect)
    out: Dict[str, dict] = {}
    asyncio.run(ML._commons_write_off_on_a_pair(_Bag(_World()), _parse, out, 9, 77, DEV))
    assert out["admin_effect: adminCommonsWriteOffAward"]["healthy"] and len(seen) == 2


def test_the_write_off_rides_the_pairs_only_payment_before_the_pay():
    import inspect
    src = inspect.getsource(ML._commons_pay_on_a_pair)
    assert src.index("_commons_write_off_on_a_pair(") < src.index("ok_pay, _ans = await _ef.effect(")
    assert "struck=xid" in inspect.getsource(ML.lifecycle_commons_season)


# ── A7: the OAuth surface on a trust entry of the run's own ─────────────────────────────────────────────────────────

class _OAuthWorld(_World):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.trust: Dict[str, Dict[str, Any]] = {}

    def _auth(self, args):
        e = next((t for t in self.trust.values() if t["client_id"] == args.get("client_id")), None)
        return e is not None and e["client_secret"] == args.get("client_secret")

    async def rpc(self, tool, args, jwt="", timeout=20):
        if tool == "theprotocol_getPublicRegistryConfig":
            return await super().rpc(tool, args, jwt, timeout)
        self.calls.append((tool, dict(args)))
        if not self.trust and tool in ("theprotocol_oauthIntrospect", "theprotocol_oauthRevoke",
                                       "theprotocol_oauthTokenExchange"):
            return _no("501", "Cross-registry OAuth federation is not enabled on this registry")
        if tool == "theprotocol_oauthIntrospect":
            if not self._auth(args):
                return _no("401", "oauthIntrospect returned HTTP 401: Invalid client credentials")
            return True, _body({"active": bool(self.d.get("introspect_active"))}), "200"
        if tool == "theprotocol_oauthRevoke":
            assert self._auth(args)
            return True, _body({"revoked": False}), "200"
        if tool == "theprotocol_oauthTokenExchange":
            return _no("401", "oauthTokenExchange returned HTTP 401: Invalid subject token")
        if tool == "theprotocol_oauthFederationTrustList":
            return True, _body({"trusted_registries": [{"registry_url": u} for u in self.trust]}), "200"
        raise AssertionError(tool)

    async def admin(self, tool, args, jwt="", timeout=20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_adminRequest":
            b = args["body"]
            assert args["endpoint"] == "/api/v1/oauth/federation/trust" and b["registry_url"].endswith(".invalid")
            assert b["public_key_url"].startswith(b["registry_url"]), "the issuer's keys are unreachable too"
            self.trust[b["registry_url"]] = b
            return True, _body({"status_code": 201, "response": {"status": "created"}}), "200"
        if tool == "theprotocol_deleteOauthFederationTrust":
            if not self.d.get("delete_not_kept"):
                self.trust.pop(args["registry_url"], None)
            return True, _body({"status": "removed"}), "200"
        raise AssertionError(tool)


def test_the_oauth_tools_run_on_a_trust_entry_of_the_runs_own_and_it_is_removed():
    w = _OAuthWorld()
    out = _run(S.lifecycle_earn_oauth_trust, w)
    for tool in (S.INTROSPECT, S.REVOKE):
        assert _healthy(out, tool), out.get(tool)
    assert out["admin_effect: deleteOauthFederationTrust"]["healthy"]
    assert "NOT MEASURED" in out[S.EXCHANGE]["skip_reason"] and "first one" in out[S.EXCHANGE]["skip_reason"]
    assert _healthy(out, "refusal: oauthIntrospect a client secret the entry does not hold")
    assert _healthy(out, "refusal: oauthTokenExchange a subject token no trusted peer signed")
    assert w.trust == {}


def test_a_token_never_issued_that_reads_active_is_a_bug_find():
    out = _run(S.lifecycle_earn_oauth_trust, _OAuthWorld(introspect_active=True))
    assert not out[S.INTROSPECT]["healthy"] and "BUG-FIND" in out[S.INTROSPECT]["fail_reason"]


def test_an_entry_the_delete_leaves_standing_is_a_bug_find():
    w = _OAuthWorld(delete_not_kept=True)
    out = _run(S.lifecycle_earn_oauth_trust, w)
    assert not out["admin_effect: deleteOauthFederationTrust"]["healthy"]


def test_no_trust_entry_is_added_off_a_stated_sandbox():
    w = _OAuthWorld(env="production")
    out = _run(S.lifecycle_earn_oauth_trust, w)
    assert all("NOT MEASURED" in out[t]["skip_reason"] for t in (S.INTROSPECT, S.REVOKE, S.EXCHANGE))
    assert not [t for t, _ in w.calls if t == "theprotocol_adminRequest"]

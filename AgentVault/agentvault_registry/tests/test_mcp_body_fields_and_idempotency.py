"""§MCPTEST30 (2026-10-01) — a tool's JSON body carries the fields its route reads, and a money tool can be retried.

The request survey's BODY_UNDECLARED class (gated in tests/test_mcp_tool_requests_meet_their_routes.py): pydantic drops a
body field the route's model does not declare and the request answers 200. runDiagnosticsSubset sent `checks` to a route
reading `check_ids`, whose absence runs EVERY check; forkBundle's `new_name` never named the fork; authSetNewPassword put
the recovery token in the body of a route that reads it as a bearer (every call 401); lockUnits put a fresh random key
in the body, so no MCP money call could ever be retried safely. The money routes honor an Idempotency-Key header (24 h,
§pass57); the tools now forward a caller's key, namespaced to the caller.
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from agentvault_registry.mcp import tools_admin, tools_agent, tools_developer, tools_discovery


class _Auth:
    raw_token = "agent-jwt"
    agent_did = "did:theprotocol:caller-1"
    developer_id = 7
    is_admin = True
    auth_type = "agent"
    agent_id = 1


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.headers, self.text = status, body or {}, {"content-type": "application/json"}, "{}"

    def json(self):
        return self._body


class _Client:
    sent = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, params=None, headers=None, **k):
        _Client.sent.append({"url": url, "json": json, "headers": dict(headers or {})})
        return _Resp(200, {"transaction_id": "tx-1", "status": "completed", "stake_id": "s1", "amount": "1"})

    async def get(self, url, params=None, headers=None, **k):
        _Client.sent.append({"url": url, "get": True})
        return _Resp(200, {"stakes": [], "id": "s1", "amount": "1"})


@pytest.fixture
def wire(monkeypatch):
    _Client.sent = []
    for mod in (tools_agent, tools_discovery):
        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(tools_agent, "require_agent_auth", lambda auth: None)
    return _Client.sent


def _run(coro):
    return asyncio.run(coro)


def test_the_header_is_the_callers_and_absent_without_a_key():
    a = _Auth()
    assert tools_agent.idempotency_header(a, None) == {} and tools_agent.idempotency_header(a, "  ") == {}
    assert tools_agent.idempotency_header(a, "retry-7") == {"Idempotency-Key": "mcp:did:theprotocol:caller-1:retry-7"}
    b = _Auth()
    b.agent_did = "did:theprotocol:caller-2"
    assert tools_agent.idempotency_header(a, "1") != tools_agent.idempotency_header(b, "1"), \
        "two callers who both pick '1' must never replay each other"


def test_a_transfer_and_a_stake_send_the_key_as_the_header_and_never_in_the_body(wire):
    _run(tools_agent.transfer_tokens(_Auth(), recipient_did="did:theprotocol:r", amount="0.01", idempotency_key="k1"))
    _run(tools_agent.stake_tokens(_Auth(), amount="1", lock_period_days=7, idempotency_key="k2"))
    _run(tools_agent.transfer_tokens(_Auth(), recipient_did="did:theprotocol:r", amount="0.01"))
    t, st, bare = wire[0], wire[1], wire[2]
    assert t["headers"]["Idempotency-Key"] == "mcp:did:theprotocol:caller-1:k1" and "idempotency_key" not in t["json"]
    assert st["headers"]["Idempotency-Key"] == "mcp:did:theprotocol:caller-1:k2" and set(st["json"]) == {"amount", "lock_period"}
    assert "Idempotency-Key" not in bare["headers"], "no key asked for, none invented"


def test_a_smart_send_sends_the_key_as_the_header_and_none_without_one(wire):
    """D6-054: smartSend sent no Idempotency-Key, so a retried call that had timed out could move units twice; /teg/send
    forwards the header to the rail it picks."""
    _run(tools_agent.smart_send_tool(_Auth(), receiver_did="did:theprotocol:r", amount="0.5", idempotency_key="k5"))
    _run(tools_agent.smart_send_tool(_Auth(), receiver_did="did:theprotocol:r", amount="0.5"))
    keyed, bare = wire[0], wire[1]
    assert keyed["url"].endswith("/api/v1/teg/send")
    assert keyed["headers"]["Idempotency-Key"] == "mcp:did:theprotocol:caller-1:k5" and "idempotency_key" not in keyed["json"]
    assert "Idempotency-Key" not in bare["headers"], "no key asked for, none invented"
    assert "theprotocol_smartSend" in tools_agent.IDEMPOTENT_MONEY_TOOLS


def test_every_idempotent_money_tool_declares_and_takes_the_key():
    schemas = {s["name"]: s for s in tools_agent.AGENT_TOOL_SCHEMAS}
    from agentvault_registry.mcp import server
    for name in tools_agent.IDEMPOTENT_MONEY_TOOLS:
        assert "idempotency_key" in schemas[name]["inputSchema"]["properties"], name
        assert "idempotency_key" in inspect.signature(server.TOOL_DISPATCH[name]).parameters, name


def test_the_post_helper_carries_extra_headers(monkeypatch, wire):
    _run(tools_agent.release_payment_by_id(_Auth(), token_id="tok-1", idempotency_key="k3"))
    _run(tools_agent.teg_cross_registry_transfer_direct(_Auth(), receiver_did="did:theprotocol:r", amount="1",
                                                        memo="hello", idempotency_key="k4"))
    rel, x = wire[0], wire[1]
    assert rel["headers"]["Idempotency-Key"].endswith(":k3")
    assert x["json"] == {"receiver_did": "did:theprotocol:r", "amount": "1", "message": "hello"}
    assert x["headers"]["Idempotency-Key"].endswith(":k4")


@pytest.fixture
def posted(monkeypatch):
    seen = []

    async def admin_post(auth, path, json_body=None, **kw):
        seen.append((path, json_body))
        return {"ok": True}

    async def dev_request(auth, method, path, json_body=None, **kw):
        seen.append((path, json_body))
        return {"ok": True}
    monkeypatch.setattr(tools_admin, "_admin_post", admin_post)
    monkeypatch.setattr(tools_developer, "_dev_request", dev_request)
    return seen


def test_admin_and_developer_tools_send_the_fields_their_routes_read(posted):
    a = _Auth()
    _run(tools_admin.run_diagnostics_subset(a, checks=["db"], targets=["self"]))
    _run(tools_admin.reject_operator_application(a, application_id="app-1", reason="incomplete"))
    _run(tools_admin.approve_funding(a, request_id=3, approved_amount="12.5"))
    _run(tools_admin.composite_health_check(a, agent_token="jwt"))
    _run(tools_admin.update_support_ticket_status(a, ticket_id="9", status="closed"))
    _run(tools_developer.fork_bundle(a, bundle_id="b1", new_name="My fork"))
    bodies = [b for _, b in posted]
    assert bodies == [{"check_ids": ["db"], "targets": ["self"]}, {"notes": "incomplete"}, {"approved_amount": "12.5"},
                      {"agent_token": "jwt"}, {"status": "closed"}, {"name": "My fork"}]


def test_the_simulation_start_mirrors_its_route(posted):
    from agentvault_registry.routers.admin_simulation import SimStartRequest
    assert set(tools_admin.SIM_START_FIELDS) == set(SimStartRequest.model_fields) - {"raw", "metrics_jsonl"}
    schema = next(s for s in tools_admin.ADMIN_TOOL_SCHEMAS if s["name"] == "theprotocol_startSimulation")
    assert set(schema["inputSchema"]["properties"]) == set(tools_admin.SIM_START_FIELDS)
    out = _run(tools_admin.start_simulation(_Auth(), mode="market", dynamic=True, max_concurrency=20, pairs=10))
    assert out == {"ok": True} and posted[-1][1] == {"mode": "market", "dynamic": True, "max_concurrency": 20, "pairs": 10}
    refused = _run(tools_admin.start_simulation(_Auth(), scenario="stress"))
    assert "unknown simulation fields ['scenario']" in refused["error"] and len(posted) == 1


def test_the_recovery_token_is_a_bearer(wire):
    _run(tools_discovery.auth_set_new_password(token="recovery-jwt", new_password="N3w-passw0rd!!"))
    sent = wire[-1]
    assert sent["headers"] == {"Authorization": "Bearer recovery-jwt"} and sent["json"] == {"new_password": "N3w-passw0rd!!"}
    assert "recovery-jwt" not in json.dumps(sent["json"])


class Ledger:
    """A fake registry for the replay probe: `replays` decides whether a keyed retry answers the first result again."""

    def __init__(self, replays=True, retry_text=None, interfere=False, body_blind=False):
        self.replays, self.balance, self.tx, self.seen_keys = replays, 5, 0, {}
        self.body_blind = body_blind   # V0525: a key reused with another amount answers the first result (the bug)
        self.key_amounts = {}
        self.messages = []          # (transaction id, attached message) per transfer that moved money
        self.interfere = interfere  # another lifecycle pays the same receiver during the concurrent pair
        self.refused_keys = set()
        self.retry_text = retry_text or ("Error: Transfer failed (HTTP 422): Idempotency-Key 'k' is claimed on this "
                                         "endpoint by an earlier request that has not stored a result: it is still in "
                                         "progress, or it ended without one (a refusal or an error stores none).")

    async def rpc(self, tool, args, jwt="", timeout=20):
        if tool == "theprotocol_getMyTegTransactions":
            rows = [{"transaction_id": t, "attached_message": m} for t, m in self.messages]
            return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(
                {"transactions": rows})}]}}, "200"
        if tool == "theprotocol_getMyBalance":
            return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(
                {"liquid_balance": f"{self.balance / 100:.2f}", "staked_balance": "0"})}]}}, "200"
        k = args.get("idempotency_key")
        if args.get("recipient_did", "").startswith("did:theprotocol:") and args["recipient_did"] != "did:theprotocol:second":
            if k in self.refused_keys:
                text = self.retry_text
            else:
                self.refused_keys.add(k)
                text = "Error: Transfer failed (HTTP 404): Recipient agent not found on this registry or any federated peer."
            return True, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}, "200"
        if (self.replays and k in self.key_amounts and self.key_amounts[k] != args.get("amount")
                and not self.body_blind):
            return True, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": (
                "Error: Transfer failed (HTTP 422): Idempotency-Key 'k' already used on this endpoint with a different "
                "request body")}]}}, "200"
        self.key_amounts.setdefault(k, args.get("amount"))
        if self.replays and k in self.seen_keys:
            out = self.seen_keys[k]
        else:
            self.tx += 1
            self.balance += 1
            out = {"transaction_id": f"tx-{self.tx}", "status": "completed"}
            self.seen_keys[k] = out
            self.messages.append((out["transaction_id"], args.get("message")))
            if self.interfere and "concurrent" in (args.get("message") or ""):
                self.interfere = False
                self.balance += 1                      # amount_bounds' accepted 1e-2, round 7
                self.messages.append(("tx-other", "MCP tester: 0.01 in scientific notation"))
        return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(out)}]}}, "200"


class ReplayBag:
    developer_jwt, sentinel_jwt, sentinel_did = "dev", "sentinel-jwt", "did:theprotocol:sentinel"

    def __init__(self, second=True):
        self.flow_values = {"second_agent_did": "did:theprotocol:second", "second_agent_jwt": "second-jwt"} if second else {}

    def get(self, k, d=None):
        return self.flow_values.get(k, d)


def _replay(ledger, bag, row="idempotency: transferUnits"):
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _parse_rpc_result
    out = {}
    asyncio.run(L.lifecycle_money_idempotent_replay(ledger.rpc, _parse_rpc_result, bag, out))
    return out[row]


REFUSED = "idempotency: a refused transferUnits retried"
CONCURRENT = "idempotency: concurrent transferUnits"


def test_another_lifecycle_paying_the_receiver_is_not_a_double_payment():
    """Round 7: amount_bounds paid the same receiver 0.01 between the concurrent pair's two balance reads; the pair was
    called a double payment while the ledger held ONE transaction with its message."""
    row = _replay(Ledger(replays=True, interfere=True), ReplayBag(), CONCURRENT)
    assert row["healthy"] is True and row["result_excerpt"]["own_transfers"] == 1
    assert row["result_excerpt"]["receiver_moved"] == "0.02", "the balance still shows the other payment, as evidence"


def test_a_concurrent_keyed_pair_moves_money_once():
    good = _replay(Ledger(replays=True), ReplayBag(), CONCURRENT)
    assert good["healthy"] is True and good["result_excerpt"]["transactions"] == 1
    assert good["result_excerpt"]["receiver_moved"] == "0.01"
    bad = _replay(Ledger(replays=False), ReplayBag(), CONCURRENT)
    assert bad["healthy"] is False and bad["fail_reason"].startswith("BUG-FIND: idempotency: two concurrent")


def test_a_refused_keyed_retry_must_not_be_told_it_is_in_progress():
    honest = _replay(Ledger(), ReplayBag(), REFUSED)
    assert honest["healthy"] is True and honest["result_excerpt"]["retry_is"] == "the honest unresolved-claim answer"
    again = _replay(Ledger(retry_text="Error: Transfer failed (HTTP 404): Recipient agent not found."), ReplayBag(), REFUSED)
    assert again["healthy"] is True and again["result_excerpt"]["retry_is"] == "the refusal again"
    old = _replay(Ledger(retry_text="Error: Transfer failed (HTTP 422): A request with Idempotency-Key 'k' is already "
                                    "in progress on this endpoint. Retry shortly to receive the result."), ReplayBag(), REFUSED)
    assert old["healthy"] is False and old["fail_reason"].startswith("BUG-FIND: idempotency: the retry of a REFUSED")


class _ClaimRedis:
    """A claim another request holds, PENDING (no stored result), with the same body."""

    def __init__(self, body_hash, ttl=37, ttl_raises=False):
        self.value, self._ttl, self.ttl_raises = json.dumps({"body_hash": body_hash, "pending": True}), ttl, ttl_raises

    async def set(self, *a, **k):
        return False

    async def get(self, k):
        return self.value

    async def ttl(self, k):
        if self.ttl_raises:
            raise RuntimeError("ttl unavailable")
        return self._ttl


def _lookup(monkeypatch, redis):
    from agentvault_registry.background_tasks import leader
    from agentvault_registry.services.idempotency import cache

    async def _get():
        return redis
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.01)
    return asyncio.run(cache.idempotency_lookup("teg.transfer", "k1", {"a": 1}, principal=_CALLER))


_CALLER = "agent:did:theprotocol:sender"   # D6-777: the claim is this caller's (cache.agent_caller)


def test_an_unresolved_claim_names_both_states_and_never_fails_open(monkeypatch):
    from agentvault_registry.services.idempotency import cache
    bh = cache._record_hash(_CALLER, {"a": 1})
    cached, err = _lookup(monkeypatch, _ClaimRedis(bh, ttl=37))
    assert cached is None and "in 37 s" in err and "ended without one" in err and "in progress" in err
    assert "Idempotency-Key" in err, "the AGORA repatriation reads a 422 carrying it as in-flight"
    cached, err = _lookup(monkeypatch, _ClaimRedis(bh, ttl_raises=True))
    assert cached is None and err and f"within {cache.IDEMPOTENCY_CLAIM_TTL_SECONDS} s" in err, \
        "a TTL read failure must still refuse: (None, None) would run the guarded side effect again"


BODY = "idempotency: transferUnits with another body"


def test_one_key_with_another_amount_is_the_contracts_422_and_moves_nothing():
    """V0525: measured by hand on sbx-alpha (V0523) first: 200, then 422 "already used", then the first transaction again."""
    good = _replay(Ledger(), ReplayBag(), BODY)
    assert good["healthy"] is True, good
    assert good["result_excerpt"] == {"other_body": "refused 422", "same_body_again_is_the_first": True, "own_transfers": 1}
    blind = _replay(Ledger(body_blind=True), ReplayBag(), BODY)
    assert blind["healthy"] is False and "answered the first result for a different request" in blind["fail_reason"]
    pays = _replay(Ledger(replays=False), ReplayBag(), BODY)
    assert pays["healthy"] is False and "moved money again" in pays["fail_reason"]


def test_a_keyed_retry_that_replays_is_healthy_and_one_that_pays_again_is_a_bug_find():
    good = _replay(Ledger(replays=True), ReplayBag())
    assert good["healthy"] is True and good["result_excerpt"]["same_transaction"] is True
    assert good["result_excerpt"]["receiver_moved"] == "0.01"
    bad = _replay(Ledger(replays=False), ReplayBag())
    assert bad["healthy"] is False and bad["fail_reason"].startswith("BUG-FIND: idempotency")
    skip = _replay(Ledger(), ReplayBag(second=False))
    assert skip["skip_reason"].startswith("NOT MEASURED: the setup made no second agent")


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

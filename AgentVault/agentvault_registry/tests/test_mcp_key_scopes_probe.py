"""§MCPTEST30 (V0528, 2026-10-01) — the key scopes probe: a narrowed API key is refused the admin MCP surface and the
minting of keys; an `mcp:admin` key is admitted.

Driven against a fake target that plays the registry's scope rules (§MCPSCOPE: a key without `mcp:admin` or `*` gets
no admin surface; AL-4: a key without `keys:manage` mints no key). An honest registry passes all three rows; one that
ignores scopes is named on the narrowed rows; one that refuses EVERY scoped key is named on the positive control.
Every key the probe minted is deleted, and no key reaches a row.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import key_scopes as KS


class _Target:
    def __init__(self, enforce=True, admit_admin_scope=True):
        self.enforce, self.admit_admin_scope = enforce, admit_admin_scope
        self.keys = {}          # plain -> {"id", "scopes", "live"}
        self.deleted = []

    def _mint(self, scopes):
        kid = len(self.keys) + 1
        plain = f"avreg_s{kid}"
        self.keys[plain] = {"id": kid, "scopes": scopes, "live": True}
        return plain, kid

    def _admin_ok(self, jwt):
        if jwt == "dev.jwt":
            return True
        k = self.keys.get(jwt)
        if not k or not k["live"]:
            return False
        if not self.enforce:
            return True
        if "mcp:admin" in k["scopes"]:
            return self.admit_admin_scope
        return "*" in k["scopes"]

    async def http(self, method, path, *, body=None, bearer="", **_k):
        assert (method, path, bearer) == ("POST", "/api/v1/auth/api-keys", "dev.jwt")
        j = json.loads(body)
        plain, kid = self._mint(j["scopes"])
        return "200", json.dumps({"plain_api_key": plain, "api_key_info": {"id": kid}})

    async def raw(self, body, path="/mcp/rpc", jwt="", timeout=30):
        assert path == "/mcp/admin/rpc"
        if self._admin_ok(jwt):
            return "200", {"result": {"content": [{"type": "text", "text": "{}"}]}}, None
        return "200", {"error": {"code": -32001, "message": "admin required"}}, None

    @staticmethod
    def _env(inner):
        return {"result": {"content": [{"type": "text", "text": json.dumps(inner)}]}}

    async def rpc(self, tool, args, jwt="", timeout=30):
        if tool == "theprotocol_getMyDeveloperProfile":
            ok = jwt == "dev.jwt" or bool(self.keys.get(jwt, {}).get("live"))
            return ok, self._env({"id": 7} if ok else {"error": "auth"}), "200"
        if tool == "theprotocol_createApiKey":
            k = self.keys.get(jwt)
            if self.enforce and k and "*" not in k["scopes"] and "keys:manage" not in k["scopes"]:
                return True, self._env({"error": "HTTP 403: lacks the 'keys:manage' scope"}), "200"
            plain, kid = self._mint(["*"])
            return True, self._env({"plain_api_key": plain, "api_key_info": {"id": kid}}), "200"
        if tool == "theprotocol_deleteMyApiKey":
            self.deleted.append(int(args["key_id"]))
            return True, self._env({}), "204"
        raise AssertionError(tool)


def _run(target):
    out = {}
    bag = type("Bag", (), {"developer_jwt": "dev.jwt", "http_in_target": target.http, "rpc_raw": target.raw})()

    def parse(body):
        return json.loads(body["result"]["content"][0]["text"])

    def answered(ok, inner, code):
        return bool(ok) and not (isinstance(inner, dict) and inner.get("error"))

    def make_outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"healthy": ok, "fail_reason": fail, "skip_reason": skip_reason}

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(KS.run_scopes(target.rpc, parse, bag, out, make_outcome, answered,
                                              lambda inner: json.dumps(inner)[:80]))
    finally:
        loop.close()
    return out


ROWS = [KS.PREFIX + c for c in ("narrowed key, admin surface", "narrowed key, key minting", "mcp:admin key, admin surface")]


def test_an_honest_registry_passes_and_every_key_is_deleted():
    t = _Target()
    out = _run(t)
    assert [out[r]["healthy"] for r in ROWS] == [True, True, True], out
    assert sorted(t.deleted) == sorted(k["id"] for k in t.keys.values())


def test_a_registry_that_ignores_scopes_is_named_and_the_escalated_key_is_removed():
    t = _Target(enforce=False)
    out = _run(t)
    assert out[ROWS[0]]["healthy"] is False and "WITHOUT the scope was answered" in out[ROWS[0]]["fail_reason"]
    assert out[ROWS[1]]["healthy"] is False
    assert len(t.keys) == 3 and sorted(t.deleted) == [1, 2, 3], "the key the narrowed key minted is deleted too"


def test_a_registry_that_refuses_every_scoped_key_fails_the_positive_control():
    out = _run(_Target(admit_admin_scope=False))
    assert out[ROWS[0]]["healthy"] is True
    assert out[ROWS[2]]["healthy"] is False and "carrying the scope was refused" in out[ROWS[2]]["fail_reason"]


def test_no_key_reaches_a_row():
    assert "avreg_" not in json.dumps(_run(_Target()))

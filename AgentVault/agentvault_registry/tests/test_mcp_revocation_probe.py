"""§MCPTEST30 (V0528, 2026-10-01) — the revocation probe: a removed credential must be refused at once, every time.

The probe's verdict and its drive, against a fake MCP transport that plays a registry. One registry honours every
removal; a second keeps answering a revoked API key on some asks (what a per-worker cache of resolved keys would
do). The probe must pass the first and name the second, and it must never record a credential.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import revocation as RV


def test_the_verdict():
    assert RV.verdict("API key", [True, True, True], [False] * 9) == (True, None, None)
    healthy, fail, _skip = RV.verdict("API key", [True], [False, True, False])
    assert healthy is False and "1 of 3" in fail and fail.startswith("BUG-FIND")
    assert RV.verdict("API key", [False, False], [False])[0] is None, "a key that never worked measures nothing"
    assert RV.verdict("API key", [True], [])[0] is None


class _Registry:
    """A fake MCP transport. `cached_asks` = how many asks after the revoke a stale worker still answers."""

    def __init__(self, cached_asks: int = 0):
        self.keys, self.agents, self.cached_asks, self.after_revoke = {}, {}, cached_asks, 0
        self.seen_args = []

    @staticmethod
    def _env(inner):
        return {"result": {"content": [{"type": "text", "text": json.dumps(inner)}]}}

    async def rpc(self, tool, args, jwt="", timeout=30):
        self.seen_args.append(json.dumps(args))
        if tool == "theprotocol_createApiKey":
            kid = len(self.keys) + 1
            self.keys[f"avreg_k{kid}"] = {"id": kid, "live": True}
            return True, self._env({"plain_api_key": f"avreg_k{kid}", "api_key_info": {"id": kid}}), "200"
        if tool in ("theprotocol_revokeApiKey", "theprotocol_deleteMyApiKey"):
            for k in self.keys.values():
                if str(k["id"]) == str(args["key_id"]):
                    k["live"] = False
            return True, self._env({"ok": True}), "200"
        if tool == "theprotocol_getMyDeveloperProfile":
            k = self.keys.get(jwt)
            if k and not k["live"] and self.after_revoke < self.cached_asks:
                self.after_revoke += 1
                return True, self._env({"id": 7}), "200"
            ok = bool(k and k["live"])
            return ok, self._env({"id": 7} if ok else {"error": "requires developer authentication"}), "200"
        if tool == "theprotocol_createAgent":
            self.agents["did:rv"] = True
            return True, self._env({"did": "did:rv", "client_id": "c", "client_secret": "s"}), "200"
        if tool == "theprotocol_getAgentToken":
            ok = self.agents.get("did:rv", False)
            return ok, self._env({"access_token": "agent.jwt"} if ok else {"error": "HTTP 403 revoked"}), "200"
        if tool == "theprotocol_getMyAgentInfo":
            ok = self.agents.get("did:rv", False)
            return ok, self._env({"did": "did:rv"} if ok else {"error": "HTTP 403 Agent account is revoked"}), "200"
        if tool == "theprotocol_deleteMyAgentByDev":
            self.agents["did:rv"] = False
            return True, self._env({}), "204"
        raise AssertionError(tool)


def _run(reg):
    out = {}
    bag = type("Bag", (), {"developer_jwt": "dev.jwt"})()

    def parse(body):
        return json.loads(body["result"]["content"][0]["text"])

    def answered(ok, inner, code):
        return bool(ok) and not (isinstance(inner, dict) and inner.get("error"))

    def make_outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
        return {"healthy": ok, "fail_reason": fail, "skip_reason": skip_reason}

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(RV.run_revocation(reg.rpc, parse, bag, out, make_outcome, answered,
                                                  lambda inner: json.dumps(inner)[:80]))
    finally:
        loop.close()
    return out


def test_a_registry_that_honours_every_removal_passes():
    out = _run(_Registry())
    for name in ("revokeApiKey", "deleteMyApiKey", "deleteMyAgentByDev"):
        row = out[RV.PREFIX + name]
        assert row["healthy"] is True and not row["skip_reason"], (name, row)
        assert row["result_excerpt"]["after_answered"] == 0
    assert out[RV.PREFIX + "deleteMyAgentByDev"]["result_excerpt"]["new_token_issued"] is False


def test_a_stale_worker_answering_a_revoked_key_is_named():
    out = _run(_Registry(cached_asks=2))
    row = out[RV.PREFIX + "revokeApiKey"]
    assert row["healthy"] is False and "2 of 9" in row["fail_reason"]


def test_no_credential_reaches_a_row():
    out = _run(_Registry())
    text = json.dumps(out)
    assert "avreg_" not in text and "agent.jwt" not in text and "client_secret" not in text

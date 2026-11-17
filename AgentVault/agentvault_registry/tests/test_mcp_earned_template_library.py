"""V0666 Tests package, part B (Guild order gwo_c8a03e81f09c9fa4d1df4a23): the success legs of the six workflow
template tools that pass the MCP suite on a refusal alone on V0664 (api_tests/contracts/earned_template_library.py), offline
against a scripted library that answers as the routes do.

The six: createWorkflowTemplate, publishWorkflowTemplateVersion, getWorkflowTemplate, purchaseWorkflowTemplate,
forkWorkflowTemplate, instantiateWorkflowTemplate. Each defect a rule guards is planted once and must turn its own row red;
a standing target (no MCP_TESTER_EPHEMERAL_TARGET) says why and writes nothing. RED on the base (the module does not exist).
"""
from __future__ import annotations

import asyncio
import copy
import json
from decimal import Decimal
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev, earned_agent_public
from agentvault_registry.api_tests.contracts import earned_template_library as T

DEV = "dev-jwt"
SELLER = {"did": "did:seller", "agent_jwt": "jwt:seller", "access_token": "dev:seller", "email": "s@example.com", "password": "pw"}
PRICE = "1"


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
    """The template library as the routes keep it, and the ledger of the agents that touch it."""

    def __init__(self, env: str = "sandbox", **defects: bool):
        self.env, self.d = env, defects
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.tpl: Dict[str, Dict[str, Any]] = {}
        self.ver: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.bought: set = set()
        self.bal: Dict[str, Decimal] = {"did:buyer": Decimal(5)}
        self.workflows: Dict[str, Dict[str, Any]] = {}
        self.deleted: List[str] = []
        self.patched: List[Tuple[str, Dict[str, Any], Any]] = []
        self.n = 0
        self.public_listing: List[Dict[str, Any]] = [] if defects.get("no_public") else [
            {"id": "wtpl_existing", "slug": "sql-to-postgres", "title": "Customers", "owner_agent_did": "did:other"}]

    def _who(self, args: dict) -> str:
        return {"jwt:seller": "did:seller", "jwt:buyer": "did:buyer"}.get(args.get("agent_jwt"), "")

    async def rpc(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        who = self._who(args)
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _body({"environment": self.env} if self.env else {}), "200"
        if tool == "theprotocol_listWorkflowTemplates":
            return True, _body({"items": self.public_listing + [t for t in self.tpl.values() if t["visibility"] == "public"
                                                               and t.get("current_version")]}), "200"
        if tool == "theprotocol_createWorkflowTemplate":
            if "migration.yaml" not in (args.get("files") or {}):
                return _no("422", "createWorkflowTemplate returned HTTP 422: the kit needs migration.yaml")
            self.n += 1
            tid = f"wtpl_{self.n}"
            if not self.d.get("create_not_stored"):
                self.tpl[tid] = {"id": tid, "slug": args["slug"], "title": args["title"], "owner_agent_did": who,
                                 "visibility": args["visibility"], "pricing_model": args["pricing_model"],
                                 "price": args.get("price"), "current_version": None, "forks": 0}
            self.ver[(tid, 1)] = {"published": False, "content_hash": f"h{self.n}", "files": args["files"]}
            return True, _body({"template_id": tid, "version": 1, "content_hash": f"h{self.n}", "published": False}), "201"
        if tool == "theprotocol_listMyWorkflowTemplates":
            mine = [dict(t, versions=[{"version": v, "published": self.ver[(t["id"], v)]["published"]}
                                      for (i, v) in self.ver if i == t["id"]])
                    for t in self.tpl.values() if t["owner_agent_did"] == who]
            return True, _body({"items": mine}), "200"
        if tool == "theprotocol_publishWorkflowTemplateVersion":
            t = self.tpl.get(args["template_id"])
            v = self.ver.get((args["template_id"], int(args["version"])))
            if t is None or v is None:
                return _no("404", "no such version")
            if v["published"]:
                return _no("409", "publishWorkflowTemplateVersion returned HTTP 409: a published version never changes: add a new version")
            v["published"] = True
            if not self.d.get("publish_not_current"):
                t["current_version"] = int(args["version"])
            return True, _body({"template_id": t["id"], "version": int(args["version"]), "content_hash": v["content_hash"],
                                "published": True}), "200"
        if tool == "theprotocol_getWorkflowTemplate":
            t = self.tpl.get(args["template_id"])
            if t is None:
                if args["template_id"] == "wtpl_existing" and self.public_listing:
                    return True, _body(dict(self.public_listing[0], versions=[{"version": 1}])), "200"
                return _no("404", "HTTP 404: no template with that id")
            out = dict(t, versions=[{"version": 1}] if t["current_version"] else [], structure={"from": "sql", "to": "sql", "steps": 2},
                       counts={"forks": t["forks"]}, current_content_hash=self.ver[(t["id"], 1)]["content_hash"] if t["current_version"] else None)
            if self.d.get("wrong_price"):
                out["price"] = "99"
            return True, _body(out), "200"
        if tool == "theprotocol_getWorkflowTemplateVersion":
            tid = args["template_id"]
            t = self.tpl[tid]
            if t["pricing_model"] == "purchase" and who != t["owner_agent_did"] and (tid, who) not in self.bought:
                return _no("402", "getWorkflowTemplateVersion returned HTTP 402: This template is purchase-priced — buy it first (POST …/purchase), then use its files")
            return True, _body({"template_id": tid, "version": 1, "files": self.ver[(tid, 1)]["files"]}), "200"
        if tool == "theprotocol_purchaseWorkflowTemplate":
            t = self.tpl[args["template_id"]]
            price = Decimal(t["price"])
            if self.bal.get(who, Decimal(0)) < price:
                return _no("402", "the purchase was declined: nothing moved")
            if not self.d.get("purchase_moves_nothing"):
                self.bal[who] = self.bal[who] - price
                self.bal[t["owner_agent_did"]] = self.bal.get(t["owner_agent_did"], Decimal(0)) + price
            if not self.d.get("purchase_not_recorded"):
                self.bought.add((args["template_id"], who))
            return True, _body({"ok": True, "template_id": args["template_id"], "price": t["price"]}), "200"
        if tool == "theprotocol_forkWorkflowTemplate":
            t = self.tpl[args["template_id"]]
            if t["pricing_model"] == "purchase" and who != t["owner_agent_did"] and (args["template_id"], who) not in self.bought:
                return _no("402", "forkWorkflowTemplate returned HTTP 402: This template is purchase-priced — buy it first (POST …/purchase), then use its files")
            self.n += 1
            nid = f"wtpl_{self.n}"
            self.tpl[nid] = {"id": nid, "slug": t["slug"] + "-fork", "title": "Fork of " + t["title"], "owner_agent_did": who,
                             "visibility": "private", "pricing_model": "free", "price": None, "current_version": None, "forks": 0,
                             "forked_from_template_id": None if self.d.get("fork_no_parent") else args["template_id"]}
            self.ver[(nid, 1)] = {"published": False, "content_hash": "hf", "files": self.ver[(args["template_id"], 1)]["files"]}
            t["forks"] += 1
            return True, _body({"template_id": nid, "forked_from": args["template_id"], "version": 1, "published": False}), "201"
        if tool == "theprotocol_instantiateWorkflowTemplate":
            self.n += 1
            wid = f"wf_{self.n}"
            v = self.ver[(args["template_id"], 1)]
            self.workflows[wid] = {"id": wid, "owner": who, "status": "draft", "steps": [{"key": "dry-run"}, {"key": "reconcile"}],
                                   "template": {"id": args["template_id"], "version": 1, "title": "t",
                                                "content_hash": None if self.d.get("no_provenance") else v["content_hash"]}}
            return True, _body({"workflow_id": wid, "template_id": args["template_id"], "version": 1,
                                "content_hash": v["content_hash"]}), "201"
        if tool == "theprotocol_getBatchAgentBalances":
            did = args["agent_dids"][0]
            return True, _body({"balances": {did: {"balance": str(self.bal.get(did, Decimal(0)))}}}), "200"
        if tool == "theprotocol_deleteMyAgentByDev":
            self.deleted.append(args["agent_did"])
            return True, _body({"status": "deleted"}), "200"
        raise AssertionError(f"unexpected call {tool}")

    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_tegTreasuryReceive":
            self.bal["did:seller"] = Decimal(0)
            return True, _body({"ok": True}), "200"
        if tool != "theprotocol_adminRequest":
            raise AssertionError(f"unexpected admin call {tool}")
        ep, method = args["endpoint"], args["method"]
        if ep == "/api/v1/teg/treasury/fund-agent":
            did = args["body"]["target_agent_did"]
            self.bal[did] = self.bal.get(did, Decimal(0)) + Decimal(args["body"]["amount"])
            return True, _body({"status_code": 200, "response": {"ok": True}}), "200"
        if ep.startswith("/api/v1/workflows/") and method == "GET":
            w = self.workflows.get(ep.rsplit("/", 1)[1])
            if w is None:
                return True, _body({"status_code": 404, "response": {"detail": "no such workflow"}}), "200"
            return True, _body({"status_code": 200, "response": w}), "200"
        if ep.startswith("/api/v1/workflows/") and ep.endswith("/cancel") and method == "POST":
            w = self.workflows[ep.split("/")[4]]
            w["status"] = "cancelled"
            return True, _body({"status_code": 200, "response": {"status": "cancelled"}}), "200"
        if ep.startswith("/api/v1/workflow-templates/") and method == "PATCH":
            t = self.tpl[ep.rsplit("/", 1)[1]]
            t["visibility"] = args["body"]["visibility"]
            self.patched.append((ep, dict(args["body"]), args.get("developer_jwt")))
            return True, _body({"status_code": 200, "response": {"visibility": t["visibility"]}}), "200"
        raise AssertionError(f"unexpected admin request {method} {ep}")


class _Throwaways:
    closed = 0

    def __init__(self, *_a, **_k):
        pass

    async def developer(self, role, verify=True):
        return {"access_token": "dev:buyer", "developer_id": 77, "email": "b@example.com", "password": "pw"}

    async def agent(self, dev, label=""):
        return {"did": "did:buyer", "agent_jwt": "jwt:buyer", "owner_jwt": "dev:buyer"}

    async def close(self):
        _Throwaways.closed += 1


class _Bag:
    def __init__(self, w: _World, admin: bool = True):
        self.developer_jwt, self.developer_id = DEV, 1
        self.rpc_admin = w.admin if admin else None
        self.event_verifier = None


def _run(w: _World, admin: bool = True) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    asyncio.run(T.lifecycle_earn_workflow_templates(w.rpc, _parse, _Bag(w, admin), out))
    return out


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(T.ef, "Throwaways", _Throwaways)
    monkeypatch.setattr(T, "ephemeral_target", lambda: True)
    scheduled: List[str] = []

    async def seller(rpc, parse, bag, tag):
        return dict(SELLER)
    monkeypatch.setattr(T, "_bonded_seller", seller)

    async def schedule(rpc, bag, email, password, why):
        scheduled.append(email)
    monkeypatch.setattr(T.ef.lc(), "_schedule_own_deletion", schedule)
    _Throwaways.closed = 0
    return scheduled


def _red(out: Dict[str, dict], tool: str) -> bool:
    row = out.get(tool)
    return bool(row) and not row.get("healthy", True) and not row.get("skip_reason")


def _green(out: Dict[str, dict], tool: str) -> bool:
    row = out.get(tool)
    return bool(row) and bool(row.get("healthy")) and not row.get("skip_reason") and str(row.get("status_code", "")).startswith("2")


SIX = (T.CREATE, T.PUBLISH, T.GET, T.PURCHASE, T.FORK, T.INSTANTIATE)


def test_on_a_pair_all_six_tools_pass_on_their_read_back():
    w = _World()
    out = _run(w)
    for tool in SIX:
        assert _green(out, tool), (tool, out.get(tool))
    # the money moved and the seller was paid: the read-back of the purchase
    assert w.bal["did:buyer"] == Decimal(5) - Decimal(PRICE)      # the seller's balance went back to the treasury at the end (tegTreasuryReceive)
    assert "did:seller" in w.deleted
    assert ("wtpl_1", "did:buyer") in w.bought


def test_each_tool_row_is_the_tools_own_and_the_refusals_are_kept_beside_it():
    out = _run(_World())
    refusals = [k for k in out if k.startswith("refusal: ")]
    assert any("fork" in k.lower() for k in refusals) and any("publish" in k.lower() for k in refusals) and any("create" in k.lower() for k in refusals), refusals
    for k in refusals:
        assert out[k].get("healthy"), (k, out[k])


def test_the_draft_workflow_is_cancelled_and_nothing_of_the_run_is_left_open(_fakes):
    w = _World()
    _run(w)
    assert w.workflows and all(x["status"] == "cancelled" for x in w.workflows.values())
    assert _Throwaways.closed == 1
    assert _fakes == [SELLER["email"]]                 # the seller's developer is scheduled for its own deletion


def test_the_seller_is_a_different_developer_from_the_buyer():
    w = _World()
    _run(w)
    sellers = {a.get("agent_jwt") for t, a in w.calls if t == T.CREATE}
    buyers = {a.get("agent_jwt") for t, a in w.calls if t == T.PURCHASE}
    assert sellers == {"jwt:seller"} and buyers == {"jwt:buyer"}


# ── each defect turns its own row red ──────────────────────────────────────────────────────

@pytest.mark.parametrize("defect,tool", [
    ("create_not_stored", T.CREATE),            # the seller's own list does not name what create answered
    ("publish_not_current", T.PUBLISH),         # published, but the public read shows no current version
    ("wrong_price", T.GET),                     # the public read disagrees with what was created
    ("purchase_moves_nothing", T.PURCHASE),     # no money moved
    ("purchase_not_recorded", T.PURCHASE),      # the buyer still cannot read the files
    ("fork_no_parent", T.FORK),                 # the fork does not name its parent
    ("no_provenance", T.INSTANTIATE),           # the workflow draft lost the template's hash
])
def test_a_planted_defect_turns_its_own_row_red(defect, tool):
    out = _run(_World(**{defect: True}))
    assert _red(out, tool), (defect, out.get(tool))


# ── where it must not run ────────────────────────────────────────────────────────────────

def test_a_standing_target_says_why_and_writes_nothing(monkeypatch):
    monkeypatch.setattr(T, "ephemeral_target", lambda: False)
    w = _World()
    out = _run(w)
    written = [t for t, _a in w.calls if t in (T.CREATE, T.PUBLISH, T.PURCHASE, T.FORK, T.INSTANTIATE)]
    assert written == []
    for tool in (T.CREATE, T.PUBLISH, T.PURCHASE, T.FORK, T.INSTANTIATE):
        row = out[tool]
        assert row.get("skip_reason") and "torn down" in str(row.get("skip_reason")), (tool, row)
    assert _Throwaways.closed == 0


def test_a_standing_target_still_reads_an_existing_public_template_for_getWorkflowTemplate(monkeypatch):
    monkeypatch.setattr(T, "ephemeral_target", lambda: False)
    out = _run(_World())
    assert _green(out, T.GET), out.get(T.GET)


def test_a_standing_target_with_no_public_template_says_so_for_get(monkeypatch):
    monkeypatch.setattr(T, "ephemeral_target", lambda: False)
    out = _run(_World(no_public=True))
    assert out[T.GET].get("skip_reason") and "public" in str(out[T.GET].get("skip_reason")).lower()


@pytest.mark.parametrize("env", ["production", "", "Sandbox"])
def test_a_target_that_does_not_state_sandbox_is_never_touched(env):
    w = _World(env=env)
    out = _run(w)
    assert [t for t, _a in w.calls] == ["theprotocol_getPublicRegistryConfig"]
    for tool in SIX:
        assert out[tool].get("skip_reason"), tool


def test_without_an_admin_bridge_the_buyer_cannot_be_funded_and_it_is_said(monkeypatch):
    out = _run(_World(), admin=False)
    for tool in (T.PURCHASE, T.FORK, T.INSTANTIATE):
        assert out[tool].get("skip_reason"), (tool, out.get(tool))


def test_a_seller_that_could_not_be_made_leaves_the_five_unmeasured_with_the_reason(monkeypatch):
    async def none(rpc, parse, bag, tag):
        return {"why": "the bond config names no amount"}
    monkeypatch.setattr(T, "_bonded_seller", none)
    w = _World()
    out = _run(w)
    for tool in (T.CREATE, T.PUBLISH, T.PURCHASE, T.FORK, T.INSTANTIATE):
        assert out[tool].get("skip_reason") and "bond config" in str(out[tool].get("skip_reason")), tool
    assert not [t for t, _a in w.calls if t == T.CREATE]


def test_the_lifecycle_is_registered_where_the_sweep_reads_the_earned_lists():
    names = {x["name"] for x in earned_agent_public.LIFECYCLES} | {x["name"] for x in earned_admin_dev.LIFECYCLES}
    assert "earn_workflow_templates" in names


def test_the_runs_own_template_is_set_private_by_its_seller_after_the_public_read_and_before_the_seller_goes():
    """No route removes a template: the leg leaves no public litter by setting its own to private (the owner's PATCH, with the
    seller agent's token), after the public read of it that the leg measures, and before the seller's agent is deleted (a patch is
    an agent's write)."""
    w = _World()
    out = _run(w)
    assert _green(out, T.GET), out.get(T.GET)
    assert [(ep, body, jwt) for ep, body, jwt in w.patched] == [("/api/v1/workflow-templates/wtpl_1", {"visibility": "private"}, SELLER["agent_jwt"])]
    assert w.tpl["wtpl_1"]["visibility"] == "private"
    names = [t for t, _a in w.calls]
    assert names.index("theprotocol_getWorkflowTemplate") < max(i for i, (t, a) in enumerate(w.calls)
                                                                 if t == "theprotocol_adminRequest" and a.get("method") == "PATCH")
    assert max(i for i, (t, a) in enumerate(w.calls) if t == "theprotocol_adminRequest" and a.get("method") == "PATCH") < names.index("theprotocol_deleteMyAgentByDev")

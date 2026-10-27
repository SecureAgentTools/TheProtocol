"""§MCPTEST30 (2026-10-01) — lifecycle_owner_scoping against a fake registry.

A registry whose routes check ownership must leave every `owner_scoping:` row green; each route seeded with a missing
check (a read that answers another developer with the owner's object, a delete or revoke that acts for a stranger, a
contract read by a non-party agent) must turn exactly its row red with a BUG-FIND; an owner whose own call fails, a
read whose owner holds nothing distinctive, and a run that cannot mint the second developer are NOT MEASURED; and no
row may carry one of the owner's values.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _parse_rpc_result

OWNER, OTHER, SENT, SECOND = "owner-dev-jwt", "other-dev-jwt", "sentinel-agent-jwt", "second-agent-jwt"
SENTINEL_DID = "did:theprotocol:sentinel-0000-1111-2222"
NOW = datetime.now(timezone.utc).isoformat()
OLD = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
OWNER_EMAIL = "owner-runner@test.sandbox"
READS = {   # what the owner's own read answers, per tool
    "getSupportTicketDetail": {"id": "tkt-9001", "subject": "phase-3 ticket 1700000001", "status": "open",
                               "created_at": OLD},
    "getOrganization": {"id": "org-77", "name": "Phase3 Org 1700000002", "slug": "phase3-org-1700000002",
                        "member_count": 1, "updated_at": NOW},
    "listOrganizationMembers": [{"id": 1, "developer_email": OWNER_EMAIL, "role": "owner", "joined_at": OLD}],
    "listOrganizationTeams": [{"id": "team-5", "name": "Phase3 Team 1700000003"}],
    "getOrganizationTeam": {"id": "team-5", "name": "Phase3 Team 1700000003", "members": []},
    "listOrganizationAgents": {"agents": [{"did": SENTINEL_DID, "name": "Sentinel Agent 1700000004"}]},
    "listOrganizationInvitations": {"invitations": []},
    "getOrganizationCicdSummary": {"org_id": "org-77", "deployments": 0, "generated_at": NOW},
    "getBundleManifest": {"bundle_kind": "snapshot", "agent": {"did": SENTINEL_DID, "name": "Sentinel Agent 1700000004"}},
    "downloadBundle": {"content_base64": "UEsDBBQAAAAIAAAAIQBzZWNyZXQtYnVuZGxl", "size": 4096},
    "exportAgentDev": {"agent_did": SENTINEL_DID, "card": {"name": "Sentinel Agent 1700000004"}},
    "getMyCicdVersions": {"agent_did": SENTINEL_DID, "versions": [{"version_id": "ver-1700000005", "tag": "v1"}]},
    "getMyAgentLogs": {"agent_did": SENTINEL_DID, "logs": [{"line": "deployment 1700000006 started"}]},
}
FIXTURES = {"support_ticket_id": "tkt-9001", "organization_id": "org-77", "team_id": "team-5", "bundle_id": "bnd-42",
            "contract_v2_id": "ctr_abc123", "contract_v2_status": "active", "second_agent_jwt": SECOND}
CONTRACT = {"id": "ctr_abc123", "client_did": SENTINEL_DID, "provider_did": "did:theprotocol:provider-3333",
            "title": "phase-3 contract 1700000007", "status": "active"}


def _ok(obj):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}]}}, "200"


def _refuse(code, msg="Not found"):
    return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": f"Error: HTTP {code}: {msg}"}],
                                                         "isError": True}}, str(code)


class FakeRegistry:
    """Ownership modeled per object; `broken` names the tools whose ownership check is missing."""

    def __init__(self, broken=(), owner_fails=(), mint_fails=False):
        self.broken, self.owner_fails, self.mint_fails = set(broken), set(owner_fails), mint_fails
        self.webhooks, self.keys, self.n = {}, {}, 500
        self.teams, self.orgs = {}, {}
        self.org_members = {"org-77": {7}}
        self.bundle_vis, self.ratings = "private", 0
        self.calls = []

    async def mint(self, role):
        if self.mint_fails:
            return {"why": "POST /auth/register answered HTTP 503"}
        return {"access_token": OTHER, "email": f"mcp-throwaway-{role}@throwaway-pl.example.com", "password": "pw",
                "developer_id": "8"}

    async def rpc(self, tool, args, jwt="", timeout=20):
        name = tool.replace("theprotocol_", "")
        self.calls.append((name, jwt))
        if name == "getMyDeveloperProfile":
            return _ok({"id": 8 if jwt == OTHER else 7, "email": "x@example.com"})
        if name == "getMyAgentBundles":
            return _ok({"bundles": [{"id": "bnd-42", "visibility": self.bundle_vis, "rating_count": self.ratings}]
                        if jwt == OWNER else []})
        if name == "rateBundle":
            if jwt != OWNER and self.bundle_vis != "public" and "rateBundle" not in self.broken:
                return _refuse(404, "Bundle not found")
            self.ratings += 1
            return _ok({"ok": True})
        if name == "patchBundle":
            if jwt != OWNER and "patchBundle" not in self.broken:
                return _refuse(403, "Not the owner")
            self.bundle_vis = args["updates"].get("visibility", self.bundle_vis)
            return _ok({"id": args["bundle_id"]})
        if name in ("createOrganizationTeam", "createOrganization", "updateOrganizationTeam", "addTeamMember",
                    "deleteOrganizationTeam", "deleteOrganization") or (name == "getOrganizationTeam"
                                                                        and args.get("team_id") in self.teams):
            return self.team_rpc(name, args, jwt)
        if name in READS:
            if jwt == OWNER:
                return _refuse(500, "boom") if name in self.owner_fails else _ok(READS[name])
            return _ok(READS[name]) if name in self.broken else _refuse(404, "Not found")
        if name == "createWebhook":
            self.n += 1
            wid = f"wh-{self.n}"
            self.webhooks[wid] = {"id": wid, "url": args["url"], "description": args["description"], "deliveries": [],
                                  "events": list(args["events"]), "is_active": True, "owner": jwt,
                                  "secret": "whsec_" + "s" * 32}
            return _ok({k: v for k, v in self.webhooks[wid].items() if k != "owner"})
        if name in ("getWebhook", "getWebhookDeliveries", "updateWebhook", "deleteWebhook", "testWebhook"):
            w = self.webhooks.get(args.get("webhook_id"))
            if w is None:
                return _refuse(404, "Webhook not found")
            if jwt != w["owner"] and name not in self.broken:
                return _refuse(404, "Webhook not found")
            if name == "getWebhook":   # the real read: id, url, events, is_active, ... and no description
                return _ok({k: v for k, v in w.items() if k not in ("owner", "deliveries", "description", "secret")})
            if name == "getWebhookDeliveries":
                return _ok({"deliveries": w["deliveries"], "total": len(w["deliveries"])})
            if name == "testWebhook":
                w["deliveries"].append({"id": "dlv-1700000008", "url": w["url"], "status": "failed"})
                return _ok({"delivered": False})
            if name == "updateWebhook":
                for k in ("description", "events"):
                    if k in args:
                        w[k] = args[k]
                return _ok({"id": w["id"]})
            del self.webhooks[w["id"]]
            return _ok({"deleted": True})
        if name == "createApiKey":
            self.n += 1
            self.keys[self.n] = {"id": self.n, "is_revoked": False, "owner": jwt}
            return _ok({"plain_api_key": "avreg_" + "k" * 32, "api_key_info": {"id": self.n, "scopes": ["*"]}})
        if name == "revokeApiKey":
            k = self.keys.get(args.get("key_id"))
            if k is None or (jwt != k["owner"] and name not in self.broken):
                return _refuse(404, "API key not found")
            k["is_revoked"] = True
            return _ok({"revoked": True})
        if name == "getMyApiKeys":
            return _ok({"api_keys": [{"id": k["id"], "is_revoked": k["is_revoked"]} for k in self.keys.values()
                                     if k["owner"] == jwt]})
        if name in ("getContractV2", "getContractById"):
            if args.get("agent_jwt") == SENT:
                return _ok(CONTRACT)
            return _ok(CONTRACT) if name in self.broken else _refuse(403, "Not a party to this contract")
        if name == "requestAccountDeletion":
            return _ok({"scheduled": True})
        return _refuse(404, f"no fake for {name}")

    def team_rpc(self, name, args, jwt):
        """V0508's routes, modeled: the caller's authority is checked on args.org_id; a team BROKEN for the update
        writes first and checks after (a 404 that changed the team), one broken for addTeamMember never checks."""
        if name == "createOrganization":
            self.n += 1
            oid = f"org-{self.n}"
            self.orgs[oid] = jwt
            self.org_members[oid] = {8 if jwt == OTHER else 7}
            return _ok({"id": oid, "name": args["name"]})
        if name == "createOrganizationTeam":
            own = args["org_id"] == "org-77" and jwt == OWNER
            if not own and self.orgs.get(args["org_id"]) != jwt:
                return _refuse(403, "Insufficient permissions")
            self.n += 1
            tid = f"team-{self.n}"
            first = {7} if own else set()
            self.teams[tid] = {"id": tid, "organization_id": args["org_id"], "description": args.get("description"),
                               "member_count": len(first), "members": first}
            return _ok({"id": tid, "name": args["name"]})
        team = self.teams.get(args.get("team_id"))
        caller_admin_of = args.get("org_id") == "org-77" and jwt == OWNER or self.orgs.get(args.get("org_id")) == jwt
        if not caller_admin_of:
            return _refuse(403, "Insufficient permissions")
        if name == "getOrganizationTeam":
            if team is None or team["organization_id"] != args["org_id"]:
                return _refuse(404, "Team not found")
            return _ok({k: v for k, v in team.items() if k != "members"})
        if name == "deleteOrganizationTeam":
            self.teams.pop(args.get("team_id"), None)
            return _ok({"deleted": True})
        if name == "deleteOrganization":
            self.orgs.pop(args.get("org_id"), None)
            return _ok({"deleted": True})
        if team is None:
            return _refuse(404, "Team not found")
        same_org = team["organization_id"] == args["org_id"]
        if name == "updateOrganizationTeam":
            if same_org or "updateOrganizationTeam" in self.broken:
                team["description"] = args.get("description", team["description"])   # the write, then the check
            return _ok({"id": team["id"]}) if same_org else _refuse(404, "Team not found")
        if name == "addTeamMember":
            if not same_org and "addTeamMember" not in self.broken:
                return _refuse(404, "Team not found")
            # V0510: the developer must be a member of the organization the route checked (the PATH's)
            if (int(args["developer_id"]) not in self.org_members.get(args["org_id"], set())
                    and "addTeamMember-outsider" not in self.broken):
                return _refuse(400, "That developer is not a member of this organization")
            team["members"].add(int(args["developer_id"]))
            team["member_count"] = len(team["members"])
            return _ok({"message": "Member added to team successfully"})
        return _refuse(404, "no fake")


class Bag:
    def __init__(self, fake, **extra):
        self.developer_jwt, self.sentinel_jwt, self.sentinel_did = OWNER, SENT, SENTINEL_DID
        self.developer_id = 7
        self.flow_values = {**FIXTURES, **extra}
        self.mint_throwaway, self.dev_login = fake.mint, None

    def get(self, key, default=None):
        return self.flow_values[key] if key in self.flow_values else getattr(self, key, default)


def _run(fake, **extra):
    outcomes = {}
    asyncio.run(L.lifecycle_owner_scoping(fake.rpc, _parse_rpc_result, Bag(fake, **extra), outcomes))
    return outcomes


ALL = [t.replace("theprotocol_", "") for t, _ in L.OWNER_SCOPED_READS] + [
    "updateWebhook (another developer's)", "deleteWebhook (another developer's)",
    "revokeApiKey (another developer's)", "getContractV2 (a non-party agent)", "getContractById (a non-party agent)",
    *L._TEAM_CHECKS, L._BUNDLE_CHECK, L._RATE_CHECK]


def _state(outcomes):
    out = {}
    for k, r in outcomes.items():
        assert k.startswith(L._OWN)
        out[k[len(L._OWN):]] = "ok" if r["healthy"] else ("skip" if r["skip_reason"] else "red")
    return out


def test_a_registry_that_checks_ownership_leaves_every_row_green():
    fake = FakeRegistry()
    st = _state(_run(fake))
    assert set(st) == set(ALL)
    # the invitations list is empty for the owner too: a refusal is still a measured answer, so it passes
    assert all(v == "ok" for v in st.values()), st
    assert not fake.webhooks and all(k["is_revoked"] for k in fake.keys.values()), "cleanup removes what it made"
    assert not fake.teams and not fake.orgs, "the team and the other developer's organization are removed too"
    assert fake.bundle_vis == "private" and fake.ratings == 0


@pytest.mark.parametrize("broken,row", [
    ("getSupportTicketDetail", "getSupportTicketDetail"),
    ("listOrganizationMembers", "listOrganizationMembers"),
    ("getBundleManifest", "getBundleManifest"),
    ("exportAgentDev", "exportAgentDev"),
    ("getWebhook", "getWebhook"),
    ("getWebhookDeliveries", "getWebhookDeliveries"),
    ("updateWebhook", "updateWebhook (another developer's)"),
    ("deleteWebhook", "deleteWebhook (another developer's)"),
    ("revokeApiKey", "revokeApiKey (another developer's)"),
    ("getContractV2", "getContractV2 (a non-party agent)"),
    ("getContractById", "getContractById (a non-party agent)"),
    ("updateOrganizationTeam", "updateOrganizationTeam (another org's admin)"),
    ("addTeamMember", "addTeamMember (another org's admin)"),
    ("patchBundle", "patchBundle (another developer's)"),
    ("rateBundle", "rateBundle (another developer's private bundle)"),
    ("addTeamMember-outsider", "addTeamMember (a developer outside the organization)"),
])
def test_each_missing_ownership_check_reddens_exactly_its_row(broken, row):
    outcomes = _run(FakeRegistry(broken={broken}))
    st = _state(outcomes)
    reds = sorted(k for k, v in st.items() if v == "red")
    assert reds == [row], st
    assert outcomes[L._OWN + row]["fail_reason"].startswith("BUG-FIND: owner scoping")


def test_no_row_carries_an_owner_value():
    outcomes = _run(FakeRegistry(broken={"getSupportTicketDetail", "getBundleManifest", "getWebhook",
                                         "listOrganizationMembers", "getContractV2"}))
    blob = json.dumps(outcomes, default=str)
    for secret in ("phase-3 ticket 1700000001", OWNER_EMAIL, "Sentinel Agent 1700000004", "whsec_", "avreg_",
                   "phase-3 contract 1700000007", "UEsDBBQAAAAIAAAAIQBzZWNyZXQtYnVuZGxl", "owner-scoping-"):
        assert secret not in blob, secret


def test_an_owner_whose_own_call_fails_proves_nothing():
    st = _state(_run(FakeRegistry(owner_fails={"getOrganization"})))
    assert st["getOrganization"] == "skip" and st["getOrganizationTeam"] == "ok"


def test_an_answer_to_a_stranger_with_nothing_to_compare_is_not_measured():
    # listOrganizationInvitations: the owner's list is empty; a stranger answered 200 cannot be judged from it
    st = _state(_run(FakeRegistry(broken={"listOrganizationInvitations"})))
    assert st["listOrganizationInvitations"] == "skip"


def test_no_second_developer_means_every_row_not_measured():
    outcomes = _run(FakeRegistry(mint_fails=True))
    assert set(_state(outcomes).values()) == {"skip"} and len(outcomes) == len(ALL)
    assert "HTTP 503" in outcomes[L._OWN + "getOrganization"]["skip_reason"]


def test_missing_fixtures_and_an_open_offer_are_named_skips():
    st = _state(_run(FakeRegistry(), bundle_id=None, contract_v2_status="offered"))
    assert st["getBundleManifest"] == "skip" and st["downloadBundle"] == "skip" and st["patchBundle (another developer's)"] == "skip"
    assert st["getContractV2 (a non-party agent)"] == "skip" and st["getContractById (a non-party agent)"] == "skip"


def test_owner_values_carried_ignores_the_question_the_clock_and_enum_words():
    owner = {"id": "org-77", "name": "Phase3 Org 1700000002", "status": "active", "generated_at": NOW, "n": 5}
    echo = {"id": "org-77", "status": "active", "generated_at": NOW, "n": 5}
    assert L.owner_values_carried(owner, echo, ["org-77"]) == (0, 1)
    assert L.owner_values_carried(owner, {"name": "Phase3 Org 1700000002"}, ["org-77"]) == (1, 1)
    assert L.owner_values_carried({"created_at": OLD}, {"created_at": OLD}, []) == (1, 1), "an old timestamp is the object's"


def test_the_verdict_on_a_server_error_is_red_not_a_refusal():
    healthy, sentence, ev = L.judge_other_principal("x", "someone", {"a": "owner value 12345"}, False,
                                                    {"_text": "Error: HTTP 500: boom"}, "500", [])
    assert healthy is False and "not refused cleanly" in sentence and ev["other_status"] == 500


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

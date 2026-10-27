"""§TWOAGENT (V0437, 2026-09-23) — one cross-frame contract rail, and on it every party acts as itself.

Found while building the replica's milestone notice (V0434): the legacy contracts surface carried a second cross-frame
rail beside the contracts v2 courier, and a weaker one.
  * `POST /contracts/{id}/accept-federated` took the provider from the BODY under a peer registry's identity: any
    federated peer could accept any open offer in any agent's name, escrowing the client's funds, with no bond or
    enforcement gate and no check that the peer is that agent's home. `submit-federated` did not ask who was delivering.
  * `POST /contracts/cross-registry/proxy` dialled those routes in the name of whichever `upgrader_agent_did` the caller
    supplied, which need not have been the caller.
  * The MCP tools `acceptContractFederated` / `submitContractWorkFederated` posted an AGENT token to the peer-only routes,
    so they were refused for every caller, always; on EU and ASIA the legacy surface is not even mounted.
The v2 rail V0428+ built answers the same need correctly: the provider acts on its own registry, as itself; that
registry gates it and couriers the command to the contract's home, where the gates run again.

Now the two peer routes answer 410 to everyone and name the v2 rail; the proxy and the three tools are the v2 provider
rail, acting as the caller. RED on 7241c198: all but the control.
"""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

ME = "did:theprotocol:asia.theprotocol.cloud:5b0c3a1e-0000-4000-8000-000000000020"
OTHER = "did:theprotocol:eu.theprotocol.cloud:5b0c3a1e-0000-4000-8000-000000000021"
CID = "ctr_58f55ded04fbd42df5ad4882"


class _Agent:
    did = ME


# ── the peer routes are retired, loudly ─────────────────────────────────────

@pytest.mark.parametrize("name, verb, path", [
    ("accept_contract_federated", "accept", "/api/v1/contracts/v2/{cid}/accept"),
    ("submit_contract_work_federated", "deliver on", "/api/v1/contracts/v2/{cid}/milestones/{seq}/submit"),
])
async def test_the_peer_routes_answer_410_and_name_the_v2_rail(name, verb, path):
    import inspect
    from agentvault_registry.routers import contracts
    fn = getattr(contracts, name)
    assert list(inspect.signature(fn).parameters) == ["contract_id"], \
        "no identity is asked for: the answer is the same for every caller"
    with pytest.raises(HTTPException) as e:
        await fn(CID)
    assert e.value.status_code == 410
    d = str(e.value.detail)
    assert f"can no longer {verb} a contract in an agent's name" in d and path in d and "/federation/contract-command" in d


# ── the proxy is the v2 provider rail, as the caller ─────────────────────────

@pytest.fixture
def v2calls(monkeypatch):
    from agentvault_registry.routers import contracts_v2 as v2
    calls = []

    async def accept(cid, request, agent=None, db=None):
        calls.append(("accept", cid, agent.did))
        return {"contract_id": cid, "relayed_to": "EU", "action": "offer.accept"}

    async def submit(cid, seq, body, request=None, agent=None, db=None):   # D6-274: the route takes the request
        calls.append(("submit", cid, seq, body.deliverable, agent.did))
        return {"ok": True, "contract_id": cid, "seq": seq, "status": "submitted"}

    monkeypatch.setattr(v2, "accept_contract_v2", accept)
    monkeypatch.setattr(v2, "submit_milestone", submit)
    return calls


def _proxy(**kw):
    from agentvault_registry.routers.contracts import CrossRegistryContractProxy
    return CrossRegistryContractProxy(contract_id=CID, **kw)


async def test_the_proxy_accepts_as_the_caller_through_v2(v2calls):
    from agentvault_registry.routers.contracts import proxy_contract_action
    out = await proxy_contract_action(proxy_data=_proxy(action="accept", upgrader_agent_did=ME), request=None, db=None,
                                      current_agent=_Agent())
    assert v2calls == [("accept", CID, ME)] and out["relayed_to"] == "EU"


async def test_the_proxy_needs_no_target_url_any_more(v2calls):
    """The contract's home is the replica's; a caller that names none is served, and the answer says where it went."""
    from agentvault_registry.routers.contracts import proxy_contract_action
    await proxy_contract_action(proxy_data=_proxy(action="accept"), request=None, db=None, current_agent=_Agent())
    assert v2calls == [("accept", CID, ME)]


async def test_the_proxy_refuses_to_act_in_another_agents_name(v2calls):
    from agentvault_registry.routers.contracts import proxy_contract_action
    with pytest.raises(HTTPException) as e:
        await proxy_contract_action(proxy_data=_proxy(action="accept", upgrader_agent_did=OTHER), request=None, db=None,
                                    current_agent=_Agent())
    assert e.value.status_code == 403 and "You act as yourself" in str(e.value.detail)
    assert v2calls == [], "nothing was attempted"


async def test_the_proxy_delivers_milestone_one_by_default(v2calls):
    from agentvault_registry.routers.contracts import proxy_contract_action
    await proxy_contract_action(proxy_data=_proxy(action="submit", pr_url="https://git.example/pr/7"), request=None,
                                db=None, current_agent=_Agent())
    await proxy_contract_action(proxy_data=_proxy(action="submit", pr_url="https://git.example/pr/8", seq=2),
                                request=None, db=None, current_agent=_Agent())
    assert v2calls == [("submit", CID, 1, {"pr_url": "https://git.example/pr/7"}, ME),
                       ("submit", CID, 2, {"pr_url": "https://git.example/pr/8"}, ME)]


async def test_control_an_unknown_action_is_still_refused():
    """Passes on both trees: the same call on each (the old route took no `request`)."""
    import inspect
    from agentvault_registry.routers.contracts import proxy_contract_action
    kw = {"proxy_data": _proxy(action="cancel", target_registry_url="https://x.invalid"), "db": None,
          "current_agent": _Agent()}
    if "request" in inspect.signature(proxy_contract_action).parameters:
        kw["request"] = None
    with pytest.raises(HTTPException) as e:
        await proxy_contract_action(**kw)
    assert e.value.status_code == 400


# ── the MCP tools are the same rail ──────────────────────────────────────────

@pytest.fixture
def posts(monkeypatch):
    from agentvault_registry.mcp import tools_agent as ta
    seen = []

    async def fake_post(auth, path, json_body=None, params=None, op_name="", refusal_reason=False):
        seen.append((path, json_body, op_name))
        return {"ok": True}

    monkeypatch.setattr(ta, "_agent_post", fake_post)
    return seen


def _auth():
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    return MCPAuthContext(auth_type="agent", agent_did=ME, raw_token="t")


async def test_accept_federated_posts_the_v2_accept_as_the_caller(posts):
    from agentvault_registry.mcp.tools_agent import accept_contract_federated
    await accept_contract_federated(_auth(), CID, ME, "https://ignored.invalid")
    await accept_contract_federated(_auth(), CID)
    assert [p[0] for p in posts] == [f"/api/v1/contracts/v2/{CID}/accept"] * 2


async def test_accept_federated_refuses_another_agents_did_before_any_call(posts):
    from agentvault_registry.mcp.tools_agent import accept_contract_federated
    out = await accept_contract_federated(_auth(), CID, OTHER, "https://x.invalid")
    assert "you act as yourself" in out["error"] and posts == []


async def test_submit_federated_delivers_a_milestone_as_the_caller(posts):
    from agentvault_registry.mcp.tools_agent import submit_contract_work_federated
    await submit_contract_work_federated(_auth(), CID, "https://git.example/pr/7", "https://ignored.invalid")
    await submit_contract_work_federated(_auth(), CID, "https://git.example/pr/8", seq=3)
    assert posts[0][:2] == (f"/api/v1/contracts/v2/{CID}/milestones/1/submit", {"deliverable": {"pr_url": "https://git.example/pr/7"}})
    assert posts[1][0] == f"/api/v1/contracts/v2/{CID}/milestones/3/submit"


async def test_the_proxy_tool_routes_both_actions_and_refuses_the_rest(posts):
    from agentvault_registry.mcp.tools_agent import cross_registry_contract_proxy
    await cross_registry_contract_proxy(_auth(), {"contract_id": CID, "action": "accept"})
    await cross_registry_contract_proxy(_auth(), {"contract_id": CID, "action": "submit", "pr_url": "https://p/1"})
    assert [p[0] for p in posts] == [f"/api/v1/contracts/v2/{CID}/accept", f"/api/v1/contracts/v2/{CID}/milestones/1/submit"]
    assert "you act as yourself" in (await cross_registry_contract_proxy(
        _auth(), {"contract_id": CID, "action": "accept", "upgrader_agent_did": OTHER}))["error"]
    assert "needs contract_id and action" in (await cross_registry_contract_proxy(_auth(), {"phase5": True}))["error"]
    assert len(posts) == 2


def test_the_api_tester_no_longer_lists_the_retired_routes():
    from agentvault_registry.api_tests import base, endpoints_registry
    import inspect
    src = inspect.getsource(endpoints_registry) + inspect.getsource(base)
    live = [ln for ln in src.splitlines() if ("accept-federated" in ln or "submit-federated" in ln)
            and not ln.lstrip().startswith("#")]
    assert live == [], live


# ── the replica reads say what the home has paid ─────────────────────────────

class _Res:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _ReplicaDB:
    """Answers the three statements the replica detail read makes: no home row, the replica row, the full replica."""
    def __init__(self, released):
        self.sql = []
        self.row = {"cid": CID, "home_registry": "EU", "client_did": OTHER, "provider_did": ME, "title": "t",
                    "currency": "ECU", "total_amount": 2, "status": "in_progress", "seq": 9, "stale": False,
                    "last_synced_at": None, "updated_at": None, "released_milestones": released}

    async def execute(self, stmt, params=None):
        q = " ".join(str(stmt).split())
        self.sql.append(q)
        if q.startswith("SELECT 1 FROM contracts"):
            return _Res([])
        if "released_milestones" in q:
            return _Res([self.row])
        return _Res([{k: self.row[k] for k in ("cid", "home_registry", "client_did", "provider_did", "status", "seq")}])


@pytest.mark.parametrize("released", [[1], None])
async def test_the_replica_detail_names_the_paid_milestones(monkeypatch, released):
    from agentvault_registry.routers import contracts_v2 as v2
    monkeypatch.setattr(v2, "contracts_v2_enabled", lambda: True)
    db = _ReplicaDB(released)
    out = await v2.get_contract_v2(CID, actor={"kind": "agent", "agent_did": ME}, db=db)
    assert out["replica"] is True and out["released_milestones"] == released
    assert any("payload->'released_milestones'" in q for q in db.sql), db.sql

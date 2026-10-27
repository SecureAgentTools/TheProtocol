"""D6-686 (2026-10-16): POST /api/v1/forge/evals/run checks the TARGET, as the design notes say.

agent_authz.py and services/org_authz.py: forge.evolve_for_org is org consent, honored only through an org:
delegation grant ("a role, incl. legacy-full, never suffices"), for the org's own lineage. The route asked the
agent's resolved permissions instead (legacy-full carries every permission) and never related them to the target,
so a legacy-full agent could run eval suites against any agent on the registry. Allowed now: the caller's own
developer owns the target, or the target and the caller share an organization that granted the caller
forge.evolve_for_org (a live grant).

Through FastAPI on the real router; the agent dependency, the database (a double that answers the three reads by
their SQL) and the eval runner are the doubles. The base's permission resolver is stubbed to what a legacy-full
agent resolves to, which is the population the defect is about.
RED on 14520b9f: the stranger, the unknown target, the org without a grant and the other org's target (the base
runs the suite for all four).
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import agent_authz
from agentvault_registry.background_tasks import eval_runner
from agentvault_registry.database import get_db
from agentvault_registry.routers import forge
from agentvault_registry.security import get_current_agent

CALLER = types.SimpleNamespace(did="did:theprotocol:caller", creator_developer_id=7, organization_id="org-a",
                               status="active")
AGENTS = {  # did -> (creator_developer_id, organization_id)
    "did:theprotocol:caller": (7, "org-a"),
    "did:theprotocol:sibling": (7, None),
    "did:theprotocol:stranger": (99, None),
    "did:theprotocol:colleague": (55, "org-a"),
    "did:theprotocol:outsider": (56, "org-b"),
}
ORGS = {"org-a": "acme", "org-b": "other"}


class _Res:
    def __init__(self, first=None, scalar=None):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar


class _Db:
    def __init__(self, grants):
        self.grants = grants  # set of (delegate_did, principal_ref)

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "FROM agents WHERE did" in sql:
            return _Res(first=AGENTS.get(params["d"]))
        if "FROM organizations" in sql:
            return _Res(scalar=ORGS.get(params["o"]))
        if "FROM agent_delegation_grants" in sql:
            hit = any((params["d"], ref) in self.grants for ref in params["refs"])
            return _Res(first=(1,) if hit else None)
        raise AssertionError(f"unexpected read: {sql}")


@pytest.fixture
def runs(monkeypatch):
    monkeypatch.setenv("FORGE_ENABLED", "true")
    monkeypatch.setenv("EVALS_AGENT_TRIGGER_ENABLED", "true")
    monkeypatch.setenv("JURISDICTION_MODE", "off")
    monkeypatch.setattr(eval_runner, "EVALS_ENABLED", True)
    seen = []

    async def run_suite_once_for(suite_id, did):
        seen.append(did)
        return "run-1"

    monkeypatch.setattr(eval_runner, "run_suite_once_for", run_suite_once_for)

    async def legacy_full(db, did, act_principal=None):  # what the base asked: a legacy-full agent's set
        return set(agent_authz.ALL_PERMISSIONS)

    monkeypatch.setattr(agent_authz, "resolve_agent_permissions", legacy_full)
    return seen


def _post(body, grants=()):
    app = FastAPI()
    app.include_router(forge.router, prefix="/api/v1")
    app.dependency_overrides[get_current_agent] = lambda: CALLER

    async def _db():
        yield _Db(set(grants))

    app.dependency_overrides[get_db] = _db
    return TestClient(app).post("/api/v1/forge/evals/run", json=body)


def test_self_eval_runs(runs):
    r = _post({"suite_id": 1})
    assert r.status_code == 200, r.text
    assert runs == ["did:theprotocol:caller"]


def test_an_agent_of_the_same_developer_runs(runs):
    r = _post({"suite_id": 1, "target_did": "did:theprotocol:sibling"})
    assert r.status_code == 200, r.text
    assert runs == ["did:theprotocol:sibling"]


def test_a_strangers_agent_is_refused_even_for_legacy_full(runs):
    r = _post({"suite_id": 1, "target_did": "did:theprotocol:stranger"})
    assert r.status_code == 403, (r.status_code, r.text)
    assert runs == []


def test_an_unknown_target_is_refused(runs):
    r = _post({"suite_id": 1, "target_did": "did:theprotocol:nobody"})
    assert r.status_code == 403, (r.status_code, r.text)
    assert runs == []


def test_an_org_colleague_needs_the_orgs_grant(runs):
    r = _post({"suite_id": 1, "target_did": "did:theprotocol:colleague"})
    assert r.status_code == 403, (r.status_code, r.text)
    assert runs == []


def test_an_org_colleague_with_the_orgs_grant_runs(runs):
    for ref in ("org:acme", "org:org-a"):  # grants name the org by slug (grant_org_slice) or by id
        runs.clear()
        r = _post({"suite_id": 1, "target_did": "did:theprotocol:colleague"},
                  grants={("did:theprotocol:caller", ref)})
        assert r.status_code == 200, (ref, r.text)
        assert runs == ["did:theprotocol:colleague"]


def test_a_grant_does_not_reach_another_orgs_agent(runs):
    r = _post({"suite_id": 1, "target_did": "did:theprotocol:outsider"},
              grants={("did:theprotocol:caller", "org:acme"), ("did:theprotocol:caller", "org:other")})
    assert r.status_code == 403, (r.status_code, r.text)
    assert runs == []

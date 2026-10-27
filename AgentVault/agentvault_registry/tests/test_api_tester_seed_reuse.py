"""§SUITES1018 batch 7 (2026-10-19): the api-tester seeds a fixture only when none of its own is there to use.

APITestBase._populate_dynamic_ids runs once per tester instance, and the router makes several instances per row (each
fixture resolver builds its own). Each population SEEDED: a one-unit transfer, a record-offense against the
counterparty, a one-unit TEG stake locked for 30 days, and a CI/CD pipeline and version, whose lists it could not read
(they wrap with "pipelines" / "versions", which _extract_first_id did not know). Measured on sbx-alpha for 2026-10-18
alone (three sweeps): 3,255 fixture transfers, 3,303 one-unit stakes locked for 30 days, 2,989 pending fixture
offenses, 2,929 pipelines. None of those objects is consumed by more than the row that measures it: a transfer is only
read (the reputation-signal row makes its own), the unstake row meets the lock on any locked stake, the approve and
reject rows take one pending offense each. So the population now reads first and seeds only when nothing of its own is
there, and the agent's REAL stake is never taken for the fixture.

RED on 1b6c461b (batch 6c): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from agentvault_registry.api_tests import base as B

AG = "did:theprotocol:sweep-agent"
AG2 = "did:theprotocol:sweep-counterparty"
OFFENSE_REF = "api-tester fixture offense"


class _Target:
    """The registry the tester sweeps, reduced to the lists and seeds the population touches; every other route 404s."""

    def __init__(self, monkeypatch, *, txs=(), pending=(), stakes=(), pipelines=(), versions=(), deployments=()):
        self.txs = [dict(t) for t in txs]
        self.pending = [dict(a) for a in pending]
        self.stakes = [dict(s) for s in stakes]
        self.cicd = {"pipelines": [dict(p) for p in pipelines], "versions": [dict(v) for v in versions],
                     "deployments": [dict(d) for d in deployments]}
        self.posts = []
        self._n = 0
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _id(self, prefix):
        self._n += 1
        return f"{prefix}-new-{self._n}"

    def posted(self, pattern):
        return [p for p in self.posts if re.fullmatch(pattern, p)]

    def _handle(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        if m == "GET":
            if path == "/api/v1/agents/me":
                return httpx.Response(200, json={"did": AG})
            if path == "/api/v1/developers/me/agents":
                return httpx.Response(200, json={"agents": [{"did": AG}, {"did": AG2}]})
            if path == "/api/v1/teg/transactions":
                return httpx.Response(200, json={"transactions": self.txs})
            if path == "/api/v1/admin/enforcement/pending":
                return httpx.Response(200, json={"items": self.pending, "page": 1, "per_page": 100})
            if path == f"/api/v1/teg/staking/balance/{AG}":
                return httpx.Response(200, json={"agent_id": AG, "staked_balance": "0", "locked_balance": "0",
                                                 "available_to_unstake": "0", "active_stakes": self.stakes})
            for kind in self.cicd:
                if path == f"/api/v1/agents/{AG}/{kind}":
                    return httpx.Response(200, json={kind: self.cicd[kind]})
            return httpx.Response(404, json={"detail": "Not Found"})
        if m == "POST":
            self.posts.append(path)
            if path == "/api/v1/teg/transfer":
                tid = self._id("tx")
                self.txs.insert(0, {"transaction_id": tid, "transaction_type": "transfer"})
                return httpx.Response(200, json={"transaction_id": tid})
            if path == f"/api/v1/admin/enforcement/agents/{AG2}/record-offense":
                aid = self._id("act")
                self.pending.insert(0, {"id": aid, "agent_did": AG2, "trigger_reference": OFFENSE_REF})
                return httpx.Response(200, json={"action_id": aid, "action_type": "warn", "status": "pending_approval"})
            if path == "/api/v1/teg/staking/stake":
                sid = self._id("stk")
                self.stakes.append({"stake_id": sid, "amount": "1", "lock_period_days": 30, "is_locked": True})
                return httpx.Response(200, json={"stake_id": sid})
            for kind in self.cicd:
                if path == f"/api/v1/agents/{AG}/{kind}":
                    oid = self._id(kind[:-1])
                    self.cicd[kind].insert(0, {"id": oid})
                    return httpx.Response(201, json={"id": oid})
            return httpx.Response(404, json={"detail": "Not Found"})
        return httpx.Response(404, json={"detail": "Not Found"})


def _populate():
    t = B.APITestBase(base_url="http://registry-test:8000")
    asyncio.run(t._populate_dynamic_ids(developer_token="dev-token", agent_token="agent-token"))
    return t._dynamic_ids


# ── the transfer ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_red_an_existing_transfer_of_the_agent_is_used_and_none_is_seeded(monkeypatch):
    f = _Target(monkeypatch, txs=[{"transaction_id": "tx-old", "transaction_type": "transfer"}])
    ids = _populate()
    assert f.posted("/api/v1/teg/transfer") == []
    assert ids["transaction_id"] == "tx-old"


def test_control_an_agent_with_no_transfer_gets_one_seeded(monkeypatch):
    f = _Target(monkeypatch, txs=[{"transaction_id": "stk-tx", "transaction_type": "stake"}])
    ids = _populate()
    assert len(f.posted("/api/v1/teg/transfer")) == 1
    assert ids["transaction_id"].startswith("tx-new-")


# ── the offense ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_red_a_pending_fixture_offense_against_the_counterparty_is_used(monkeypatch):
    f = _Target(monkeypatch, pending=[{"id": "act-old", "agent_did": AG2, "trigger_reference": OFFENSE_REF}])
    ids = _populate()
    assert f.posted(r"/api/v1/admin/enforcement/agents/.*/record-offense") == []
    assert ids["action_id"] == "act-old"


def test_control_another_agents_offense_or_a_real_one_is_never_taken(monkeypatch):
    f = _Target(monkeypatch, pending=[{"id": "other-agent", "agent_did": "did:theprotocol:someone", "trigger_reference": OFFENSE_REF},
                                      {"id": "real-dispute", "agent_did": AG2, "trigger_reference": "dispute:213"}])
    ids = _populate()
    assert len(f.posted(r"/api/v1/admin/enforcement/agents/.*/record-offense")) == 1
    assert ids["action_id"].startswith("act-new-")


# ── the stake ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_red_a_locked_fixture_stake_of_the_agent_is_used(monkeypatch):
    f = _Target(monkeypatch, stakes=[{"stake_id": "stk-old", "amount": "1.000000000000000000", "lock_period_days": 30,
                                      "is_locked": True}])
    ids = _populate()
    assert f.posted("/api/v1/teg/staking/stake") == []
    assert ids["teg_stake_id"] == "stk-old"


def test_control_the_agents_real_stake_and_an_unlocked_one_are_never_taken(monkeypatch):
    # the real stake carries the agent's voting power, and the unstake row on an unlocked stake would release it
    f = _Target(monkeypatch, stakes=[{"stake_id": "real", "amount": "10000", "lock_period_days": 30, "is_locked": True},
                                     {"stake_id": "unlocked", "amount": "1", "lock_period_days": 30, "is_locked": False},
                                     {"stake_id": "short", "amount": "1", "lock_period_days": 7, "is_locked": True}])
    ids = _populate()
    assert len(f.posted("/api/v1/teg/staking/stake")) == 1
    assert ids["teg_stake_id"].startswith("stk-new-")


# ── the CI/CD chain ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_red_the_agents_pipeline_version_and_deployment_are_used(monkeypatch):
    f = _Target(monkeypatch, pipelines=[{"id": "pl-old"}], versions=[{"id": "v-old"}], deployments=[{"id": "d-old"}])
    ids = _populate()
    assert f.posted(rf"/api/v1/agents/{re.escape(AG)}/(pipelines|versions|deployments)") == []
    assert (ids["pipeline_id"], ids["version_id"], ids["deployment_id"]) == ("pl-old", "v-old", "d-old")


def test_control_an_agent_with_no_cicd_objects_gets_one_of_each(monkeypatch):
    f = _Target(monkeypatch)
    ids = _populate()
    for kind in ("pipelines", "versions", "deployments"):
        assert len(f.posted(f"/api/v1/agents/{re.escape(AG)}/{kind}")) == 1, kind
    assert ids["pipeline_id"].startswith("pipeline-new-") and ids["version_id"].startswith("version-new-")
    assert ids["deployment_id"].startswith("deployment-new-")


def test_red_the_cicd_list_wrappers_are_read():
    for kind in ("pipelines", "versions", "deployments"):
        assert B.APITestBase._extract_first_id({kind: [{"id": "x1"}]}, id_fields=("id",)) == ("x1", {"id": "x1"}), kind


def test_control_a_wrapper_that_is_no_list_still_reads_as_empty():
    # the org CI/CD summary carries {"pipelines": {"total": ...}}: a count, not a list of rows
    assert B.APITestBase._extract_first_id({"pipelines": {"total": 3}}, id_fields=("id",)) == (None, None)


# ── a sweep: the router makes a fresh tester instance per row ────────────────────────────────────────────────────────

def test_red_a_sweep_of_many_instances_seeds_each_fixture_once(monkeypatch):
    f = _Target(monkeypatch)
    for _ in range(6):
        _populate()
    counts = {
        "transfer": len(f.posted("/api/v1/teg/transfer")),
        "offense": len(f.posted(r"/api/v1/admin/enforcement/agents/.*/record-offense")),
        "stake": len(f.posted("/api/v1/teg/staking/stake")),
        "pipeline": len(f.posted(f"/api/v1/agents/{re.escape(AG)}/pipelines")),
        "version": len(f.posted(f"/api/v1/agents/{re.escape(AG)}/versions")),
        "deployment": len(f.posted(f"/api/v1/agents/{re.escape(AG)}/deployments")),
    }
    assert counts == {k: 1 for k in counts}, counts


def test_control_a_consumed_offense_is_recorded_again_for_the_next_instance(monkeypatch):
    # the approve row executes the pending action it is given: the next instance finds none pending and records one
    f = _Target(monkeypatch)
    first = _populate()["action_id"]
    f.pending = [a for a in f.pending if a["id"] != first]
    second = _populate()["action_id"]
    assert second != first and len(f.posted(r"/api/v1/admin/enforcement/agents/.*/record-offense")) == 2

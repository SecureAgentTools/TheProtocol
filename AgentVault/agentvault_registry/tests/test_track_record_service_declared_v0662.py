"""V0662 console polish, item 7 (order gwo_0aa7b875cbf65b6347f5f775): the track record tells "no live service declared"
apart from "service not answering".

The panel showed the health checker's raw outcome ("endpoint probe: unreachable") for every agent it had probed, and
the checker probes whatever URL the card names, placeholders included: a spawned child's sub-<uuid>.agents.local, a
probe agent's made-up host. Those agents declared no live service; "unreachable" read as a service that is down. The
liveness block now says whether the card declares one (`service_declared`): a card URL (url, then
supportedInterfaces[0..1].url, the order the checker reads) whose host is not loopback and not a special-use TLD
(background_tasks/agent_card_pullsync.reserved_tld_of, the rule create_agent and the pull-sync use).
Red on f569f6a6e: no service_declared, and services.track_record.declares_live_service does not exist.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.routers import track_record as TR
from agentvault_registry.services import track_record as svc

DID = "did:theprotocol:eu.test:worker-agent"


def test_the_rule_reads_the_card_like_the_checker():
    assert svc.declares_live_service({"url": "https://agent.example.org/a2a"}) is True
    assert svc.declares_live_service({"supportedInterfaces": [{"url": "https://svc.theprotocol.cloud/a2a"}]}) is True
    # the checker's order: url first, then the interfaces; loopback is skipped like the checker skips it
    assert svc.declares_live_service({"url": "http://localhost:9000", "supportedInterfaces": [{"url": "https://real.host/a2a"}]}) is True
    for placeholder in ("https://sub-1234.agents.local", "https://x.invalid/a", "https://probe.test", "http://127.0.0.1:8000"):
        assert svc.declares_live_service({"url": placeholder}) is False, placeholder
    for nothing in (None, {}, {"url": ""}, {"supportedInterfaces": []}, {"url": None}, "not a card"):
        assert svc.declares_live_service(nothing) is False, nothing


class _R:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row

    def scalar(self):
        return self._row[0] if self._row else None


class _Db:
    def __init__(self, liveness_row):
        self.row, self.sql = liveness_row, []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append(sql)
        if "last_health" in sql:
            return _R(self.row)
        return _R((1,))


def _get(monkeypatch, row):
    async def _summaries(_db, dids):
        return {}

    async def _detail(_db, _did, limit=5):
        return []
    monkeypatch.setattr(svc, "track_record_summaries", _summaries)
    monkeypatch.setattr(svc, "track_record_detail", _detail)
    app = FastAPI()
    app.include_router(TR.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: _Db(row)
    r = TestClient(app, raise_server_exceptions=False).get(f"/api/v1/agents/{DID}/track-record")
    assert r.status_code == 200, r.text
    return r.json()["liveness"]


def test_a_placeholder_endpoint_is_no_live_service_whatever_the_probe_said(monkeypatch):
    lv = _get(monkeypatch, ("unreachable", None, False, {"url": "https://sub-9.agents.local"}))
    assert lv["probe"] == "unreachable" and lv["service_declared"] is False


def test_a_real_endpoint_that_does_not_answer_is_declared(monkeypatch):
    lv = _get(monkeypatch, ("unreachable", None, False, {"supportedInterfaces": [{"url": "https://agent.example.org/a2a"}]}))
    assert lv["probe"] == "unreachable" and lv["service_declared"] is True


def test_an_agent_with_no_card_declares_none(monkeypatch):
    # control: the agent row exists, its card does not (LEFT JOIN): the block is still there, declaring nothing
    lv = _get(monkeypatch, (None, None, False, None))
    assert lv["probe"] is None and lv["service_declared"] is False

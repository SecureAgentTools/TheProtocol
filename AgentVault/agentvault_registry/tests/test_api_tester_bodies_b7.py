"""§SUITES1018 batch 7 (2026-10-19): rows the V0624 sweep left NOT MEASURED "runner gap: no body it accepts", read.

Four rows of the 2026-10-18 V0624 sweep never reached their handler, each for want of a body or a path value the
sweep could have sent, and each read against its handler first:
- POST /teg/fx/quote prices a swap and moves no funds: a receiver on a peer frame with another unit where the frame has
  one (batch 6c's _fx_counterparty_did), else the sweep's local counterparty (rate 1.0).
- POST /agora/passport/order-status is a read-only relay to the peer frame's market, scoped to the sweep's agent.
- POST /admin/opa/simulate replays decisions against a scratch module it always deletes: the module's package is the
  sweep's own (OPA joins every module of one package; system.* is refused by the route).
- GET /developers/me/prefs/{key} asked for a key outside the closed set (404 "Unknown pref key"): it reads the pulse
  switch. The PUT replaces a real setting of the signed-in developer whole, so it is NOT MEASURED, with that reason.
- POST /attestations/schedules had no body, and DELETE /attestations/schedules/{schedule_id} sent base's literal "1"
  (400 "Invalid schedule_id (not UUID)"): the sweep agent declares its own schedule (an upsert per agent and circuit)
  and the DELETE row disables that one, declaring it first when the agent holds none.

RED on 23f0fa76 (batch 7 part 1): every test_red_* fails there (the three schedule tests on f536253c too); the
test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio

import httpx

from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.request_bodies import RequestBodies


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


def test_red_the_fx_quote_names_a_receiver_and_an_amount():
    assert RequestBodies().get_body("/teg/fx/quote") == {"receiver_did": "__FX_RECEIVER_DID__", "amount": "1"}


def test_red_the_passport_status_read_names_the_peer_market():
    b = RequestBodies().get_body("/agora/passport/order-status")
    assert b["venue_registry"] == "__PEER_FRAME_NAME__" and b["order_ids"], b


def test_red_the_opa_simulation_uploads_a_package_of_its_own():
    from agentvault_registry.routers.admin_opa import SimulateRequest, refuses_system_package, rego_package
    b = RequestBodies().get_body("/admin/opa/simulate")
    req = SimulateRequest(**b)   # the route's own validation
    pkg = rego_package(req.rego)
    assert pkg == "apitest_sweep_simulation" and not refuses_system_package(req.rego)
    assert req.rule_path.split("/")[0] == pkg and req.limit <= 10


def _markers(monkeypatch, fx_did, values):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(values))

    async def _fx():
        return fx_did
    monkeypatch.setattr(R, "_fx_counterparty_did", _fx)
    return asyncio.run(R._resolve_body_markers({"receiver_did": "__FX_RECEIVER_DID__", "amount": "1"}))


def test_red_the_fx_receiver_marker_names_the_cross_frame_receiver(monkeypatch):
    out = _markers(monkeypatch, "did:theprotocol:on-the-peer-frame", {"agent_002_did": "did:theprotocol:local"})
    assert out == {"receiver_did": "did:theprotocol:on-the-peer-frame", "amount": "1"}


def test_red_without_a_peer_frame_the_marker_names_the_local_counterparty(monkeypatch):
    out = _markers(monkeypatch, None, {"agent_002_did": "did:theprotocol:local"})
    assert out["receiver_did"] == "did:theprotocol:local"


def test_red_a_developers_preference_write_is_not_measured():
    kind, why = B._classify_frame_control("PUT", "/developers/me/prefs/{key}")
    assert kind == "account_setting" and "never overwrites" in why


def test_control_the_preference_read_and_its_neighbours_are_untouched():
    for m, p in (("GET", "/developers/me/prefs/{key}"), ("GET", "/developers/me/prefs"),
                 ("PUT", "/developers/me/profile")):
        assert B._classify_frame_control(m, p) == ("", ""), (m, p)


def test_red_the_preference_read_asks_for_a_key_that_exists(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(
            200, json={"key": "pocket.pulse", "value": None, "updated_at": None}))
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    t = B.APITestBase(base_url="http://registry-test:8000")
    t._dynamic_ids["_populated"] = True   # the fixtures are not this test's subject
    out = asyncio.run(t.test_endpoint(method="GET", path="/developers/me/prefs/{key}", auth_type="developer",
                                      developer_token="dev-token"))
    asked = [r.url.path for r in seen]
    assert "/api/v1/developers/me/prefs/pocket.pulse" in asked, asked
    assert out.get("statusCode") == 200, out


# ── the sweep agent's own attestation schedule: declared by the POST row, disabled by the DELETE row ────────────────

def test_red_the_schedule_body_declares_an_active_circuit_at_the_longest_interval():
    from agentvault_registry.routers.attestations import _ACTIVE_CIRCUIT_IDS, CreateScheduleRequest
    b = RequestBodies().get_body("/attestations/schedules")
    req = CreateScheduleRequest(**b)
    assert req.circuit_id in _ACTIVE_CIRCUIT_IDS and req.interval_hours == 720, b


class _Schedules:
    def __init__(self, monkeypatch, items):
        self.items, self.posts = list(items), []
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _handle(self, req):
        if req.url.path == "/api/v1/attestations/schedules" and req.method == "GET":
            return httpx.Response(200, json={"items": self.items, "count": len(self.items)})
        if req.url.path == "/api/v1/attestations/schedules" and req.method == "POST":
            import json as _json
            self.posts.append(_json.loads(req.content))
            row = {"id": "5b2c0c3e-0000-4000-8000-000000000002", "enabled": True, **self.posts[-1]}
            self.items.append(row)
            return httpx.Response(200, json=row)
        return httpx.Response(200, json={"items": []})


def _placeholders(monkeypatch, agent_token="agent-token"):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    return asyncio.run(R.replace_path_placeholders("/attestations/schedules/{schedule_id}", "dev-token", agent_token,
                                                   method="DELETE"))


def test_red_the_schedule_delete_disables_the_sweep_agents_own(monkeypatch):
    mine = "5b2c0c3e-0000-4000-8000-000000000001"
    f = _Schedules(monkeypatch, [{"id": "another-circuit", "circuit_id": "fairCrossRegistryFee/v2.0.0", "enabled": True},
                                 {"id": mine, "circuit_id": "fairMarkupPolicy/v2.0.0", "enabled": True}])
    assert _placeholders(monkeypatch) == f"/attestations/schedules/{mine}"
    assert f.posts == []


def test_red_with_no_schedule_of_its_own_one_is_declared_first(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    f = _Schedules(monkeypatch, [{"id": "disabled", "circuit_id": "fairMarkupPolicy/v2.0.0", "enabled": False}])
    assert _placeholders(monkeypatch) == "/attestations/schedules/5b2c0c3e-0000-4000-8000-000000000002"
    assert f.posts == [R._SWEEP_SCHEDULE] == [RequestBodies().get_body("/attestations/schedules")]


def test_control_without_the_agent_nothing_is_declared(monkeypatch):
    f = _Schedules(monkeypatch, [])
    out = _placeholders(monkeypatch, agent_token=None)
    assert f.posts == [] and not out.endswith("5b2c0c3e-0000-4000-8000-000000000002"), out

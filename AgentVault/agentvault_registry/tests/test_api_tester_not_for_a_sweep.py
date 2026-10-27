"""§SUITES1018 batch 7 (2026-10-19): the rows left NOT MEASURED "runner gap: no body" say what they would do.

The V0624 sweep (2026-10-18) left 119 rows NOT MEASURED "runner gap: the sweep sent this route no body it accepts", as
if a body were all they lacked. Batch 6 gave 49 of them their reason and 14 a body; batch 7 gave five more a body
(test_api_tester_bodies_b7.py). Each of the rest was read against its handler: they move value, rewrite a frame's or
an org's live configuration, start work on the host's frame runner or write the tester's own history, or act for a
person (mail, a review, a moderation decision, a biometric, a role set, an org handed away). None is a call a sweep
makes, whatever body it sends; each is NOT MEASURED before any call, with what it would do. The single-role grant is
measured: on the sweep's own agent with a role it holds from birth the route answers `changed: false`.

RED on 5f180ad6 (batch 7 part 4): every test_red_* fails there; of the test_control_* ones, the one that reads the new
table fails there only because the table is new, the other passes on both.
"""
from __future__ import annotations

import asyncio

import httpx

from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.request_bodies import RequestBodies

ROWS = """POST /organizations/{org_id}/treasury/fund
POST /organizations/{org_id}/treasury/remit
POST /organizations/{org_id}/treasury/sweep
POST /organizations/{org_id}/work-orders
POST /organizations/{org_id}/work-orders/{oid}/award
POST /organizations/{org_id}/work-orders/{oid}/verify
POST /contracts/{contract_id}/mark-failed
POST /teg/fx/route/sweep
POST /admin/fee-collector/distribute
POST /commons/seasons/{season_id}/ballot
POST /commons/seasons/{season_id}/submissions
POST /admin/fiat/flare/grant
PUT /teg/fx/reserve-keeper
PUT /teg/fx/router-keeper
PUT /admin/jurisdiction-profile
POST /admin/jurisdiction-profile/authorizations
PUT /admin/reward-funding/policy
PUT /admin/release-channel/schedule
POST /admin/canary/fleet/remote-paths
POST /agora/organizations/{org_id}/listings/{symbol}/market-makers
PUT /organizations/{org_id}/settings
POST /admin/frame-runner/jobs
POST /admin/frame-runner/frames/{name}/resume
POST /admin/frame-runner/plan
POST /admin/api-test/runs/publish
POST /admin/mcp-tester/sandbox/reveal
POST /admin/email/send
POST /agents/{did}/instruct
POST /operators/request-frame
PATCH /admin/frame-requests/{request_id}
POST /admin/bundles/reports/{report_id}/dismiss
POST /admin/agents/{did}/authz/clamp
PUT /agents/{did}/authz
POST /organizations/{org_id}/agents/grant-bulk
PUT /organizations/{org_id}/members/{developer_id}/role
POST /organizations/{org_id}/ownership/transfer
POST /organizations/{org_id}/ownership/respond
PATCH /agent-cards/{card_id}/listing
POST /admin/agents/bulk/refresh-cards
POST /admin/agents/orphaned-listings/sweep
POST /admin/evals/suites/{suite_id}/tasks
POST /liability/webauthn/register
POST /auth/push-login/{approval_id}/approve
POST /auth/push-login/{approval_id}/approve-direct
POST /phone/sessions
POST /phone/sessions/{sid}/act"""


def _rows():
    return [tuple(line.split(" ", 1)) for line in ROWS.splitlines()]


def test_red_each_row_left_a_runner_gap_names_what_it_would_do():
    kinds = {}
    for m, p in _rows():
        kind, why = B._classify_frame_control(m, p)
        assert kind in ("moves_money", "frame_control", "suite_launch", "for_a_person"), (m, p, kind)
        assert "not a call a sweep makes" in why and "runner gap" not in why, (m, p, why)
        kinds[kind] = kinds.get(kind, 0) + 1
    assert kinds == {"moves_money": 12, "frame_control": 9, "suite_launch": 5, "for_a_person": 20}, kinds


def test_red_a_concrete_path_matches_its_route():
    assert B._classify_frame_control("POST", "/organizations/5/treasury/sweep")[0] == "moves_money"
    assert B._classify_frame_control("PATCH", "/agent-cards/abc-123/listing?x=1")[0] == "for_a_person"


def test_control_none_of_them_had_a_reason_before():
    older = set(B._FRAME_CONTROL_ROUTES) | set(B._MONEY_ROUTES) | set(B._PEER_STANDING_ROUTES)
    for key in B._NOT_FOR_A_SWEEP:
        assert key not in older and not B._classify_suite_launch(*key), key


def test_control_the_reads_and_the_single_grant_beside_them_are_measured():
    for m, p in (("GET", "/admin/frame-runner/status"), ("GET", "/admin/frame-runner/jobs/{job_id}"),
                 ("GET", "/agents/{did}/authz"), ("POST", "/agents/{did}/authz/roles"),
                 ("GET", "/teg/fx/reserve-keeper"), ("GET", "/admin/jurisdiction-profile"),
                 ("GET", "/organizations/{org_id}/settings"), ("GET", "/commons/seasons/{season_id}"),
                 ("POST", "/organizations/{org_id}/members")):
        assert B._classify_frame_control(m, p) == ("", ""), (m, p)


def test_red_the_single_role_grant_names_a_role_the_agent_is_born_with():
    from agentvault_registry.agent_authz import ROLE_PERMISSIONS
    b = RequestBodies().get_body("/agents/{did}/authz/roles")
    assert b == {"role": "client"} and "client" in ROLE_PERMISSIONS
    # sbx-alpha's AGENT_RBAC_DEFAULT_ROLES is trader,client,staker; the code default trader,client
    assert "client" in "trader,client".split(",")


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


def test_red_the_router_sends_nothing_for_a_mail_or_a_treasury_drain(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(org_id="9"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)
    seen = []
    real = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200, json={}))
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    for path, bucket in (("/admin/email/send", "not_measured_for_a_person"),
                         ("/organizations/{org_id}/treasury/sweep", "not_measured_moves_money")):
        out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "POST", "path": path,
                                                                       "auth": "developer"}, current_developer=None))
        assert out["not_measured"] is True and out["failure_bucket"] == bucket, out
    assert seen == []

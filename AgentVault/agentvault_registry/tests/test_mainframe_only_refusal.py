"""D6-820 (V0640): a deliberate "not on this kind of registry" refusal answers 404 with a code word first, never 503.

A cloud operator refused a sovereign-mainframe-only rail with 503 SERVICE_UNAVAILABLE, and a mainframe refused a cloud
operator's own routes (self-restart, self-rename, self-logs) the same way: a status that reads as an outage to a client
(retry), to monitoring (a 5xx) and to the testers. Both answer 404 now, with the code word first in a plain-string
detail (`mainframe_only:`, `operator_only:`) and the sentence every reader before V0640 matched kept whole after it.
The wire is read through the registry's own error handlers (the RFC 7807 layer stringifies a dict detail, so the code
word has to sit in a plain string), and each route that refuses inline is called with the registry kind it refuses.
"""
import asyncio

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import errors
from agentvault_registry.core import mainframe_gate
from agentvault_registry.routers import admin_developers, operator_portal_actions

# the prefix the testers pin (mcp_contracts.py, requestFrame); GATE_SENTENCE is its first clause
PIN = "This feature runs on sovereign mainframes only. Cloud-operators federa"


@pytest.fixture()
def frame_only_client(monkeypatch):
    def make(mainframe: bool) -> TestClient:
        monkeypatch.setattr(mainframe_gate, "is_mainframe", lambda: mainframe)
        app = FastAPI()
        errors.register_error_handlers(app)

        @app.post("/frame-only", dependencies=[Depends(mainframe_gate.require_mainframe_only)])
        async def frame_only():
            return {"ran": True}
        return TestClient(app)
    return make


def test_a_cloud_operator_refuses_a_frame_only_rail_with_404_and_the_code_word_first(frame_only_client):
    r = frame_only_client(False).post("/frame-only")
    assert r.status_code == 404, (r.status_code, r.text[:300])
    body = r.json()
    for detail in (body["detail"], body["error"]["detail"]):
        assert detail.startswith("mainframe_only: "), detail
        assert PIN in detail and "runs on sovereign mainframes only" in detail, detail
        assert "—" not in detail, detail          # no em dash in a sentence people read
    assert body["error"]["type"] == "not_found" and body["status"] == 404
    assert "ran" not in body


def test_a_mainframe_serves_the_rail(frame_only_client):
    r = frame_only_client(True).post("/frame-only")
    assert r.status_code == 200 and r.json() == {"ran": True}


def test_the_refusal_is_the_shared_one_and_never_a_5xx():
    exc = mainframe_gate.mainframe_only_refusal()
    assert exc.status_code == 404 and exc.detail == f"mainframe_only: {mainframe_gate.MAINFRAME_ONLY_SENTENCE}"
    own = mainframe_gate.mainframe_only_refusal("Gift provisioning is mainframe-only (x).")
    assert own.status_code == 404 and own.detail == "mainframe_only: Gift provisioning is mainframe-only (x)."
    rev = mainframe_gate.operator_only_refusal("self-rename is for cloud-ops only. Mainframe admins use PUT y.")
    assert rev.status_code == 404 and rev.detail == "operator_only: self-rename is for cloud-ops only. Mainframe admins use PUT y."


def test_gift_provisioning_on_a_cloud_operator_refuses_with_the_code_word(monkeypatch):
    monkeypatch.setattr(mainframe_gate, "is_mainframe", lambda: False)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(admin_developers.gift_provisioning(developer_id=999999, body=None, db=None, admin=None))
    assert ei.value.status_code == 404
    assert ei.value.detail == ("mainframe_only: Gift provisioning is mainframe-only (cloud-ops cannot extend their own "
                               "provisioning).")


@pytest.mark.parametrize("call, sentence", [
    (lambda: operator_portal_actions.operator_self_restart(
        body=operator_portal_actions.SelfRestartRequest(), current_admin=None, db=None),
     "Operator self-restart is for cloud-ops only. Mainframe admins use /admin/cloud-operators/{id}/restart-service."),
    (lambda: operator_portal_actions.operator_self_rename(
        body=operator_portal_actions.SelfRenameRequest(display_name="Probe"), current_admin=None, db=None),
     "self-rename is for cloud-ops only. Mainframe admins use PUT /api/v1/admin/registry-card."),
    (lambda: operator_portal_actions.operator_self_logs(service="registry", tail=10, current_admin=None, db=None),
     "Operator self-logs is for cloud-ops only. Mainframe admins use /admin/cloud-operators/{id}/logs."),
], ids=["self-restart", "self-rename", "self-logs"])
def test_a_mainframe_refuses_a_cloud_operators_own_route_with_404_and_its_sentence_whole(monkeypatch, call, sentence):
    monkeypatch.setattr(mainframe_gate, "is_mainframe", lambda: True)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(call())
    assert ei.value.status_code == 404
    assert ei.value.detail == f"operator_only: {sentence}"
    assert "is for cloud-ops only" in ei.value.detail          # the testers' marker survives

"""§TESTBED (2026-09-19): the MCP tester view's sandbox rail.

His words: "the sandbox provisioning should be also in the frontend mcp-tester view ... options to pick and you can see
progress. and possible errors". The rail passes one request per route to the frame runner (the operator socket a kit
frame mounts), names THIS frame (the runner checks the claim against the calling container), audits every act and every
refusal (a password never), and answers `available: false` with the reason where no runner offers sandboxes, so the view
can say so rather than show an empty panel. A fake stands in at the client's one seam.
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import mcp_tester_sandbox as rail
from agentvault_registry.services import frame_runner_client as client

BASE = "/api/v1/admin/mcp-tester/sandbox"
JOB = "0123456789abcdef"


class FakeRunner:
    def __init__(self):
        self.calls, self.answers = [], {}

    async def __call__(self, op, *, timeout=client.SHORT_TIMEOUT_S, **fields):
        self.calls.append({"op": op, **fields})
        answer = self.answers.get(op)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _app(monkeypatch, developer=None):
    fake, audits = FakeRunner(), []

    async def _log(db, **row):
        audits.append(row)

    async def _db():
        yield None
    monkeypatch.setattr(rail.runner, "call", fake)
    monkeypatch.setattr(rail, "log_admin_action", _log)
    monkeypatch.setattr(rail, "frame_slug", lambda: "larch")
    app = FastAPI()
    app.include_router(rail.router)
    app.dependency_overrides[get_db] = _db
    if developer is None:
        app.dependency_overrides[rail.platform_admin] = lambda: types.SimpleNamespace(id=7, is_admin=True)
    else:
        app.dependency_overrides[security.get_current_developer] = lambda: developer
    return TestClient(app), fake, audits


def test_no_runner_is_available_false_with_the_reason_not_an_error(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["sandbox_status"] = client.RunnerUnavailable("no frame runner socket at /run/theprotocol/frame-runner.sock")
    r = http.get(BASE)
    assert r.status_code == 200
    assert r.json() == {"available": False, "frame": "larch", "reason": "no_runner",
                        "why": "no frame runner socket at /run/theprotocol/frame-runner.sock"}


def test_a_refusal_is_available_false_and_says_why(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["sandbox_status"] = client.RunnerRefused("op 'sandbox_status': this runner's policy does not offer sandboxes")
    body = http.get(BASE).json()
    assert body["available"] is False and body["reason"] == "refused" and "does not offer sandboxes" in body["why"]


def test_a_sandboxs_own_console_learns_whose_sandbox_it_is(monkeypatch):
    """The runner's own sentence (frame_runner._sandbox_parent), classified here so the view never parses it."""
    http, fake, _ = _app(monkeypatch)
    fake.answers["sandbox_status"] = client.RunnerRefused("larchsbx is itself the sandbox of larch; a sandbox does not provision sandboxes")
    body = http.get(BASE).json()
    assert body["available"] is False and body["reason"] == "is_sandbox" and body["parent"] == "larch"


def test_status_names_this_frame_and_trims_the_job(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["sandbox_status"] = {"supported": True, "frame": "larch", "sandboxes": [],
                                      "job": {"id": JOB, "op": "sandbox_up", "name": "larch", "state": "running",
                                              "argv": ["python3", "frame-sandbox.py"], "pid": 4242, "secrets_dir": "/x"},
                                      "topologies": [], "host": {"problems": [], "mem_available_gib": 40.0, "busy": None}}
    body = http.get(BASE).json()
    assert fake.calls == [{"op": "sandbox_status", "frame": "larch"}]
    assert body["available"] is True and set(body["job"]) == set(rail.JOB_FIELDS)
    assert "argv" not in body["job"] and "pid" not in body["job"] and "secrets_dir" not in body["job"]


def test_provision_passes_the_topology_and_audits_it(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["sandbox_up"] = {"started": True, "job": {"id": JOB, "op": "sandbox_up", "name": "larch", "state": "running"}}
    r = http.post(BASE, json={"frames": 2, "operators": True})
    assert r.status_code == 200 and r.json()["job"]["id"] == JOB
    assert fake.calls == [{"op": "sandbox_up", "frame": "larch", "frames": 2, "operators": True}]
    assert audits[-1]["action"] == "mcp_tester_sandbox.up" and audits[-1]["details"]["job_id"] == JOB


@pytest.mark.parametrize("body", [{"frames": 3}, {"frames": "2"}, {"operators": "yes"}, {"frames": 1, "extra": 1}])
def test_the_shape_is_closed(monkeypatch, body):
    http, fake, _ = _app(monkeypatch)
    assert http.post(BASE, json=body).status_code == 422
    assert fake.calls == []


def test_a_refused_provision_is_409_with_the_runners_sentence_and_audited(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["sandbox_up"] = client.RunnerRefused("job abc (sandbox_up larch) is running: one job at a time")
    r = http.post(BASE, json={"frames": 1, "operators": False})
    assert r.status_code == 409 and "one job at a time" in r.json()["detail"]
    assert audits[-1]["outcome"] == "refused" and "one job at a time" in audits[-1]["error_message"]


def test_reveal_answers_the_login_uncached_and_the_audit_never_holds_the_password(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["sandbox_reveal"] = {"sandbox": "larchsbx", "console": "https://sandbox.larch.example.org",
                                      "email": "admin@sandbox.larch.example.org", "password": "s3cret-" + "x" * 20}
    r = http.post(BASE + "/reveal", json={"which": "a"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["password"].startswith("s3cret-")
    assert not any("s3cret-" in repr(a) for a in audits)
    assert audits[-1]["details"] == {"which": "a", "sandbox": "larchsbx", "email": "admin@sandbox.larch.example.org"}


def test_events_pass_the_cursor(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["sandbox_events"] = {"job": {"id": JOB, "state": "running"}, "events": [{"step": "plan", "event": "start"}], "next": 5}
    r = http.get(f"{BASE}/jobs/{JOB}/events", params={"after": 4})
    assert r.status_code == 200 and r.json()["next"] == 5
    assert fake.calls == [{"op": "sandbox_events", "frame": "larch", "job_id": JOB, "after": 4}]
    assert http.get(f"{BASE}/jobs/not-a-job/events").status_code == 422


@pytest.mark.parametrize("flags,expect", [({"admin_platform": True}, 200), ({"admin_federation": True}, 403), ({}, 403)])
def test_the_gate_is_the_platform_flag(monkeypatch, flags, expect):
    """A non-legacy admin (is_admin=False: legacy is_admin passes every flag by design) needs admin_platform itself."""
    dev = types.SimpleNamespace(id=9, email="ops@example.test", is_admin=False, must_change_password=False, **flags)
    http, fake, _ = _app(monkeypatch, developer=dev)
    fake.answers["sandbox_status"] = {"supported": True, "frame": "larch", "sandboxes": [], "job": None}
    assert http.get(BASE).status_code == expect
    assert (fake.calls != []) == (expect == 200)

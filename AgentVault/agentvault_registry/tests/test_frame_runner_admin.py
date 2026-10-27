"""§FRAMEPROV P3 (2026-09-13): the frame runner rail.

The gate (admin_platform, and only that flag), the pass-through (the whole spec reaches the runner, and nothing else),
the audit (every act, refusals included, the credential never), what stays on the host (a job's argv, pid and secrets
path), and the retirement of the nsenter launcher. The runner itself is tested in the stack repo
(tools/frame-runner/tests); here a fake stands in at the client's one seam, and a real unix socket proves the framing.
"""
import ast
import asyncio
import json
import socket
import threading
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import frame_runner_admin as rail
from agentvault_registry.services import frame_runner_client as client

SRC = Path(rail.__file__).resolve().parents[1]
BASE = "/api/v1/admin/frame-runner"
JOB = "0123456789abcdef"
SPEC = {"name": "juice", "frame_label": "Juice", "ticker": "JUC", "currency_name": "Juice Unit", "mint": 1000000,
        "theme": "neural", "description": "A sandbox frame.", "operator_label": "TheProtocol",
        "location_label": "Valencia, Spain", "lat": 39.47, "lng": -0.38, "website": "",
        "registry_image": "agentvault2-registry-a:v0362", "teg_image": "agentvault2-teg-layer:v0351"}


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.answers = {}

    async def __call__(self, op, *, timeout=client.SHORT_TIMEOUT_S, **fields):
        self.calls.append({"op": op, "timeout": timeout, **fields})
        answer = self.answers.get(op)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _app(monkeypatch, developer=None):
    """The router alone. `developer` given: the REAL admin gate runs against that developer; otherwise it is waved."""
    fake, audits = FakeRunner(), []

    async def _log(db, **row):
        audits.append(row)

    async def _db():
        yield None

    monkeypatch.setattr(rail.runner, "call", fake)
    monkeypatch.setattr(rail, "log_admin_action", _log)
    app = FastAPI()
    app.include_router(rail.router)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    if developer is None:
        app.dependency_overrides[rail.platform_admin] = lambda: types.SimpleNamespace(id=10, is_admin=True)
    else:
        app.dependency_overrides[security.get_current_developer] = lambda: developer
    return TestClient(app), fake, audits


def test_status_answers_frames_and_jobs_and_leaves_host_paths_on_the_host(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["ping"] = {"version": "2", "uid": 1000, "active": None, "domain": "theprotocol.cloud",
                            "images": {"registry": [SPEC["registry_image"]], "teg": [SPEC["teg_image"]]},
                            "resumable_steps": ["compose"], "spec_fields": list(SPEC)}
    fake.answers["status"] = {
        "active": None,
        "jobs": [{"id": JOB, "op": "standup", "name": "juice", "state": "succeeded", "created": "2026-09-13T08:00:00Z",
                  "ended": "2026-09-13T08:16:00Z", "exit_code": 0, "argv": ["python3", "-u", "driver"], "pid": 4242}],
        "frames": [{"name": "juice", "state": "live", "stack_dir": "/opt/theprotocol/stack/juice-1788000000",
                    "secrets_dir": "/var/lib/theprotocol/frame-runner/jobs/x/secrets", "spec": SPEC,
                    "built_by_job": JOB, "created": "2026-09-13T08:00:00Z", "updated": "2026-09-13T08:16:00Z"}]}
    r = http.get(f"{BASE}/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["runner"]["domain"] == "theprotocol.cloud"
    assert body["frames"][0]["stack_dir"].endswith("juice-1788000000") and "secrets_dir" not in body["frames"][0]
    assert set(body["jobs"][0]) == set(rail.JOB_FIELDS)
    assert "/var/lib/theprotocol" not in r.text and "4242" not in r.text


def test_a_registry_that_cannot_reach_the_runner_says_so_and_why(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    reason = "no frame runner socket at /run/theprotocol/frame-runner.sock on this registry"
    fake.answers["ping"] = client.RunnerUnavailable(reason)
    r = http.get(f"{BASE}/status")
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": reason, "runner": None, "active": None, "jobs": [], "frames": []}


def test_a_registry_whose_socket_does_not_serve_the_status_reads_says_so_too(monkeypatch):
    # §MCPTEST30 V0562: a registry holding only the operator socket is refused "ping"; the page read it as an error
    http, fake, _ = _app(monkeypatch)
    words = "op 'ping' is not served on this socket; this socket serves operator_ping, operator_provision"
    fake.answers["ping"] = client.RunnerRefused(words)
    r = http.get(f"{BASE}/status")
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": f"this registry's runner socket does not serve frame work ({words})",
                        "runner": None, "active": None, "jobs": [], "frames": []}


def test_a_plan_sends_the_whole_spec_and_waits_as_long_as_the_runner_may(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["plan"] = {"exit_code": 2, "plan_ok": False,
                            "plan": {"ok": False, "refusals": ["cert missing"], "warnings": [], "derived": {}}}
    r = http.post(f"{BASE}/plan", json=SPEC)
    assert r.status_code == 200 and r.json()["plan"]["refusals"] == ["cert missing"]
    assert fake.calls == [{"op": "plan", "timeout": client.LONG_TIMEOUT_S, "spec": SPEC}]


@pytest.mark.parametrize("extra", [{"federate_with": "eu"}, {"grant_host_reach": True}, {"posture": "production"}])
def test_a_field_outside_the_spec_never_reaches_the_runner(monkeypatch, extra):
    # Milestone 1's hard stops (no federation, no host reach, no production posture from the UI) hold at the schema too.
    http, fake, audits = _app(monkeypatch)
    for path in (f"{BASE}/plan", f"{BASE}/jobs"):
        assert http.post(path, json={**SPEC, **extra}).status_code == 422
    assert fake.calls == [] and audits == []


def test_a_started_standup_is_audited_with_its_job(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["standup"] = {"started": True, "plan": {"ok": True},
                               "job": {"id": JOB, "op": "standup", "name": "juice", "state": "running"}}
    r = http.post(f"{BASE}/jobs", json=SPEC)
    assert r.status_code == 200 and r.json()["job"]["id"] == JOB
    assert fake.calls == [{"op": "standup", "timeout": client.LONG_TIMEOUT_S, "spec": SPEC}]
    assert len(audits) == 1
    row = audits[0]
    assert (row["action"], row["target_type"], row["target_id"], row["outcome"], row["actor_id"]) == \
        ("frame_runner.standup", "frame", "juice", "success", "10")
    assert row["details"]["job_id"] == JOB and row["details"]["registry_image"] == SPEC["registry_image"]


def test_a_standup_its_plan_refuses_starts_nothing_and_is_audited_as_refused(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    refusal = "cert missing: /etc/letsencrypt/live/juice.theprotocol.cloud/fullchain.pem"
    fake.answers["standup"] = {"started": False, "exit_code": 2, "plan_ok": False,
                               "plan": {"ok": False, "refusals": [refusal], "warnings": [], "derived": {}}}
    r = http.post(f"{BASE}/jobs", json=SPEC)
    assert r.status_code == 200 and r.json()["started"] is False
    assert [(a["outcome"], a["error_message"]) for a in audits] == [("refused", refusal)]


def test_a_runner_refusal_is_a_409_carrying_its_sentence_and_an_audit_row(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["teardown"] = client.RunnerRefused("eu is a protected frame (/etc/theprotocol/protected-frames.list)")
    r = http.post(f"{BASE}/frames/eu/teardown")
    assert r.status_code == 409
    assert r.json()["detail"] == "refused: eu is a protected frame (/etc/theprotocol/protected-frames.list)"
    assert [(a["action"], a["outcome"], a["target_id"]) for a in audits] == [("frame_runner.teardown", "refused", "eu")]


def test_an_act_on_a_runner_that_is_down_is_a_503_and_audited(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["cancel"] = client.RunnerUnavailable("nothing is listening on /run/theprotocol/frame-runner.sock")
    r = http.post(f"{BASE}/jobs/{JOB}/cancel")
    assert r.status_code == 503 and r.json()["detail"].startswith("runner unavailable: ")
    assert [(a["outcome"], a["target_type"]) for a in audits] == [("failure", "frame_runner_job")]


def test_a_runner_failure_is_a_502(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["status"] = client.RunnerError("KeyError: 'id'")
    r = http.get(f"{BASE}/jobs/{JOB}")
    assert r.status_code == 502 and r.json()["detail"] == "runner error: KeyError: 'id'"


def test_the_credential_is_handed_over_uncached_and_never_written_to_the_audit(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    secret = "Only-Once-7f3a9c2e1b"
    fake.answers["reveal"] = {"admin_email": "admin@juice.theprotocol.cloud", "admin_password": secret,
                              "console": "https://juice.theprotocol.cloud"}
    r = http.post(f"{BASE}/frames/juice/reveal")
    assert r.status_code == 200 and r.json()["admin_password"] == secret
    assert r.headers["cache-control"] == "no-store"
    assert [(a["action"], a["details"]) for a in audits] == [("frame_runner.reveal", {"admin_email": "admin@juice.theprotocol.cloud"})]
    assert secret not in json.dumps(audits)


def test_a_job_view_leaves_the_argv_pid_and_secrets_path_on_the_host(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["status"] = {"job": {"id": JOB, "op": "resume", "name": "juice", "state": "running", "created": "x",
                                      "ended": None, "exit_code": None, "request": {"name": "juice", "from_step": "vhosts"},
                                      "argv": ["python3"], "pid": 4242, "needle": "standup_driver.py", "uid": 1000,
                                      "secrets_dir": "/var/lib/theprotocol/frame-runner/jobs/x/secrets"},
                              "last_event": {"step": "vhosts", "event": "start"}}
    r = http.get(f"{BASE}/jobs/{JOB}")
    assert r.status_code == 200
    assert set(r.json()["job"]) == set(rail.JOB_FIELDS) and r.json()["last_event"]["step"] == "vhosts"
    assert fake.calls == [{"op": "status", "timeout": client.SHORT_TIMEOUT_S, "job_id": JOB}]


def test_events_pass_the_cursor_and_a_negative_one_never_reaches_the_runner(monkeypatch):
    http, fake, _ = _app(monkeypatch)
    fake.answers["events"] = {"events": [], "next": 7, "state": "running"}
    assert http.get(f"{BASE}/jobs/{JOB}/events", params={"after": 7}).json()["next"] == 7
    assert http.get(f"{BASE}/jobs/{JOB}/events", params={"after": -1}).status_code == 422
    assert [c["after"] for c in fake.calls] == [7]


def test_a_resume_names_its_step(monkeypatch):
    http, fake, audits = _app(monkeypatch)
    fake.answers["resume"] = {"started": True, "job": {"id": JOB}}
    r = http.post(f"{BASE}/frames/juice/resume", json={"from_step": "vhosts"})
    assert r.status_code == 200
    assert fake.calls == [{"op": "resume", "timeout": client.SHORT_TIMEOUT_S, "name": "juice", "from_step": "vhosts"}]
    assert audits[-1]["details"] == {"from_step": "vhosts", "job_id": JOB}


@pytest.mark.parametrize("flags, expect", [
    ({"admin_platform": True}, 200),
    ({"admin_federation": True}, 403),   # the retired launcher's flag does not open this rail
    ({}, 403),
])
def test_the_gate_is_admin_platform_and_only_admin_platform(monkeypatch, flags, expect):
    developer = types.SimpleNamespace(id=7, email="ops@example.test", is_admin=False, must_change_password=False, **flags)
    http, fake, _ = _app(monkeypatch, developer=developer)
    fake.answers["plan"] = {"exit_code": 0, "plan_ok": True, "plan": {"ok": True}}
    r = http.post(f"{BASE}/plan", json=SPEC)
    assert r.status_code == expect, r.text
    assert len(fake.calls) == (1 if expect == 200 else 0)


def _modules(path):
    found = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_the_nsenter_launcher_is_retired_and_the_rail_holds_no_host_reach():
    main = ast.parse((SRC / "main.py").read_text())
    routers = {alias.name for node in ast.walk(main)
               if isinstance(node, ast.ImportFrom) and node.module == "agentvault_registry.routers" for alias in node.names}
    assert "frame_runner_admin" in routers and "frame_demo" not in routers
    assert not (SRC / "routers" / "frame_demo.py").exists()
    assert not (SRC / "services" / "frame_demo_launcher.py").exists()
    reach = {"subprocess", "docker", "pty"}
    assert not reach & (_modules(rail.__file__) | _modules(client.__file__))


def _serve_once(path, reply):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    seen = {}

    def run():
        conn, _ = srv.accept()
        with conn:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            seen["request"] = json.loads(buf)
            answer = reply(seen["request"])
            if answer is None:
                threading.Event().wait(1.5)   # accept, then say nothing
            else:
                conn.sendall(answer)
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return seen


def test_the_client_speaks_one_json_line_each_way(tmp_path, monkeypatch):
    sock = tmp_path / "fr.sock"
    seen = _serve_once(sock, lambda req: (json.dumps({"ok": True, "result": {"echo": req}}) + "\n").encode())
    monkeypatch.setenv("FRAME_RUNNER_SOCKET", str(sock))
    assert asyncio.run(client.call("events", job_id=JOB, after=3)) == {"echo": {"op": "events", "job_id": JOB, "after": 3}}
    assert seen["request"] == {"op": "events", "job_id": JOB, "after": 3}


@pytest.mark.parametrize("line, error", [
    (b'{"ok": false, "refused": "name: eu is a protected frame"}\n', client.RunnerRefused),
    (b'{"ok": false, "error": "KeyError: x"}\n', client.RunnerError),
    (b"not json\n", client.RunnerError),
    (b"[1, 2]\n", client.RunnerError),
])
def test_the_client_names_each_kind_of_answer(tmp_path, line, error):
    sock = tmp_path / "fr.sock"
    _serve_once(sock, lambda req: line)
    with pytest.raises(error):
        client.unwrap(client._exchange(str(sock), {"op": "ping"}, 5))


def test_a_missing_socket_and_a_silent_runner_are_unavailable_not_empty(tmp_path):
    with pytest.raises(client.RunnerUnavailable, match="no frame runner socket at"):
        client._exchange(str(tmp_path / "absent.sock"), {"op": "ping"}, 1)
    sock = tmp_path / "silent.sock"
    _serve_once(sock, lambda req: None)
    with pytest.raises(client.RunnerUnavailable, match="did not answer within 0.3 s"):
        client._exchange(str(sock), {"op": "ping"}, 0.3)

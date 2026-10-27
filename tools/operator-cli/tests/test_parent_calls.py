"""CB-228, CB-289 (2026-10-16): `license verify` and `sync` ask the parent a question it actually answers.

CB-228: `license verify` sent the licence to GET /api/v1/federation/info, a public route that checks no credential, and
called any 2xx verified: a revoked, suspended or wrong key read as VERIFIED. CB-289: `sync` POSTed the licence to the
parent's /api/v1/federation/sync/trigger, which never accepts a licence: the parent answered 401, nothing ran, and the
command exited 0. Both now make their call the way the operator's registry calls its parent (tp_operator.parent_call:
inside the registry container, the parent's federation lane with the operator's certificate first, the console path
when the lane is unknown), and report the parent's verdict.

SEC-08 (2026-10-17): `license rotate`, `spire enroll` and `spire revoke` still sent the licence from the host to the
parent URL. A template frame's console clears it, so the parent answered 400 (rotate-self: "X-Federation-License header
required") or 401 (the IRONHAND proxies) and nothing rotated, enrolled or was deleted. They now ask through
parent_call too: rotate-self on the lane (it forwards /api/v1/federation/) with the X-Idempotency-Key the route
requires, the IRONHAND proxies on their lane aliases (/api/v1/federation/ironhand/*, the operator's certificate). SEC-17:
`license verify` and `sync` honour the global --timeout again (they had fixed 20 s and 60 s), and so do the three.

The parent here is a FastAPI app that answers as the real parent does (the details are the registry's own:
routers/cloud_operators.cloud_operator_self_logs, core/federation_auth._verify_license_key,
core/mtls_auth.require_vouched_peer_cert, routers/federation_sync.require_sync_trigger_identity,
routers/federation_license_self.rotate_self, routers/agent_mtls's IRONHAND proxies and their federation_router); its
console clears X-Federation-License, X-Federation-Secret and X-Federation-SPIFFE-ID, as every template frame's does (EU's
`location /`). The registry container is replaced by a double that makes the call the way
routers/operator_portal_actions._call_parent does (lane first, with the certificate the parent's terminator vouches
for; the console when the lane is unknown), carrying the call's extra headers the way parent_call.SCRIPT adds them,
because a test cannot run docker; SCRIPT itself runs against a stub of the registry's modules. The commands run through
the CLI itself (typer's CliRunner).
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator import http_client  # noqa: E402
from tp_operator.main import app as cli  # noqa: E402

ACTIVE = "tp_fed_active-licence-test-not-a-secret"
REVOKED = "tp_fed_revoked-licence-test-not-a-secret"
NEW = "tp_fed_new-licence-test-not-a-secret"
DID = "did:theprotocol:0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
ROTATE = "/api/v1/federation/license/rotate-self"
OPERATOR_SVID = "spiffe://eu.parent.test/operator/amsterdam/registry"
LANE_REFUSAL = ("the operator lane is served only through this frame's mTLS federation terminator: a cloud operator "
                "reaches it at its parent frame's federation address, presenting its SVID")


def parent(operator_active: bool = True):
    """The parent frame as the operator meets it. `seen` records every request (path, licence present, vouched)."""
    app = FastAPI()
    app.state.seen = []
    app.state.rotations = []        # the idempotency key of every rotation the parent made
    app.state.spire = []            # (op, agent_did, parent_fingerprint, identity) of every entry made or deleted

    @app.middleware("http")
    async def record(request: Request, call_next):
        app.state.seen.append((request.url.path, bool(request.headers.get("X-Federation-License")),
                               request.headers.get("X-Test-Vouched") == "operator"))
        return await call_next(request)

    def licence(request: Request):
        key = request.headers.get("X-Federation-License")
        if not key:
            raise HTTPException(401, "X-Federation-License header required")
        if key != ACTIVE:
            raise HTTPException(403, "Invalid or revoked federation license")

    @app.get("/api/v1/federation/info")
    def info():                                   # public: it checks nothing (CB-228's probe)
        return {"registry_name": "EU", "federation_enabled": True}

    @app.get("/api/v1/federation/operator-self/logs")
    def lane_logs(request: Request, service: str = "registry", tail: int = 200):
        if request.headers.get("X-Test-Vouched") != "operator":
            raise HTTPException(401, LANE_REFUSAL)
        licence(request)
        return {"operator_name": "Amsterdam", "auth_mode": "federation_license", "service": service, "logs": "..."}

    @app.get("/api/v1/admin/cloud-operators/self-logs")
    def console_logs(request: Request):
        licence(request)                              # never reached with a licence: the console cleared it
        return {"operator_name": "Amsterdam"}

    @app.post("/api/v1/federation/sync/trigger")
    def trigger(request: Request):
        if request.headers.get("X-Test-Vouched") == "operator":     # mode 1: the operator's certificate
            if not operator_active:
                raise HTTPException(403, "Operator federation license is not active")
            return {"status": "sync_completed", "peers_synced": 3}
        raise HTTPException(401, "Federation authentication required (an mTLS peer certificate, the internal lane "
                                 "from inside this host, or an admin developer token)")

    @app.post(ROTATE)                 # served under /api/v1/federation/: the lane forwards it with both headers
    def rotate_self(body: dict, x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
                    x_federation_license: Optional[str] = Header(None, alias="X-Federation-License")):
        if body.get("reason") not in ("leak_suspected", "scheduled_rotation", "post_incident"):
            raise HTTPException(422, "Invalid reason")
        if not x_federation_license:
            raise HTTPException(400, "X-Federation-License header required for self-serve rotation")
        if not 16 <= len(x_idempotency_key) <= 64:
            raise HTTPException(400, "X-Idempotency-Key must be 16-64 chars")
        if x_federation_license == REVOKED:
            raise HTTPException(403, "License is not active (status=revoked); contact support to reinstate.")
        if x_federation_license != ACTIVE:
            raise HTTPException(401, "Federation license not recognised")
        app.state.rotations.append(x_idempotency_key)
        return {"rotation_id": "rot-1", "license_id": "lic-1", "license_key": NEW, "operator_did": "did:op:amsterdam",
                "operator_name": "Amsterdam", "rotated_at": "2026-10-17T04:00:00Z", "idempotent_replay": False}

    def peer_registry(request: Request) -> str:
        """require_peer_registry_identity: the operator's certificate the terminator vouched for (with S4: a revoked
        operator's certificate stops), else a licence, which a console never passes on."""
        if request.headers.get("X-Test-Vouched") == "operator":
            if not operator_active:
                raise HTTPException(403, "Operator federation license is not active")
            return OPERATOR_SVID
        if not request.headers.get("X-Federation-License"):
            raise HTTPException(401, "Federation authentication required (mTLS certificate, internal secret, or "
                                     "federation license)")
        licence(request)
        return "spiffe://theprotocol.cloud/service/registry-did:op:amsterdam"

    def spire_op(op: str, body: dict, request: Request) -> dict:
        identity = peer_registry(request)
        if not str(body.get("agent_did") or "").startswith("did:"):
            raise HTTPException(400, "Invalid or missing agent_did")
        if op == "register" and not body.get("parent_fingerprint"):
            raise HTTPException(400, "Missing parent_fingerprint")
        app.state.spire.append((op, body["agent_did"], body.get("parent_fingerprint"), identity))
        if op == "register":
            return {"spiffe_id": "spiffe://eu.parent.test/agent/" + body["agent_did"].rsplit(":", 1)[-1]}
        return {"deleted": True}

    def lane_only(request: Request) -> None:      # core/mtls_auth.require_vouched_peer_cert on federation_router
        if request.headers.get("X-Test-Vouched") != "operator":
            raise HTTPException(401, LANE_REFUSAL)

    @app.post("/api/v1/admin/ironhand/register-agent-proxy")
    def console_register(body: dict, request: Request):
        return spire_op("register", body, request)

    @app.post("/api/v1/admin/ironhand/delete-agent-proxy")
    def console_delete(body: dict, request: Request):
        return spire_op("delete", body, request)

    @app.post("/api/v1/federation/ironhand/register-agent-proxy")
    def lane_register(body: dict, request: Request):
        lane_only(request)
        return spire_op("register", body, request)

    @app.post("/api/v1/federation/ironhand/delete-agent-proxy")
    def lane_delete(body: dict, request: Request):
        lane_only(request)
        return spire_op("delete", body, request)

    return app


def console(app):
    """The parent's public console address: a template frame's vhost clears every federation credential a request
    carries before the registry sees it (EU's `location /`)."""
    cleared = {b"x-federation-license", b"x-federation-secret", b"x-federation-spiffe-id"}

    async def asgi(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, headers=[(k, v) for k, v in scope["headers"] if k.lower() not in cleared])
        await app(scope, receive, send)

    return asgi


class Container:
    """The operator's registry container: holds a licence of its own (its env) and the certificate, and calls its
    parent the way _call_parent does with the licence it is handed on stdin (its own when stdin is empty). `lane`
    False: this registry knows no federation lane for its parent (no ACTIVE frame row)."""

    def __init__(self, parent_app, own_licence, lane=True):
        self.lane_client = TestClient(parent_app, raise_server_exceptions=False)
        self.console_client = TestClient(console(parent_app), raise_server_exceptions=False)
        self.own_licence = own_licence
        self.lane = lane
        self.argv = []
        self.stdin = []
        self.timeouts = []      # (the call's HTTP timeout, the exec's own timeout) per call

    def __call__(self, ctx, service, *args, timeout=120, input=None):
        assert service == "registry" and args[:2] == ("python", "-c"), args
        assert input is not None, "stdin left to the terminal: the container would wait on it"
        self.argv.append(args)
        self.stdin.append(input)
        licence = input.strip() or self.own_licence
        spec = json.loads(args[3])
        self.timeouts.append((spec.get("timeout"), timeout))
        # what _call_parent sends (the licence alone), with the call's extra headers the way SCRIPT adds them
        headers = {**(spec.get("headers") or {}), "X-Federation-License": licence}
        answer, lane = None, None
        if self.lane:
            r = self.lane_client.request(spec["method"], spec["lane_path"], params=spec.get("params"),
                                         json=spec.get("json"), headers={**headers, "X-Test-Vouched": "operator"})
            if r.status_code != 404:
                answer, lane = r, "federation lane"
        if answer is None:   # the console: its vhost clears X-Federation-License before the registry sees it
            answer = self.console_client.request(spec["method"], spec["console_path"], params=spec.get("params"),
                                                 json=spec.get("json"), headers=headers)
            lane = "console"
        try:
            body = answer.json()
        except ValueError:
            body = answer.text[:2000]
        line = json.dumps({"status": answer.status_code, "lane": lane, "body": body})
        return subprocess.CompletedProcess(args, 0, stdout=f"INFO svid initialised\nTP_PARENT_CALL {line}\n", stderr="")


@pytest.fixture
def operator(tmp_path, monkeypatch):
    """An operator stack directory, the CLI's HOME, and the parent wired in for the old path (the CLI's own HTTP
    client to the console URL) and the new one (the registry container)."""
    d = tmp_path / "cloud-op-amsterdam"
    d.mkdir()
    (d / "docker-compose.operator.yml").write_text("services: {}\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TP_OPERATOR_REMOTE_AUDIT", raising=False)

    def setup(licence=ACTIVE, operator_active=True, lane=True, registry_licence=None):
        (d / ".env.operator").write_text(f"REGISTRY_NAME=amsterdam\nFEDERATION_LICENSE_KEY={licence}\n"
                                         f"CENTRAL_REGISTRY_URL=https://eu.parent.test\n")
        app = parent(operator_active)
        container = Container(app, registry_licence or licence, lane)
        try:
            from tp_operator import parent_call
            monkeypatch.setattr(parent_call, "compose_exec", container)
        except ImportError:           # the code before CB-228 has no parent_call: its commands use the client below
            pass

        def _client(**_kw):           # the CLI's own HTTP client, as the old commands used it, reaching the console
            return TestClient(console(app), base_url="https://eu.parent.test", raise_server_exceptions=False)
        monkeypatch.setattr(http_client, "httpx", SimpleNamespace(Client=_client, Timeout=httpx.Timeout))
        return app, container

    return d / ".env.operator", setup


def run(env_path, *verb):
    result = CliRunner().invoke(cli, ["--config", str(env_path), "--json", *verb])
    try:
        body = json.loads(result.stdout)
    except ValueError:
        body = {"_raw": result.stdout}
    return result.exit_code, body


def test_a_revoked_licence_is_not_verified(operator):
    env, setup = operator
    setup(licence=REVOKED)
    code, out = run(env, "license", "verify")
    assert out.get("verified") is False, out
    assert code == 2, out
    assert "Invalid or revoked federation license" in out.get("reason", ""), out


def test_an_active_licence_is_verified_by_the_parent_on_its_lane(operator):
    env, setup = operator
    app, _ = setup(licence=ACTIVE)
    code, out = run(env, "license", "verify")
    assert code == 0 and out.get("verified") is True, out
    assert out.get("lane") == "federation lane", out
    assert ("/api/v1/federation/operator-self/logs", True, True) in app.state.seen


def test_the_probe_is_never_a_route_that_checks_nothing(operator):
    env, setup = operator
    app, _ = setup(licence=REVOKED)
    run(env, "license", "verify")
    assert app.state.seen, "the parent was never asked"
    assert not any(path == "/api/v1/federation/info" for path, _, _ in app.state.seen), app.state.seen


def test_without_the_lane_the_console_never_receives_the_licence_and_says_so(operator):
    env, setup = operator
    setup(licence=ACTIVE, lane=False)
    code, out = run(env, "license", "verify")
    assert code == 2 and out.get("verified") is False, out
    assert "did not receive the licence" in out.get("reason", ""), out


def test_the_licence_travels_on_stdin_never_in_the_arguments(operator):
    env, setup = operator
    _, container = setup(licence=ACTIVE)
    run(env, "license", "verify")
    run(env, "sync")
    assert container.argv and all(ACTIVE not in " ".join(a) for a in container.argv)
    assert container.stdin == [ACTIVE, ACTIVE]


def test_verify_checks_the_licence_in_env_operator_not_the_running_registrys(operator):
    """Between `license rotate` (the new key in .env.operator, the old one revoked) and the registry's restart, the
    container still holds the old key; `license verify` is the runbook's check of the NEW one."""
    env, setup = operator
    setup(licence=ACTIVE, registry_licence=REVOKED)
    code, out = run(env, "license", "verify")
    assert code == 0 and out.get("verified") is True, out


def test_the_container_reads_stdin_first_and_its_own_key_second():
    from tp_operator.parent_call import SCRIPT
    assert 'sys.stdin.read().strip() or (os.environ.get("FEDERATION_LICENSE_KEY")' in SCRIPT


def test_sync_asks_the_parent_on_its_lane_and_reports_it(operator):
    env, setup = operator
    app, _ = setup(licence=ACTIVE)
    code, out = run(env, "sync")
    assert code == 0 and out.get("triggered") is True, out
    assert out.get("lane") == "federation lane"
    assert ("/api/v1/federation/sync/trigger", True, True) in app.state.seen


def test_a_refused_sync_is_a_failure(operator):
    env, setup = operator
    setup(licence=ACTIVE, operator_active=False)
    code, out = run(env, "sync")
    assert out.get("triggered") is False, out
    assert code == 3, out
    assert "403" in out.get("reason", "") and "not active" in out.get("reason", ""), out


def test_a_sync_the_parent_never_ran_is_not_reported_as_done(operator):
    env, setup = operator
    setup(licence=ACTIVE, lane=False)      # the licence alone, on the console: the trigger answers 401
    code, out = run(env, "sync")
    assert code == 3 and out.get("triggered") is False, out


def test_the_answer_line_is_found_among_the_containers_noise():
    from tp_operator.parent_call import parse_answer

    noise = 'INFO a\nTP_PARENT_CALL {"status": 1}\nWARNING b\nTP_PARENT_CALL {"status": 200, "lane": "console"}\n'
    assert parse_answer(noise) == {"status": 200, "lane": "console"}
    assert parse_answer("nothing here") is None and parse_answer("TP_PARENT_CALL not json") is None


def test_a_frame_is_told_it_has_no_parent_to_ask(tmp_path, monkeypatch):
    from tp_operator.commands.sync import _do_sync
    from tp_operator.config import OperatorContext

    called = []
    from tp_operator import parent_call
    monkeypatch.setattr(parent_call, "compose_exec", lambda *a, **k: called.append(a))
    frame = OperatorContext(name="juice", dir=tmp_path, env_path=tmp_path / ".env.frame-test", env={}, kind="frame")
    out = _do_sync(frame)
    assert out["triggered"] is False and "no parent" in out["reason"] and called == []


# ── SEC-08: `license rotate`, `spire enroll` and `spire revoke` ask through the registry, on the parent's lane ─────────


def invoke(env_path, *argv):
    """The CLI's exit code and its whole output (stdout and stderr; in --json mode an error is one plain line)."""
    result = CliRunner().invoke(cli, ["--config", str(env_path), "--json", *argv])
    return result.exit_code, result.output


def test_rotate_asks_the_parent_on_its_lane_and_writes_the_new_key(operator):
    env, setup = operator
    app, _ = setup(licence=ACTIVE)
    code, out = run(env, "--yes", "license", "rotate")
    assert code == 0, out
    assert out.get("lane") == "federation lane" and out.get("license_key_prefix") == NEW[:12] + "...", out
    assert NEW not in json.dumps(out), "the new key itself is never printed"
    assert f"FEDERATION_LICENSE_KEY={NEW}\n" in env.read_text()
    assert (ROTATE, True, True) in app.state.seen
    assert len(app.state.rotations) == 1 and 16 <= len(app.state.rotations[0]) <= 64, app.state.rotations


def test_rotate_carries_its_idempotency_key_and_the_licence_only_on_stdin(operator):
    env, setup = operator
    app, container = setup(licence=ACTIVE)
    run(env, "--yes", "license", "rotate")
    assert container.stdin == [ACTIVE]
    assert container.argv and all(ACTIVE not in " ".join(a) for a in container.argv)
    assert json.loads(container.argv[0][3])["headers"] == {"X-Idempotency-Key": app.state.rotations[0]}


def test_a_refused_rotation_writes_nothing_and_names_the_parents_reason(operator):
    env, setup = operator
    app, _ = setup(licence=REVOKED)
    before = env.read_text()
    code, text = invoke(env, "--yes", "license", "rotate")
    assert code == 3, text
    assert "HTTP 403" in text and "not active" in text, text
    assert app.state.rotations == [] and env.read_text() == before
    assert not list(env.parent.glob(".env.operator.bak-pre-rotate-*"))


def test_a_rotation_whose_answer_is_lost_says_the_key_may_have_changed(operator, monkeypatch):
    env, setup = operator
    setup(licence=ACTIVE)
    from tp_operator import parent_call
    monkeypatch.setattr(parent_call, "compose_exec",
                        lambda *a, **k: subprocess.CompletedProcess(a, 137, stdout="", stderr="killed\n"))
    before = env.read_text()
    code, text = invoke(env, "--yes", "license", "rotate")
    assert code == 3 and "no_answer" in text and "license verify" in text, text
    assert env.read_text() == before


def test_enroll_asks_the_parent_on_its_lane_with_the_operators_certificate(operator):
    env, setup = operator
    app, container = setup(licence=ACTIVE)
    code, out = run(env, "spire", "enroll", DID, "--parent-fingerprint", "ab12cd34")
    assert code == 0, out
    assert out.get("spiffe_id") == "spiffe://eu.parent.test/agent/" + DID.rsplit(":", 1)[-1], out
    assert out.get("lane") == "federation lane", out
    assert app.state.spire == [("register", DID, "ab12cd34", OPERATOR_SVID)]
    assert container.stdin == [ACTIVE] and all(ACTIVE not in " ".join(a) for a in container.argv)


def test_revoke_asks_the_parent_on_its_lane(operator):
    env, setup = operator
    app, _ = setup(licence=ACTIVE)
    code, out = run(env, "--yes", "spire", "revoke", DID)
    assert code == 0 and out.get("deleted") is True and out.get("lane") == "federation lane", out
    assert app.state.spire == [("delete", DID, None, OPERATOR_SVID)]


def test_a_refused_enrollment_makes_nothing_and_names_the_parents_reason(operator):
    env, setup = operator
    app, _ = setup(licence=ACTIVE, operator_active=False)
    code, text = invoke(env, "spire", "enroll", DID, "--parent-fingerprint", "ab12cd34")
    assert code == 3 and "HTTP 403" in text and "not active" in text, text
    assert app.state.spire == []


@pytest.mark.parametrize("verb", [("--yes", "license", "rotate"),
                                  ("spire", "enroll", DID, "--parent-fingerprint", "ab12cd34"),
                                  ("--yes", "spire", "revoke", DID)])
def test_without_the_lane_the_console_never_gets_the_licence_and_nothing_changes(operator, verb):
    env, setup = operator
    app, _ = setup(licence=ACTIVE, lane=False)
    before = env.read_text()
    code, text = invoke(env, *verb)
    assert code == 3, text
    assert app.state.rotations == [] and app.state.spire == [] and env.read_text() == before


@pytest.mark.parametrize("verb", [("--yes", "license", "rotate"),
                                  ("spire", "enroll", DID, "--parent-fingerprint", "ab12cd34"),
                                  ("--yes", "spire", "revoke", DID)])
def test_a_frame_is_told_it_has_no_parent_to_ask_and_sends_nothing(tmp_path, monkeypatch, verb):
    d = tmp_path / "juice-1788800000"
    d.mkdir()
    (d / ".env.frame-test").write_text(f"FEDERATION_LICENSE_KEY={ACTIVE}\nCENTRAL_REGISTRY_URL=https://eu.parent.test\n")
    (d / "docker-compose.frame-test.yml").write_text("services: {}\n")
    (d / "hetzner-demo-run.json").write_text(json.dumps({"name": "juice", "env_label": "sandbox"}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TP_OPERATOR_REMOTE_AUDIT", raising=False)
    sent = []
    from tp_operator import parent_call
    monkeypatch.setattr(parent_call, "compose_exec", lambda *a, **k: sent.append("registry container"))

    def _client(**_kw):              # the old path: the licence from the host to the parent URL
        sent.append("http")
        return TestClient(FastAPI(), base_url="https://eu.parent.test", raise_server_exceptions=False)
    monkeypatch.setattr(http_client, "httpx", SimpleNamespace(Client=_client, Timeout=httpx.Timeout))
    result = CliRunner().invoke(cli, ["--frame", str(d), "--json", *verb])
    assert result.exit_code == 1, result.output
    assert "no parent frame to ask" in result.output and sent == [], (result.output, sent)


# ── SEC-17: the global --timeout bounds every call the CLI asks through the registry ────────────────────────────────


@pytest.mark.parametrize("verb, own", [(("license", "verify"), 20.0),
                                       (("sync",), 60.0),
                                       (("--yes", "license", "rotate"), 15.0),
                                       (("spire", "enroll", DID, "--parent-fingerprint", "ab12cd34"), 30.0),
                                       (("--yes", "spire", "revoke", DID), 30.0)])
def test_the_global_timeout_reaches_the_parent_call(operator, verb, own):
    """--timeout is the parent call's HTTP timeout (the exec gets a minute more for docker itself); unset, each command
    keeps its own."""
    env, setup = operator
    _, container = setup(licence=ACTIVE)
    CliRunner().invoke(cli, ["--config", str(env), "--json", "--timeout", "7", *verb])
    CliRunner().invoke(cli, ["--config", str(env), "--json", *verb])
    assert container.timeouts == [(7.0, 67), (own, int(own) + 60)], container.timeouts


# ── the container's side of parent_call: SCRIPT itself, against a stub of the registry's modules ────────────────────

STUB_CALL_PARENT = '''
import httpx


def _echo(request):
    return httpx.Response(200, json={"headers": {k.lower(): v for k, v in request.headers.items()}})


async def _call_parent(db, method, console_path, lane_path, license_key, *, json_body=None, params=None, timeout=90.0):
    """The shape of routers/operator_portal_actions._call_parent: the licence alone, through httpx.AsyncClient.request
    (here to a transport that answers with the headers it received)."""
    headers = {"X-Federation-License": license_key}
    async with httpx.AsyncClient(timeout=timeout, transport=httpx.MockTransport(_echo)) as client:
        r = await client.request(method, "https://eu.parent.test:8443" + lane_path, json=json_body, params=params,
                                 headers=headers)
    return r, "federation lane"
'''


def _script_sends(tmp_path, headers):
    """Run parent_call.SCRIPT the way the registry container runs it (the spec in argv, the licence on stdin) over a
    stub agentvault_registry; the headers the parent received."""
    from tp_operator.parent_call import SCRIPT, parse_answer

    pkg = tmp_path / "agentvault_registry"
    (pkg / "routers").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "routers" / "__init__.py").write_text("")
    (pkg / "routers" / "operator_portal_actions.py").write_text(STUB_CALL_PARENT)
    (pkg / "database.py").write_text("import contextlib\n\n\n@contextlib.asynccontextmanager\n"
                                     "async def get_db_context():\n    yield None\n")
    spec = {"method": "POST", "console_path": ROTATE, "lane_path": ROTATE, "params": None,
            "json": {"reason": "scheduled_rotation"}, "headers": headers, "timeout": 5}
    path = os.pathsep.join(p for p in (str(tmp_path), os.environ.get("PYTHONPATH", "")) if p)
    r = subprocess.run([sys.executable, "-c", SCRIPT, json.dumps(spec)], input=ACTIVE, capture_output=True,
                       text=True, env={**os.environ, "PYTHONPATH": path}, timeout=60)
    answer = parse_answer(r.stdout)
    assert answer and answer.get("status") == 200, (r.stdout, r.stderr)
    return answer["body"]["headers"]


def test_the_container_adds_the_calls_headers_to_the_request_the_registry_makes(tmp_path):
    seen = _script_sends(tmp_path, {"X-Idempotency-Key": "rotate-0123456789abcdef0123456789abcdef"})
    assert seen.get("x-idempotency-key") == "rotate-0123456789abcdef0123456789abcdef", seen
    assert seen.get("x-federation-license") == ACTIVE, seen


def test_an_extra_header_never_replaces_the_licence_the_registry_sends(tmp_path):
    seen = _script_sends(tmp_path, {"X-Federation-License": REVOKED, "X-Idempotency-Key": "rotate-0123456789abcdef"})
    assert seen.get("x-federation-license") == ACTIVE, seen


def test_a_call_without_extra_headers_sends_the_licence_alone(tmp_path):
    seen = _script_sends(tmp_path, {})
    assert "x-idempotency-key" not in seen and seen.get("x-federation-license") == ACTIVE, seen


def test_a_lost_answer_never_repeats_an_answer_line(tmp_path, monkeypatch):
    """A rotation's answer carries the new key: when its line does not parse, the error never quotes it."""
    from tp_operator import parent_call
    from tp_operator.config import OperatorContext

    secret = "tp_fed_" + "c" * 64
    cut = parent_call.MARK + '{"status": 200, "lane": "federation lane", "body": {"license_key": "' + secret
    monkeypatch.setattr(parent_call, "compose_exec", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="INFO svid initialised\n" + cut + "\n", stderr=""))
    ctx = OperatorContext(name="amsterdam", dir=tmp_path, env_path=tmp_path / ".env.operator",
                          env={"FEDERATION_LICENSE_KEY": ACTIVE})
    answer = parent_call.call_parent(ctx, "POST", ROTATE, ROTATE)
    assert answer.get("error") == "no_answer" and secret not in json.dumps(answer), answer

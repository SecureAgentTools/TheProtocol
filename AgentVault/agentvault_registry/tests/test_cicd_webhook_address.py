"""D6-842 (2026-10-26, agentvault2-66): a CI/CD pipeline's webhook URL passes the developer webhook's address check, and
each deployment's send connects only to an address that check approved.

The pipeline's webhook URL was stored as given (create and update), and trigger_deployment POSTed each deployment to it
from the registry with a plain httpx call; the start of a failed answer was kept on the deployment, which its developer
reads back. Developer webhooks have refused an internal address since D6-760 and connected only to a checked one since
SEC-14; this path called neither. Now create and update refuse an internal URL with the canonical validator (400), and
_send_webhook goes through webhook_service.post_to_checked_address: a stored URL the check refuses (one stored before the
check, or a name that resolves internal by now) fails the deployment at once, with nothing sent and nothing retried.

DB-free: fake sessions record the writes; the resolver is a table whose answers for a name are taken in turn (as in
test_sec14_webhook_pinned_delivery.py), and the HTTP client's transport records the address each request reached. RED on
c7531675's agent_cicd_service.py and webhook_service.py: the internal URLs are stored, and the sends reach them.
"""
import asyncio
import ipaddress
import json
import logging
import socket
import types

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry import database
from agentvault_registry.services import agent_cicd_service as svc_mod

DID = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-000000000042"
PUBLIC = "93.184.216.34"   # a public address the export allows in a shipped file (its G13)
PAYLOAD = {"deployment_id": "dep-1", "agent_did": DID, "pipeline_name": "build", "pipeline_config": {"stages": []},
           "version": "1.0.0", "environment": "production", "callback_url": "https://api.example/cb"}
SIGNED = {"X-AgentVault-Signature": "sha256=" + "0" * 64}


class _Dns:
    """socket.getaddrinfo from a table; a name's answers are taken in turn, the last one kept."""

    def __init__(self):
        self.answers, self.asked = {}, []

    def __call__(self, host, port, *a, **k):
        self.asked.append(host)
        seq = self.answers.get(host)
        if not seq:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        addrs = seq.pop(0) if len(seq) > 1 else seq[0]
        return [((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, port, 0, 0)) if ":" in a
                 else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))) for a in addrs]


@pytest.fixture
def dns(monkeypatch):
    d = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", d)
    return d


@pytest.fixture
def wire(monkeypatch, dns):
    """Every request a send makes and the address it reached; `answer` maps an address to (status, text)."""
    seen, answer = [], {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            ipaddress.ip_address(host)
            reached = host
        except ValueError:   # a name: the client resolves it again before it connects
            reached = dns(host, request.url.port or 443)[0][4][0]
        seen.append({"reached": reached, "host": request.headers.get("host"),
                     "sni": request.extensions.get("sni_hostname"), "body": request.content,
                     "type": request.headers.get("content-type"),
                     "signature": request.headers.get("x-agentvault-signature")})
        status, text = answer.get(reached, (200, "ok"))
        return httpx.Response(status, text=text)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return types.SimpleNamespace(seen=seen, answer=answer)


@pytest.fixture(autouse=True)
def _service(monkeypatch):
    async def permission(db, agent_did, developer_id):
        return types.SimpleNamespace(did=agent_did)

    async def emit(*a, **k):
        return None

    monkeypatch.setattr(svc_mod.agent_cicd_service, "_get_agent_with_permission", permission)
    monkeypatch.setattr(svc_mod, "_emit_cicd_event", emit)


class _PipeDb:
    """The pipeline create and update queries: no duplicate name, the stored address, and every pipeline write."""

    def __init__(self, current_url=None):
        self.current_url, self.writes = current_url, []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT COUNT(*) FROM agent_pipelines"):
            return types.SimpleNamespace(scalar=lambda: 0)
        if sql.startswith("SELECT webhook_url FROM agent_pipelines"):
            row = (self.current_url,)
            return types.SimpleNamespace(first=lambda: row)
        if "agent_pipelines" in sql and sql.startswith(("INSERT", "UPDATE")):
            self.writes.append((sql.split()[0], dict(params or {})))
        return types.SimpleNamespace(first=lambda: None, scalar=lambda: None)

    async def commit(self):
        pass


def _create(db, url):
    data = {"pipeline_name": "build", "pipeline_config": {"stages": []}, "webhook_url": url}
    return asyncio.run(svc_mod.agent_cicd_service.create_pipeline(db, DID, data, 7))


def _update(db, **data):
    return asyncio.run(svc_mod.agent_cicd_service.update_pipeline(db, DID, "pipe-1", data, 7))


# ── the address check at create and update ─────────────────────────────────────────────────────────────────────────

INTERNAL = [
    ("http://127.0.0.1:8080/hook", {}),
    ("http://10.0.0.5/hook", {}),
    ("http://169.254.169.254/latest/meta-data", {}),
    ("http://[::ffff:127.0.0.1]/hook", {}),
    ("https://teg.internal.example/hook", {"teg.internal.example": [["172.16.0.7"]]}),
    ("https://half.example/hook", {"half.example": [[PUBLIC, "192.168.1.9"]]}),
]


@pytest.mark.parametrize("url,answers", INTERNAL)
def test_create_refuses_an_internal_webhook_url_and_stores_nothing(dns, url, answers):
    dns.answers.update({k: list(v) for k, v in answers.items()})
    db = _PipeDb()
    with pytest.raises(HTTPException) as e:
        _create(db, url)
    assert e.value.status_code == 400 and "Invalid webhook URL" in str(e.value.detail), e.value.detail
    assert db.writes == [], "nothing is stored"


def test_create_takes_a_public_url_and_one_that_resolves_to_nothing_yet(dns):
    dns.answers["ci.example"] = [[PUBLIC]]
    for url in ("https://ci.example/hook", "https://suite-ci.invalid/hook"):   # the console suite's address shape
        db = _PipeDb()
        out = _create(db, url)
        assert [w[0] for w in db.writes] == ["INSERT"] and db.writes[0][1]["webhook_url"] == url
        assert out.get("webhook_secret"), "the secret is returned once, as before"


def test_update_refuses_a_new_internal_address_and_writes_nothing(dns):
    db = _PipeDb(current_url="https://ci.example/hook")
    with pytest.raises(HTTPException) as e:
        _update(db, pipeline_name="build", webhook_url="http://10.1.2.3/x")
    assert e.value.status_code == 400 and db.writes == []


def test_update_keeps_an_unchanged_address_without_a_lookup(dns):
    # a URL stored before the check: an unrelated edit still saves; the send refuses it (below)
    db = _PipeDb(current_url="http://teg-layer:8080/api")
    _update(db, pipeline_name="renamed", webhook_url="http://teg-layer:8080/api")
    assert [w[0] for w in db.writes] == ["UPDATE"] and dns.asked == []


# ── the send ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Session:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        self.log.append((" ".join(str(stmt).split()), dict(params or {})))

    async def commit(self):
        pass


@pytest.fixture
def sessions(monkeypatch):
    log, slept = [], []

    async def sleep(delay, *a, **k):
        slept.append(delay)

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session(log))
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return types.SimpleNamespace(log=log, slept=slept)


def _send(url):
    asyncio.run(svc_mod.agent_cicd_service._send_webhook(None, "dep-1", url, PAYLOAD, dict(SIGNED)))


def _outcome(sessions):
    (sql, params), = sessions.log
    status = "running" if "status = 'running'" in sql else "failed" if "status = 'failed'" in sql else sql
    return status, params.get("error")


def test_a_deployment_reaches_the_checked_address_named_for_the_pipelines_host(dns, wire, sessions):
    dns.answers["ci.example"] = [[PUBLIC], ["127.0.0.1"]]   # public when checked, internal when asked again
    _send("https://ci.example/deploy")
    (sent,) = wire.seen
    assert sent["reached"] == PUBLIC, f"the send reached {sent['reached']}, an address nobody checked"
    assert (sent["host"], sent["sni"]) == ("ci.example", "ci.example")
    assert json.loads(sent["body"]) == PAYLOAD and sent["type"] == "application/json"
    assert sent["signature"] == SIGNED["X-AgentVault-Signature"], "the signed request is unchanged"
    assert dns.asked == ["ci.example"] and _outcome(sessions) == ("running", None)


def test_a_stored_internal_url_fails_the_deployment_at_once_and_nothing_is_sent(dns, wire, sessions):
    dns.answers["teg-layer"] = [["172.16.0.5"]]
    _send("http://teg-layer:8080/api")
    assert wire.seen == [], "nothing reached the internal address"
    status, error = _outcome(sessions)
    assert status == "failed" and "refused (no retry): Webhook URL refused" in error, error
    assert sessions.slept == [], "a refusal is not retried"


def test_a_name_that_turns_internal_after_the_save_is_refused_at_the_send(dns, wire, sessions):
    dns.answers["flip.example"] = [[PUBLIC], ["10.0.0.9"]]
    db = _PipeDb()
    _create(db, "https://flip.example/hook")                 # checked when saved: public then
    _send("https://flip.example/hook")                       # internal by the time it is sent
    assert [w[0] for w in db.writes] == ["INSERT"] and wire.seen == []
    assert _outcome(sessions)[0] == "failed"


def test_control_a_public_endpoints_own_4xx_is_recorded_as_before(dns, wire, sessions):
    dns.answers["ci.example"] = [[PUBLIC]]
    wire.answer[PUBLIC] = (404, "no such pipeline")
    _send("https://ci.example/deploy")
    assert len(wire.seen) == 1
    assert _outcome(sessions) == ("failed", "Webhook delivery exhausted: 4xx (no retry): 404 no such pipeline")


# ── the send task is held until it finishes ──────────────────────────────────────────────────────────────────────

def test_a_background_task_is_held_until_it_finishes_and_a_failure_is_logged(caplog):
    async def run():
        gate = asyncio.Event()

        async def waits():
            await gate.wait()

        async def fails():
            raise RuntimeError("boom")

        held = svc_mod._spawn(waits())
        failed = svc_mod._spawn(fails())
        assert {held, failed} <= svc_mod._BACKGROUND_TASKS
        await asyncio.gather(failed, return_exceptions=True)
        await asyncio.sleep(0)
        assert failed not in svc_mod._BACKGROUND_TASKS and held in svc_mod._BACKGROUND_TASKS
        gate.set()
        await held
        await asyncio.sleep(0)
        assert held not in svc_mod._BACKGROUND_TASKS

    with caplog.at_level(logging.WARNING, logger=svc_mod.logger.name):
        asyncio.run(run())
    assert any("background task failed" in r.getMessage() and "boom" in r.getMessage() for r in caplog.records)


# ── a bundle restore keeps a refused address out of the store ─────────────────────────────────────────────────────

class _NoRows:
    def first(self):
        return None

    def scalar(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []

    def mappings(self):
        return self

    @property
    def rowcount(self):
        return 1


class _RestoreDb:
    """The restore's queries: no rows anywhere, and each pipeline insert recorded."""

    def __init__(self):
        self.pipelines = []

    async def execute(self, stmt, params=None):
        if "INSERT INTO agent_pipelines" in str(stmt):
            self.pipelines.append(dict(params or {}))
        return _NoRows()

    async def commit(self):
        pass

    async def rollback(self):
        pass


def test_a_bundle_restore_stores_no_refused_address_and_says_why(dns, monkeypatch):
    from agentvault_registry.routers import onboarding
    from agentvault_registry.services.bundles import service as S

    async def no_clash(db, did):
        return False

    dns.answers["ci.example"] = [[PUBLIC]]
    pipelines = [{"pipeline_name": "inside", "webhook_url": "http://10.0.0.5/hook"},
                 {"pipeline_name": "outside", "webhook_url": "https://ci.example/hook"}]
    payload = {"did": DID, "name": "Restored", "agent_card": {}, "pipelines": pipelines}
    monkeypatch.setattr(S.fmt, "unpack_bundle", lambda data: ({"exporter": {}}, [payload], None, []))
    monkeypatch.setattr(onboarding, "did_is_taken", no_clash)
    db = _RestoreDb()
    out = asyncio.run(S.restore_bundle(db=db, installer_dev_id=8, uploaded_bytes=b"tpb", conflict_resolution="rename"))
    assert {p["pname"]: p["wurl"] for p in db.pipelines} == {"inside": None, "outside": "https://ci.example/hook"}
    (said,) = [w for w in out["warnings"] if "webhook URL refused" in w]
    assert said.startswith("Pipeline 'inside': webhook URL refused: ") and said.endswith(
        "; the pipeline restored without it"), said

"""V0664 consoles (C2, gwo_ebaafc5c4af1fa3a6858e55d): a proxy reports its status to its registry, opt-in.

`service: {report_every_s: N}` in the spec turns it on (absent = off; `tp-proxy init` writes 300). The running proxy posts, as its own
agent, to POST /api/v1/agents/me/proxy-status:

  {name, sdk_version, uptime_s,
   mappings: {<name>: {pending, done, dead, paused, breaker}},      breaker: the state's NAME ("stopped", "cooling") or null
   sources:  {<name>: {finished, last_read_at}}}                    last_read_at: UTC ISO text of the newest record read, or null

Names and counts only: never a record, a config value, a secret, or the text of an error (a test puts a sentinel in each place and
finds it nowhere in what was posted). A failed post is logged once per hour and changes nothing else (the records are still sent).
RED on the base v0664/stack-cut 300a3bed: the spec has no report_every_s and the runtime posts nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

import proxy_fake as F
from theprotocol import __version__

PATH = "/api/v1/agents/me/proxy-status"
SENTINELS = ["SECRET-RECORD-VALUE-77", "SECRET-CONFIG-VALUE-88", "SECRET-ERROR-TEXT-99"]


class StatusRegistry(F.FakeRegistry):
    """The fake registry plus the status route: it keeps what was posted, as the registry keeps one row per agent."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.status_mode = 200
        self.posted = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == PATH and request.method == "POST":
            self.calls.append({"method": "POST", "path": PATH, "key": request.headers.get("idempotency-key"),
                               "auth": request.headers.get("authorization", "")})
            if not self._authorized(request):
                return httpx.Response(401, json={"detail": "Could not validate credentials"})
            if self.status_mode != 200:
                return httpx.Response(self.status_mode, json={"detail": "not now"})
            self.posted.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        return super().handle(request)


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
    monkeypatch.setitem(plugins.BUILTINS["sink"], "list_sink", "proxy_fake:ListSink")


def _proxy(tmp_path, reg, doc=None, **kw):
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    spec = parse(doc or F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}]), base=tmp_path)
    return Proxy(spec, transport=reg.transport, service=False, poll_s=0.01, **kw)


async def _drain(p):
    await asyncio.wait_for(p.run(until_idle=True), timeout=10)


# ── the spec ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_report_every_s_is_a_number_of_at_least_ten(tmp_path):
    from theprotocol.proxy.spec import SpecError, parse
    doc = F.spec_doc(tmp_path, service={"enabled": False, "report_every_s": 300})
    assert parse(doc, base=tmp_path).service["report_every_s"] == 300
    for bad in (5, 0, -1, "300", True):
        with pytest.raises(SpecError) as e:
            parse(F.spec_doc(tmp_path, service={"enabled": False, "report_every_s": bad}), base=tmp_path)
        assert "report_every_s" in str(e.value)


def test_it_needs_an_agent_to_report_as(tmp_path):
    from theprotocol.proxy.spec import SpecError, parse
    doc = F.spec_doc(tmp_path, service={"enabled": False, "report_every_s": 60})
    doc.pop("identity")
    doc["actions"] = {}
    doc["sinks"] = {"out": {"type": "list_sink", "config": {}}}
    doc["mappings"] = [{"name": "m", "version": 1, "from": "feed", "to": "out", "fields": {"v": "$.payload.v"}}]
    with pytest.raises(SpecError) as e:
        parse(doc, base=tmp_path)
    assert "report_every_s" in str(e.value) and "identity" in str(e.value)


def test_init_writes_300_into_the_spec_it_creates():
    from theprotocol.proxy.cli import SKELETON
    assert "report_every_s: 300" in SKELETON.format(title="t", secret_file="s", name="n", registry="r", did="d",
                                                    client_id="c", client_secret="x")


# ── off by default, and never in a dry run ──────────────────────────────────────────────────────────────────────

async def test_absent_means_off(tmp_path):
    reg = StatusRegistry()
    p = _proxy(tmp_path, reg)
    await _drain(p)
    await asyncio.sleep(0.1)
    assert reg.posted == [] and [c for c in reg.calls if c["path"] == PATH] == []
    p.close()


async def test_a_dry_run_reports_nothing(tmp_path):
    reg = StatusRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}], service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, dry_run=True, report_every_s=0.02)
    await _drain(p)
    await asyncio.sleep(0.1)
    assert reg.posted == []
    p.close()


# ── the report ──────────────────────────────────────────────────────────────────────────────────────────────────

async def test_it_posts_as_its_own_agent_with_the_documented_shape(tmp_path):
    reg = StatusRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}, {"id": "r2", "v": 2}], service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02)
    await _drain(p)
    await asyncio.sleep(0.15)
    assert reg.posted, "nothing was posted"
    last = reg.posted[-1]
    assert set(last) == {"name", "sdk_version", "uptime_s", "mappings", "sources"}
    assert last["name"] == "proxy-test" and last["sdk_version"] == __version__ and last["uptime_s"] >= 0
    assert last["mappings"] == {"reading": {"pending": 0, "done": 2, "dead": 0, "paused": False, "breaker": None}}
    src = last["sources"]["feed"]
    assert set(src) == {"finished", "last_read_at"} and src["finished"] is True
    assert src["last_read_at"].endswith("Z") and "T" in src["last_read_at"]
    call = next(c for c in reg.calls if c["path"] == PATH)
    assert call["auth"].startswith("Bearer ") and call["key"]                  # the agent's own token, and a write's key
    p.close()


async def test_a_source_that_has_read_nothing_has_no_last_read(tmp_path):
    reg = StatusRegistry()
    doc = F.spec_doc(tmp_path, items=[], service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02)
    await _drain(p)
    await asyncio.sleep(0.1)
    assert reg.posted[-1]["sources"]["feed"]["last_read_at"] is None
    p.close()


async def test_a_stopped_mapping_reports_its_breaker_state_name_only(tmp_path):
    reg = StatusRegistry()
    reg.mode = "refuse"                                                          # the attestation route refuses: the breaker trips
    items = [{"id": f"r{i}", "v": i} for i in range(6)]
    doc = F.spec_doc(tmp_path, items=items, service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02)
    await asyncio.wait_for(p.run(until_idle=True), timeout=10)
    await asyncio.sleep(0.1)
    m = reg.posted[-1]["mappings"]["reading"]
    assert m["breaker"] == "stopped" and m["dead"] >= 1
    assert "Agent lacks permission" not in json.dumps(reg.posted)                # the refusal's text is not in a report
    p.close()


async def test_a_pause_is_reported(tmp_path):
    reg = StatusRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}], service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02)
    p.outbox.set_switch("pause:reading", True)
    await p.start()
    await asyncio.sleep(0.1)
    assert reg.posted and reg.posted[-1]["mappings"]["reading"]["paused"] is True
    await p.stop()
    p.close()


# ── names and counts only ───────────────────────────────────────────────────────────────────────────────────────

async def test_no_record_no_config_value_no_secret_and_no_error_text_is_ever_posted(tmp_path):
    reg = StatusRegistry(client_secret="s3cr3t-proxy-client-secret-value")
    reg.mode = "refuse"
    items = [{"id": f"r{i}", "v": 1, "note": SENTINELS[0]} for i in range(5)]
    doc = F.spec_doc(tmp_path, items=items, service={"enabled": False, "report_every_s": 10})
    doc["sources"]["feed"]["config"]["label"] = SENTINELS[1]                      # a config value
    doc["mappings"][0]["fields"]["note"] = "$.payload.note"
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02)
    await asyncio.wait_for(p.run(until_idle=True), timeout=10)
    await asyncio.sleep(0.1)
    p.outbox.set_switch("breaker:reading", {"state": "stopped", "why": SENTINELS[2], "refusals": 3, "since": 1.0, "until": None})
    await asyncio.sleep(0.1)
    body = json.dumps(reg.posted)
    assert reg.posted
    for s in SENTINELS + [F.CLIENT_SECRET, F.CLIENT_ID, F.DID, "registry.test"]:
        assert s not in body, s
    p.close()


# ── a failed post ───────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_failed_post_is_logged_once_an_hour_and_changes_nothing_else(tmp_path, caplog):
    now = [1_000_000.0]
    reg = StatusRegistry()
    reg.status_mode = 503
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}, {"id": "r2", "v": 2}], service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02, clock=lambda: now[0])
    stop = asyncio.Event()
    runner = asyncio.ensure_future(p.run(stop=stop))                                # it keeps running: the reports keep coming
    try:
        with caplog.at_level(logging.WARNING, logger="theprotocol.proxy"):
            await asyncio.sleep(0.3)                                                # many failed posts in the same hour
            posts = [c for c in reg.calls if c["path"] == PATH]
            assert len(posts) >= 3
            assert len(reg.effects) == 2 and p.outbox.counts()["done"] == 2         # the records were attested all the same
            first = [r for r in caplog.records if "status report" in r.getMessage()]
            assert len(first) == 1
            now[0] += 3601                                                          # an hour later, it says so once more
            await asyncio.sleep(0.2)
            again = [r for r in caplog.records if "status report" in r.getMessage()]
            assert len(again) == 2
        assert SENTINELS[2] not in caplog.text
    finally:
        stop.set()
        await asyncio.wait_for(runner, timeout=10)
    p.close()


async def test_a_registry_that_has_no_such_route_is_not_an_error_for_the_proxy(tmp_path):
    reg = StatusRegistry()
    reg.status_mode = 404                                                          # an older registry
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}], service={"enabled": False, "report_every_s": 10})
    p = _proxy(tmp_path, reg, doc, report_every_s=0.02)
    await _drain(p)
    assert len(reg.effects) == 1
    p.close()

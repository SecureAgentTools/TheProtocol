"""§FRAMEPROV P5 (2026-09-13): the frame runner owns the four DNS names of the frames it builds, and nothing else.

A fake Cloudflare API (a real HTTP server on localhost that checks the bearer token), a fake `dig` whose answers a test
flips, a fake certbot, and the P2 rig's fake driver and teardown. Nothing here touches Cloudflare, nginx or /etc.
"""
import http.server
import importlib.util
import json
import os
import pathlib
import sys
import threading
import time
import urllib.parse
import uuid

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_p5", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)
_base_spec = importlib.util.spec_from_file_location("frame_runner_p2_tests", HERE / "test_frame_runner.py")
base = importlib.util.module_from_spec(_base_spec)
_base_spec.loader.exec_module(base)

TOKEN = "cf-test-token-" + "0123456789abcdef" * 2
IPV4 = "203.0.113.10"
DOMAIN = "theprotocol.cloud"
FAKE_DIG = r'''#!/usr/bin/env python3
import json, os, sys
answers = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dig_answers.json")))
host, rtype = sys.argv[-2], sys.argv[-1]
if rtype == "A":
    print("\n".join(answers.get(host, [])))
'''
FAKE_CERTBOT = '#!/bin/bash\necho "$@" >> "$(dirname "$0")/certbot_calls.txt"\nexit 0\n'


class FakeCloudflare:
    """The zone as the runner sees it: records by id, every call recorded, a wrong bearer answered 403."""

    def __init__(self):
        self.records, self.calls = {}, []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, doc):
                body = json.dumps(doc).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                if self.headers.get("Authorization") == f"Bearer {TOKEN}":
                    return True
                self._send(403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
                return False

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                fake.calls.append(("GET", url.path))
                if self._authorized():
                    name = urllib.parse.parse_qs(url.query).get("name", [""])[0]
                    self._send(200, {"success": True, "errors": [],
                                     "result": [r for r in fake.records.values() if r["name"] == name]})

            def do_POST(self):
                fake.calls.append(("POST", self.path))
                if self._authorized():
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                    rid = uuid.uuid4().hex
                    fake.records[rid] = {"id": rid, **body}
                    self._send(200, {"success": True, "errors": [], "result": fake.records[rid]})

            def do_DELETE(self):
                fake.calls.append(("DELETE", self.path))
                if self._authorized():
                    rid = self.path.rsplit("/", 1)[1]
                    if fake.records.pop(rid, None) is None:
                        self._send(404, {"success": False, "errors": [{"code": 81044, "message": "Record does not exist."}]})
                    else:
                        self._send(200, {"success": True, "errors": [], "result": {"id": rid}})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}/client/v4"

    def seed(self, name, rtype="A", content="198.51.100.7"):
        rid = uuid.uuid4().hex
        self.records[rid] = {"id": rid, "type": rtype, "name": name, "content": content, "proxied": False}
        return rid

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def rig(tmp_path):
    (tmp_path / "stack").mkdir()
    (tmp_path / "standup_driver.py").write_text(base.FAKE_DRIVER)
    for name, text in (("teardown_hetzner_frame.sh", base.FAKE_TEARDOWN), ("dig", FAKE_DIG), ("certbot", FAKE_CERTBOT)):
        (tmp_path / name).write_text(text)
        (tmp_path / name).chmod(0o755)
    (tmp_path / "dig_answers.json").write_text("{}")
    token = tmp_path / "cloudflare.token"
    token.write_text(TOKEN + "\n")
    token.chmod(0o600)
    plist = tmp_path / "protected-frames.list"
    plist.write_text("# fixture\neu\nasia\n")
    cf = FakeCloudflare()
    cfg = fr.Config(conf={"images": {"registry": ["agentvault2-registry-a:v0359"], "teg": ["agentvault2-teg-layer:v0351"]},
                          "allowed_uids": [os.getuid()], "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0,
                          "dns": {"zone_id": "zone1", "ipv4": IPV4, "token_file": str(token), "api": cf.api,
                                  "resolver": "1.1.1.1", "propagation_timeout_s": 20, "poll_interval_s": 0.2}},
                    socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "standup_driver.py"), teardown=str(tmp_path / "teardown_hetzner_frame.sh"),
                    python=sys.executable, stack_root=str(tmp_path / "stack"), protected_list=str(plist),
                    dig=str(tmp_path / "dig"), certbot=str(tmp_path / "certbot"), letsencrypt=str(tmp_path / "letsencrypt"))
    srv = fr.make_server(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield cfg, srv, tmp_path, cf
    active = srv.runner.active()
    if active and active.get("pid"):
        fr.os.killpg(active["pid"], 9)
    srv.shutdown()
    srv.server_close()
    cf.server.shutdown()


def call(cfg, **req):
    return fr.call(cfg.socket, req, timeout=60)


def spec(name):
    return {**base.SPEC, "name": name}


def resolve_all(tmp_path, name):
    answers = json.loads((tmp_path / "dig_answers.json").read_text())
    answers.update({host: [IPV4] for host in fr.frame_dns.names(name, DOMAIN)})
    (tmp_path / "dig_answers.json").write_text(json.dumps(answers))


def driver_runs(tmp_path):
    if not (tmp_path / "calls.jsonl").exists():
        return []
    return [c for c in base.calls(tmp_path) if "--plan" not in c["argv"]]


def until(check, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.1)
    raise AssertionError("the condition never held")


def wait_state(cfg, job_id, states=("succeeded", "failed", "cancelled", "lost"), timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = call(cfg, op="status", job_id=job_id)["result"]["job"]
        if rec["state"] in states:
            return rec
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never reached {states}")


def test_a_plan_passes_acme_and_names_the_hosts_the_runner_would_create(rig):
    cfg, _, tmp, cf = rig
    r = call(cfg, op="plan", spec=spec("gamma"))["result"]
    assert r["plan_ok"] is True, r["plan"]
    dns = r["plan"]["derived"]["dns_runner"]
    assert dns["state"] == "absent" and [h["host"] for h in dns["hosts"]] == fr.frame_dns.names("gamma", DOMAIN)
    assert any(w.startswith("the frame runner creates gamma.theprotocol.cloud") for w in r["plan"]["warnings"])
    argv = base.calls(tmp)[-1]["argv"]
    assert "--acme" in argv and "--dns-by-runner" in argv
    assert cf.writes() == []
    assert call(cfg, op="ping")["result"]["dns_managed"] is True


def test_a_host_with_a_record_the_runner_did_not_create_is_refused_and_never_adopted(rig):
    cfg, _, tmp, cf = rig
    cf.seed("taken-es.theprotocol.cloud")
    r = call(cfg, op="plan", spec=spec("taken"))["result"]
    assert r["plan_ok"] is False
    assert any("taken-es.theprotocol.cloud already has a record the runner did not create" in x for x in r["plan"]["refusals"])
    started = call(cfg, op="standup", spec=spec("taken"))["result"]
    assert started["started"] is False
    refused = call(cfg, op="dns_ensure", name="taken")
    assert refused["ok"] is False and "never adopted" in refused["refused"]
    assert cf.writes() == [] and len(cf.records) == 1


def test_a_host_that_resolves_without_a_record_is_refused(rig):
    cfg, _, tmp, cf = rig
    (tmp / "dig_answers.json").write_text(json.dumps({"echo-push.theprotocol.cloud": ["198.51.100.9"]}))
    r = call(cfg, op="plan", spec=spec("echo"))["result"]
    assert r["plan_ok"] is False
    assert any("echo-push.theprotocol.cloud already resolves at 1.1.1.1" in x for x in r["plan"]["refusals"])
    assert cf.writes() == []


def test_without_its_token_the_runner_refuses_the_plan_and_asks_the_zone_nothing(rig):
    cfg, _, tmp, cf = rig
    os.remove(cfg.dns["token_file"])
    r = call(cfg, op="plan", spec=spec("gamma"))["result"]
    assert r["plan_ok"] is False
    assert any(x.startswith("DNS automation: no readable Cloudflare token") for x in r["plan"]["refusals"])
    assert cf.calls == []


def test_the_token_is_read_in_place_from_certbots_credential_file(rig):
    # His word 2026-09-13: the runner uses the token that already issues the operators' certificates, read where certbot
    # keeps it, so there is one carrier to rotate.
    cfg, _, tmp, cf = rig
    ini = tmp / "cloudflare.ini"
    ini.write_text(f"# certbot-dns-cloudflare\ndns_cloudflare_api_token = {TOKEN}\n")
    ini.chmod(0o600)
    cfg.dns["token_file"] = str(ini)
    assert call(cfg, op="dns_status", name="gamma")["result"]["state"] == "absent"
    ini.write_text("dns_cloudflare_email = someone@example.test\ndns_cloudflare_api_key = not-a-scoped-token\n")
    refused = call(cfg, op="dns_status", name="gamma")
    assert refused["ok"] is False and refused["refused"] == f"{ini} does not hold one Cloudflare token"


def test_a_standup_creates_four_marked_records_waits_for_the_resolver_then_runs_the_driver(rig):
    cfg, _, tmp, cf = rig
    started = call(cfg, op="standup", spec=spec("gamma"))["result"]
    assert started["started"] is True
    job = started["job"]["id"]
    made = sorted(cf.records.values(), key=lambda r: r["name"])
    assert [r["name"] for r in made] == sorted(fr.frame_dns.names("gamma", DOMAIN))
    assert {(r["type"], r["content"], r["proxied"], r["comment"]) for r in made} == {("A", IPV4, False, f"frame-runner:gamma:{job}")}
    held = json.loads((tmp / "state" / "dns" / "gamma.json").read_text())
    assert {r["id"] for r in held["records"]} == set(cf.records)
    time.sleep(1.0)                                            # the resolver has not answered: the driver has not run
    assert driver_runs(tmp) == []
    assert call(cfg, op="ping")["result"]["active"] == job     # the waiting wrapper is the job the runner watches
    resolve_all(tmp, "gamma")
    assert wait_state(cfg, job)["state"] == "succeeded"
    events = call(cfg, op="events", job_id=job)["result"]["events"]
    assert [(e["step"], e["event"]) for e in events[:2]] == [("dns", "start"), ("dns", "end")]
    assert len(driver_runs(tmp)) == 1 and "--acme" in driver_runs(tmp)[0]["argv"]
    until(lambda: call(cfg, op="status")["result"]["frames"])
    frame = call(cfg, op="status")["result"]["frames"][0]
    assert frame["name"] == "gamma" and frame["dns_managed"] is True


def test_a_resolver_that_never_answers_fails_the_job_before_the_driver_and_a_retry_reuses_the_records(rig):
    cfg, _, tmp, cf = rig
    cfg.dns["propagation_timeout_s"] = 1
    first = call(cfg, op="standup", spec=spec("gamma"))["result"]
    rec = wait_state(cfg, first["job"]["id"])
    assert rec["state"] == "failed" and driver_runs(tmp) == []
    last = call(cfg, op="status", job_id=rec["id"])["result"]["last_event"]
    assert (last["step"], last["event"]) == ("dns", "fail") and "still do not resolve at 1.1.1.1" in last["sentence"]
    assert len(cf.records) == 4
    cfg.dns["propagation_timeout_s"] = 20
    again = call(cfg, op="standup", spec=spec("gamma"))["result"]
    assert again["started"] is True and len(cf.records) == 4 and len(cf.writes()) == 4
    resolve_all(tmp, "gamma")
    assert wait_state(cfg, again["job"]["id"])["state"] == "succeeded"


def test_teardown_deletes_only_the_runners_records_and_the_certificate_it_issued(rig):
    cfg, _, tmp, cf = rig
    job = call(cfg, op="standup", spec=spec("gamma"))["result"]["job"]["id"]
    resolve_all(tmp, "gamma")          # the resolver answers once the runner's records exist, never before
    assert wait_state(cfg, job)["state"] == "succeeded"
    until(lambda: call(cfg, op="status")["result"]["frames"])
    other = cf.seed("gamma-legacy.theprotocol.cloud")            # a gamma-like name the runner never made
    renewal = tmp / "letsencrypt" / "renewal"
    renewal.mkdir(parents=True)
    (renewal / "gamma.theprotocol.cloud.conf").write_text("# what --acme leaves behind for a certificate it issued\n")
    teardown = call(cfg, op="teardown", name="gamma")["result"]["job"]["id"]
    assert wait_state(cfg, teardown)["state"] == "succeeded"
    until(lambda: list(cf.records) == [other])
    until(lambda: not (tmp / "state" / "dns" / "gamma.json").exists())
    until(lambda: (tmp / "certbot_calls.txt").exists())
    assert (tmp / "certbot_calls.txt").read_text().split() == ["delete", "--non-interactive", "--cert-name", "gamma.theprotocol.cloud"]


def test_a_frame_whose_standup_issued_no_certificate_asks_certbot_nothing(rig):
    # §FRAMEPROV P4 (2026-09-13): plum's standup stopped at `emission`, before --acme issued anything; its teardown must
    # say no certificate was issued instead of reporting certbot's refusal to delete one that does not exist.
    cfg, _, tmp, cf = rig
    job = call(cfg, op="standup", spec=spec("gamma"))["result"]["job"]["id"]
    resolve_all(tmp, "gamma")
    assert wait_state(cfg, job)["state"] == "succeeded"
    until(lambda: call(cfg, op="status")["result"]["frames"])
    teardown = call(cfg, op="teardown", name="gamma")["result"]["job"]["id"]
    assert wait_state(cfg, teardown)["state"] == "succeeded"
    record = tmp / "state" / "jobs" / teardown / "frame.json"
    until(record.exists)
    assert json.loads(record.read_text())["cert_cleanup"] == "none issued"
    assert not (tmp / "certbot_calls.txt").exists() and list(cf.records) == []


def test_dns_ensure_is_idempotent_and_dns_remove_leaves_a_record_a_human_changed(rig):
    cfg, _, tmp, cf = rig
    first = call(cfg, op="dns_ensure", name="delta")["result"]
    assert len(first["created"]) == 4
    second = call(cfg, op="dns_ensure", name="delta")["result"]
    assert second["created"] == [] and len(second["present"]) == 4 and len(cf.records) == 4
    touched = next(r for r in cf.records.values() if r["name"] == "delta-spire.theprotocol.cloud")
    touched["comment"] = "kept by hand"
    out = call(cfg, op="dns_remove", name="delta")["result"]
    assert len(out["deleted"]) == 3 and len(out["kept"]) == 1 and "left alone" in out["kept"][0]
    assert [r["name"] for r in cf.records.values()] == ["delta-spire.theprotocol.cloud"]
    status = call(cfg, op="dns_status", name="delta")["result"]
    assert status["state"] == "refused" and any("did not create" in p for p in status["problems"])


def test_dns_ops_refuse_protected_names_and_a_frame_the_runner_built(rig):
    cfg, _, tmp, cf = rig
    for op in ("dns_status", "dns_ensure", "dns_remove"):
        r = call(cfg, op=op, name="eu")
        assert r["ok"] is False and "protected" in r["refused"], (op, r)
    job = call(cfg, op="standup", spec=spec("gamma"))["result"]["job"]["id"]
    resolve_all(tmp, "gamma")          # the resolver answers once the runner's records exist, never before
    assert wait_state(cfg, job)["state"] == "succeeded"
    until(lambda: call(cfg, op="status")["result"]["frames"])
    r = call(cfg, op="dns_remove", name="gamma")
    assert r["ok"] is False and "its teardown deletes its DNS" in r["refused"]
    assert [c for c in cf.calls if c[0] == "DELETE"] == []


def test_the_token_never_leaves_its_file(rig):
    cfg, _, tmp, cf = rig
    job = call(cfg, op="standup", spec=spec("gamma"))["result"]["job"]["id"]
    resolve_all(tmp, "gamma")          # the resolver answers once the runner's records exist, never before
    assert wait_state(cfg, job)["state"] == "succeeded"
    until(lambda: call(cfg, op="status")["result"]["frames"])
    teardown = call(cfg, op="teardown", name="gamma")["result"]["job"]["id"]
    assert wait_state(cfg, teardown)["state"] == "succeeded"
    until(lambda: not cf.records)
    files = [p for p in tmp.rglob("*") if p.is_file() and p.name != "cloudflare.token"]
    assert files and [str(p) for p in files if TOKEN in p.read_text(errors="ignore")] == []


# ── §PUSH (2026-10-06): one push name for a frame whose other names predate the runner ──────────────────────────────
def _answers(tmp_path, **hosts):
    answers = json.loads((tmp_path / "dig_answers.json").read_text())
    answers.update({h: v for h, v in hosts.items()})
    (tmp_path / "dig_answers.json").write_text(json.dumps(answers))


def test_dns_push_ensure_creates_the_push_name_alone_and_dns_remove_takes_only_it(rig):
    """The sandbox pair's shape: a console name a human created long ago, no push name. The runner creates the push name
    alone, marked; a second call is a no-op; dns_remove deletes the runner's record and leaves the human's."""
    cfg, _, tmp, cf = rig
    human = cf.seed("sandbox-a.theprotocol.cloud", content=IPV4)
    _answers(tmp, **{"sandbox-a.theprotocol.cloud": [IPV4]})
    out = call(cfg, op="dns_push_ensure", name="sandbox-a")["result"]
    assert out["created"] == ["sandbox-a-push.theprotocol.cloud"]
    made = [r for r in cf.records.values() if r["name"] == "sandbox-a-push.theprotocol.cloud"]
    assert len(made) == 1 and made[0]["content"] == IPV4 and made[0]["comment"].startswith("frame-runner:sandbox-a:push-")
    assert len(cf.writes()) == 1, "one POST: the console name is never touched"
    _answers(tmp, **{"sandbox-a-push.theprotocol.cloud": [IPV4]})
    again = call(cfg, op="dns_push_ensure", name="sandbox-a")["result"]
    assert again["created"] == [] and again["present"] == ["sandbox-a-push.theprotocol.cloud"] and len(cf.writes()) == 1
    gone = call(cfg, op="dns_remove", name="sandbox-a")["result"]
    assert gone["deleted"] == ["sandbox-a-push.theprotocol.cloud"]
    assert list(cf.records) == [human], "the human's console record stays"


def test_dns_push_ensure_never_adopts_and_refuses_a_frame_that_is_not_there(rig):
    cfg, _, tmp, cf = rig
    # a push name somebody else created: refused, never adopted
    cf.seed("taken-push.theprotocol.cloud")
    _answers(tmp, **{"taken.theprotocol.cloud": [IPV4]})
    r = call(cfg, op="dns_push_ensure", name="taken")
    assert r["ok"] is False and "never adopted" in r["refused"]
    # a push name that resolves without a record in the zone: refused
    _answers(tmp, **{"loose.theprotocol.cloud": [IPV4], "loose-push.theprotocol.cloud": ["198.51.100.9"]})
    r = call(cfg, op="dns_push_ensure", name="loose")
    assert r["ok"] is False and "already resolves" in r["refused"]
    # no frame by that name (its console name does not resolve): refused
    r = call(cfg, op="dns_push_ensure", name="nowhere")
    assert r["ok"] is False and "no frame by that name" in r["refused"]
    # a protected frame name: refused before the zone is asked
    r = call(cfg, op="dns_push_ensure", name="eu")
    assert r["ok"] is False and "protected" in r["refused"]
    assert cf.writes() == []


def test_dns_push_ensure_dry_run_creates_nothing(rig):
    cfg, _, tmp, cf = rig
    _answers(tmp, **{"sandbox-b.theprotocol.cloud": [IPV4]})
    out = call(cfg, op="dns_push_ensure", name="sandbox-b", dry_run=True)["result"]
    assert out["would_create"] == "sandbox-b-push.theprotocol.cloud" and out["created"] == []
    assert cf.writes() == []

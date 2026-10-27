"""§FRAMEPROV P2 (2026-09-13): the frame runner accepts a closed set of jobs, and nothing else.

A real server on a temporary socket, a FAKE driver and a FAKE teardown (tiny scripts written into tmp_path), a fixture
protected list and image allowlist. Nothing here touches the host's stacks, nginx, docker or /etc.
"""
import importlib.util
import json
import shutil
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

FAKE_DRIVER = r'''
import json, os, sys, time
argv = sys.argv[1:]
here = os.path.dirname(os.path.abspath(__file__))
def val(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default
name = val("--name")
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": argv, "secrets": os.environ.get("FRAME_SECRETS_DIR"),
                        "env_keys": sorted(os.environ)}) + "\n")
if "--plan" in argv:
    ok = name != "refuseme"
    print(json.dumps({"ok": ok, "refusals": [] if ok else ["DNS first: refuseme.theprotocol.cloud"], "warnings": [],
                      "derived": {"name": name, "ports": {"registry": 8600}}}))
    sys.exit(0 if ok else 2)
progress = val("--progress-file")
def emit(step, event, **kw):
    with open(progress, "a") as f:
        f.write(json.dumps({"step": step, "event": event, **kw}) + "\n")
emit("compose", "start")
if name == "slowpoke":
    time.sleep(60)
stack = val("--resume-stack-dir")
if not stack:
    ts = int(time.time())
    stack = os.path.join(here, "stack", f"{name}-{ts}")
    os.makedirs(stack)
    with open(os.path.join(stack, "hetzner-demo-run.json"), "w") as f:
        json.dump({"name": name, "ts": ts}, f)
    tmpl = os.path.join(here, "template.yml.tmpl")   # the frame's stack, rendered as the provisioner would
    if os.path.exists(tmpl):
        with open(tmpl) as src, open(os.path.join(stack, "docker-compose.frame-test.yml"), "w") as dst:
            dst.write(src.read().replace("{{REGISTRY_NAME}}", name))
    with open(os.path.join(os.environ["FRAME_SECRETS_DIR"], f".{name}_frame_admin.secret.json"), "w") as f:
        json.dump({"admin_email": f"admin@{name}.theprotocol.cloud", "admin_password": "p" * 24}, f)
emit("compose", "end", verdict="ok")
if name == "breakme":
    emit("run", "fail", verdict="refused", sentence="emission gate: EventStore not healthy")
    sys.exit(1)
emit("live", "live", verdict="ok", stack_dir=stack)
'''

# §MTLSHOPS T2: the compose template the rig's driver renders from, and the real shape check beside it
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE_TEMPLATE = ("# fixture compose template\n# frame-template-generation: mtlshops-t2\nservices:\n"
                    "  {{REGISTRY_NAME}}-registry:\n    image: registry\n  {{REGISTRY_NAME}}-nginx-edge:\n    image: nginx\n"
                    "volumes:\n  data:\n")

FAKE_TEARDOWN = '#!/bin/bash\necho "$1" >> "$(dirname "$0")/teardowns.txt"\nexit 0\n'

SPEC = {"name": "juice", "frame_label": "Juice", "ticker": "JUC", "currency_name": "Juice Unit", "mint": 1000000,
        "theme": "neural", "description": "A sandbox frame.", "operator_label": "TheProtocol",
        "location_label": "Valencia, Spain", "lat": 39.47, "lng": -0.38, "website": "",
        "registry_image": "agentvault2-registry-a:v0359", "teg_image": "agentvault2-teg-layer:v0351"}


@pytest.fixture
def rig(tmp_path):
    (tmp_path / "stack").mkdir()
    (tmp_path / "standup_driver.py").write_text(FAKE_DRIVER)
    shutil.copy(REPO_ROOT / "scripts" / "hetzner_demo" / "template_shape.py", tmp_path / "template_shape.py")
    (tmp_path / "template.yml.tmpl").write_text(FIXTURE_TEMPLATE)
    teardown = tmp_path / "teardown_hetzner_frame.sh"
    teardown.write_text(FAKE_TEARDOWN)
    teardown.chmod(0o755)
    plist = tmp_path / "protected-frames.list"
    plist.write_text("# fixture\neu\nasia\n")
    cfg = fr.Config(conf={"images": {"registry": ["agentvault2-registry-a:v0359"], "teg": ["agentvault2-teg-layer:v0351"]},
                          "allowed_uids": [os.getuid()], "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0},
                    socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "standup_driver.py"), teardown=str(teardown), python=sys.executable,
                    stack_root=str(tmp_path / "stack"), protected_list=str(plist),
                    template=str(tmp_path / "template.yml.tmpl"))
    srv = fr.make_server(cfg)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield cfg, srv, tmp_path
    active = srv.runner.active()
    if active:
        fr.os.killpg(active["pid"], 9)
    srv.shutdown()
    srv.server_close()


def call(cfg, **req):
    return fr.call(cfg.socket, req, timeout=60)


def wait_state(cfg, job_id, states=("succeeded", "failed", "cancelled", "lost"), timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = call(cfg, op="status", job_id=job_id)["result"]["job"]
        if rec["state"] in states:
            return rec
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never reached {states}")


def calls(tmp_path):
    with open(tmp_path / "calls.jsonl") as f:
        return [json.loads(line) for line in f]


def test_ping_names_the_caller(rig):
    cfg, _, _ = rig
    r = call(cfg, op="ping")
    assert r["ok"] is True and r["result"]["uid"] == os.getuid() and r["result"]["active"] is None


def test_ping_tells_the_ui_what_it_may_ask_for(rig):
    cfg, _, _ = rig
    r = call(cfg, op="ping")["result"]
    assert r["images"] == {"registry": ["agentvault2-registry-a:v0359"], "teg": ["agentvault2-teg-layer:v0351"],
                           "event_store": []}   # §SOVKIT: the store's allowlist is told too, empty here
    assert r["domain"] == "theprotocol.cloud"
    assert r["resumable_steps"] == list(fr.RESUMABLE_STEPS) and "emission" in r["resumable_steps"]
    assert r["spec_fields"] == list(fr.SPEC_FIELDS)


def test_the_socket_is_not_world_reachable(rig):
    cfg, _, _ = rig
    assert oct(os.stat(cfg.socket).st_mode & 0o777) == "0o660"
    assert oct(os.stat(cfg.state).st_mode & 0o777) == "0o700"


def test_an_unknown_op_and_a_malformed_request_are_refused(rig):
    cfg, _, _ = rig
    assert "unknown op" in call(cfg, op="shell", cmd="id")["refused"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(cfg.socket)
        s.sendall(b"not json\n")
        resp = json.loads(s.recv(65536))
    assert resp["ok"] is False and "one JSON object" in resp["refused"]


def test_a_uid_outside_the_allowlist_is_refused(rig):
    _, srv, _ = rig
    with pytest.raises(fr.Refused, match="may not use the frame runner"):
        srv.runner.handle({"op": "ping"}, 4242)


@pytest.mark.parametrize("change, sentence", [
    ({"name": "eu"}, "protected frame"),
    ({"name": "Bad_Name"}, "name: 2 to 32"),
    ({"ticker": "juc"}, "ticker"),
    ({"federate_with": "/opt/theprotocol/stack/eu-1"}, "unknown field"),
    ({"grant_host_reach": True}, "unknown field"),
    ({"registry_image": "agentvault2-registry-a:latest"}, "not an allowlisted registry image"),
    ({"lat": None}, "declared, never invented"),
    ({"description": "--wire-prod"}, "not starting with '-'"),
    ({"website": "http://plain.example"}, "website"),
    ({"mint": True}, "mint"),
])
def test_the_spec_is_a_closed_set_of_validated_fields(rig, change, sentence):
    cfg, _, _ = rig
    r = call(cfg, op="plan", spec={**SPEC, **change})
    assert r["ok"] is False and sentence in r["refused"], r


def test_a_plan_passes_the_drivers_answer_through(rig):
    cfg, _, tmp_path = rig
    ok = call(cfg, op="plan", spec=SPEC)["result"]
    assert ok["plan_ok"] is True and ok["exit_code"] == 0 and ok["plan"]["derived"]["name"] == "juice"
    refused = call(cfg, op="plan", spec={**SPEC, "name": "refuseme"})["result"]
    assert refused["plan_ok"] is False and refused["exit_code"] == 2
    argv = calls(tmp_path)[0]["argv"]
    for flag in ("--plan", "--allocate-ports", "--posture", "--wire-prod", "--render-vhosts"):
        assert flag in argv
    # §LANTERNT3 (2026-09-16): the default is production, not the old literal "sandbox". A runner-built frame is
    # internet-facing by construction, and the sandbox posture disables its rate limiter (standup_driver.py:695).
    assert argv[argv.index("--posture") + 1] == "production"
    assert argv[argv.index("--env-label") + 1] == "production"   # the tier cannot disagree with the posture
    for flag in ("--federate-with", "--grant-host-reach", "--operators-json", "--with-operator", "--tester-fixtures"):
        assert flag not in argv


def test_a_standup_the_plan_refuses_never_starts(rig):
    cfg, _, _ = rig
    r = call(cfg, op="standup", spec={**SPEC, "name": "refuseme"})["result"]
    assert r["started"] is False and r["plan_ok"] is False
    assert call(cfg, op="status")["result"]["jobs"] == []


def test_a_standup_runs_records_its_frame_and_hands_the_credential_over_once(rig):
    cfg, _, tmp_path = rig
    r = call(cfg, op="standup", spec=SPEC)["result"]
    assert r["started"] is True
    job = wait_state(cfg, r["job"]["id"])
    assert job["state"] == "succeeded" and job["exit_code"] == 0
    ev = call(cfg, op="events", job_id=job["id"], after=0)["result"]
    assert [e["event"] for e in ev["events"]] == ["start", "end", "live"] and ev["next"] == 3
    frames = call(cfg, op="status")["result"]["frames"]
    assert [f["name"] for f in frames] == ["juice"] and frames[0]["state"] == "live"
    run_call = [c for c in calls(tmp_path) if "--plan" not in c["argv"]][0]
    assert run_call["secrets"] == frames[0]["secrets_dir"] and run_call["secrets"].startswith(cfg.state)
    assert "--progress-file" in run_call["argv"]
    assert not any(k.startswith(("FRAME_TEST_PORT", "FRAME_MAIL")) for k in run_call["env_keys"])
    first = call(cfg, op="reveal", name="juice")
    assert first["ok"] is True and first["result"]["admin_password"] == "p" * 24
    again = call(cfg, op="reveal", name="juice")
    assert again["ok"] is False and "handed over at" in again["refused"]
    assert "p" * 24 not in (pathlib.Path(cfg.state) / "audit.jsonl").read_text()
    assert oct(os.stat(pathlib.Path(cfg.state) / "jobs" / job["id"] / "stdout.log").st_mode & 0o777) == "0o600"


def test_one_job_at_a_time_and_a_cancel_stops_it(rig):
    cfg, _, _ = rig
    slow = call(cfg, op="standup", spec={**SPEC, "name": "slowpoke"})["result"]
    assert slow["started"] is True
    second = call(cfg, op="standup", spec={**SPEC, "name": "second"})
    assert second["ok"] is False and "one job at a time" in second["refused"]
    assert call(cfg, op="ping")["result"]["active"] == slow["job"]["id"]
    assert call(cfg, op="cancel", job_id=slow["job"]["id"])["ok"] is True
    assert wait_state(cfg, slow["job"]["id"])["state"] == "cancelled"


def test_teardown_touches_only_a_frame_this_runner_built(rig):
    cfg, _, tmp_path = rig
    assert "protected frame" in call(cfg, op="teardown", name="eu")["refused"]
    assert "not built by this runner" in call(cfg, op="teardown", name="juice")["refused"]
    job = wait_state(cfg, call(cfg, op="standup", spec=SPEC)["result"]["job"]["id"])
    stack = call(cfg, op="status")["result"]["frames"][0]["stack_dir"]
    td = call(cfg, op="teardown", name="juice")["result"]
    assert wait_state(cfg, td["job"]["id"])["state"] == "succeeded" and job["state"] == "succeeded"
    assert (tmp_path / "teardowns.txt").read_text().strip() == stack
    assert call(cfg, op="status")["result"]["frames"] == []
    assert "not built by this runner" in call(cfg, op="teardown", name="juice")["refused"]


def test_a_teardown_removes_the_frames_secret_copies_and_only_those(rig):
    # His word 2026-09-13 ("torn down secrets ... have no use anymore, you decide"): the per-job copies go with the frame.
    cfg, srv, tmp_path = rig
    job = wait_state(cfg, call(cfg, op="standup", spec=SPEC)["result"]["job"]["id"])
    secrets = tmp_path / "state" / "jobs" / job["id"] / "secrets"
    assert (secrets / ".juice_frame_admin.secret.json").exists()
    td = wait_state(cfg, call(cfg, op="teardown", name="juice")["result"]["job"]["id"])
    record = tmp_path / "state" / "jobs" / td["id"] / "frame.json"
    deadline = time.time() + 10
    while not record.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert json.loads(record.read_text())["secrets_cleanup"] == "removed 1 file(s)"
    assert not secrets.exists() and (tmp_path / "state" / "jobs" / job["id"] / "stdout.log").exists()
    # the control: a recorded path that is not a runner job's secrets directory is named and left alone
    outside = tmp_path / "elsewhere" / "secrets"
    outside.mkdir(parents=True)
    (outside / "keep.json").write_text("{}")
    result = srv.runner._remove_frame_secrets({"name": "juice", "secrets_dir": str(outside)}, os.getuid())
    assert result.startswith("left alone") and (outside / "keep.json").exists()


def test_a_failed_standup_that_left_a_stack_can_still_be_torn_down(rig):
    cfg, _, _ = rig
    job = wait_state(cfg, call(cfg, op="standup", spec={**SPEC, "name": "breakme"})["result"]["job"]["id"])
    assert job["state"] == "failed"
    frames = call(cfg, op="status")["result"]["frames"]
    assert frames[0]["name"] == "breakme" and frames[0]["state"] == "standup failed"
    assert call(cfg, op="teardown", name="breakme")["ok"] is True


def test_a_resume_reuses_the_frames_stack_ports_and_secrets(rig):
    cfg, _, tmp_path = rig
    assert "from_step" in call(cfg, op="resume", name="juice", from_step="federate")["refused"]
    wait_state(cfg, call(cfg, op="standup", spec=SPEC)["result"]["job"]["id"])
    frame = call(cfg, op="status")["result"]["frames"][0]
    rid = call(cfg, op="resume", name="juice", from_step="wire")["result"]["job"]["id"]
    assert wait_state(cfg, rid)["state"] == "succeeded"
    resume_call = [c for c in calls(tmp_path) if "--resume-stack-dir" in c["argv"]][0]
    argv = resume_call["argv"]
    assert argv[argv.index("--resume-stack-dir") + 1] == frame["stack_dir"]
    assert argv[argv.index("--resume-from") + 1] == "wire" and "--allocate-ports" not in argv
    assert resume_call["secrets"] == frame["secrets_dir"]


def _standup_juice(cfg):
    wait_state(cfg, call(cfg, op="standup", spec=SPEC)["result"]["job"]["id"])
    return call(cfg, op="status")["result"]["frames"][0]


def _refused_before_any_job(cfg, tmp_path):
    """A refused resume leaves no job row, launches no driver and leaves the frame's state as it was."""
    jobs = pathlib.Path(cfg.state) / "jobs"
    before = sorted(os.listdir(jobs))
    state_before = call(cfg, op="status")["result"]["frames"][0]["state"]
    r = call(cfg, op="resume", name="juice", from_step="wire")
    assert r["ok"] is False, r
    assert sorted(os.listdir(jobs)) == before, "a refused resume must leave no job row"
    assert not [c for c in calls(tmp_path) if "--resume-stack-dir" in c["argv"]], "the driver must never launch"
    assert call(cfg, op="status")["result"]["frames"][0]["state"] == state_before
    return r["refused"]


def test_a_resume_of_a_stack_from_todays_generation_still_runs(rig):
    """§MTLSHOPS T2: the guard lets through the frame a resume exists for (same generation line, same services)."""
    cfg, _, _ = rig
    _standup_juice(cfg)
    rid = call(cfg, op="resume", name="juice", from_step="wire")["result"]["job"]["id"]
    assert wait_state(cfg, rid)["state"] == "succeeded"


def test_a_resume_refuses_a_stack_rendered_before_the_generation_line(rig):
    """lantern's shape: no generation line, and a service today's template no longer renders in place of one it does.
    Refused before any job row exists, and the sentence names the way out."""
    cfg, _, tmp_path = rig
    frame = _standup_juice(cfg)
    compose = pathlib.Path(frame["stack_dir"]) / "docker-compose.frame-test.yml"
    compose.write_text(compose.read_text().replace("# frame-template-generation: mtlshops-t2\n", "")
                       .replace("  juice-nginx-edge:\n    image: nginx\n", "  juice-pgbouncer:\n    image: pgbouncer\n"))
    r = _refused_before_any_job(cfg, tmp_path)
    assert r.startswith("juice cannot be resumed") and "re-render juice onto the mtlshops-t2 template first" in r
    assert "needs the Commander's word" in r and "tear it down and stand it up again" in r


def test_a_resume_refuses_a_stack_whose_service_set_differs(rig):
    """The same generation line, but today's template renders a service the stack lacks: another frame, still refused."""
    cfg, _, tmp_path = rig
    _standup_juice(cfg)
    tmpl = tmp_path / "template.yml.tmpl"
    tmpl.write_text(tmpl.read_text().replace("volumes:\n", "  {{REGISTRY_NAME}}-nginx-ntfy:\n    image: nginx\nvolumes:\n"))
    r = _refused_before_any_job(cfg, tmp_path)
    assert "services today's template renders and the stack lacks: juice-nginx-ntfy" in r


def test_a_resume_refuses_when_the_shape_check_cannot_load(rig):
    cfg, _, tmp_path = rig
    _standup_juice(cfg)
    (tmp_path / "template_shape.py").unlink()
    assert "cannot be loaded" in _refused_before_any_job(cfg, tmp_path)


def test_the_host_gates_refuse_before_anything_starts(rig):
    cfg, srv, _ = rig
    srv.runner.host_gates = lambda: ["load1=99.0 is at or above 40"]
    r = call(cfg, op="standup", spec=SPEC)
    assert r["ok"] is False and "host gates: load1=99.0" in r["refused"]


def test_a_restarted_runner_settles_a_job_whose_process_is_gone(rig):
    cfg, srv, _ = rig
    jd = pathlib.Path(cfg.state) / "jobs" / "0123456789abcdef"
    jd.mkdir(mode=0o700)
    (jd / "progress.jsonl").write_text(json.dumps({"step": "live", "event": "live"}) + "\n")
    fr.write_json(str(jd / "job.json"), {"id": "0123456789abcdef", "op": "resume", "name": "ghost", "state": "running",
                                         "pid": 999999999, "needle": "standup_driver.py", "created": fr.now(),
                                         "request": {}, "argv": [], "secrets_dir": str(jd)})
    fr.Runner(cfg)
    rec = fr.read_json(str(jd / "job.json"))
    assert rec["state"] == "succeeded" and rec["exit_code"] is None


def _conf(**over):
    base = {"images": {"registry": ["agentvault2-registry-a:v0359"], "teg": ["agentvault2-teg-layer:v0351"]},
            "allowed_uids": [os.getuid()], "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0}
    base.update(over)
    return base


def test_the_posture_comes_from_the_policy_and_not_a_literal():
    """§LANTERNT3 (2026-09-16, his word "lantern shouldnt be sandbox"): driver_argv carried the literal "sandbox",
    and standup_driver.py:695 turns the rate limiter OFF for any posture that is not "production" — so every frame
    the runner ever built went live on a public DNS name with no rate limiting. The default is now production, a
    host that really wants a sandbox frame says so in its policy, and --env-label follows the same key so the tier
    a frame is GROUPED under cannot disagree with the posture it carries."""
    spec = dict(SPEC)
    default = fr.Config(conf=_conf())
    assert default.posture == "production"
    argv = fr.Runner(default).driver_argv(spec)
    assert argv[argv.index("--posture") + 1] == "production"
    assert argv[argv.index("--env-label") + 1] == "production"

    sandbox = fr.Config(conf=_conf(posture="sandbox"))
    argv = fr.Runner(sandbox).driver_argv(spec)
    assert argv[argv.index("--posture") + 1] == "sandbox"
    assert argv[argv.index("--env-label") + 1] == "sandbox"


def test_a_posture_that_is_neither_is_refused_at_load():
    """The control: the key is not free text. A typo must stop the runner rather than silently become a posture
    the driver does not recognise — which, because the driver tests `!= "production"`, is the permissive one."""
    with pytest.raises(SystemExit) as e:
        fr.Config(conf=_conf(posture="prod"))          # plausible, wrong, the exact shape a human would type
    assert "posture" in str(e.value)


def test_the_mail_relay_is_passed_through_and_the_token_comes_from_a_file(tmp_path):
    """§LANTERNT3: a production-posture frame needs an outbound relay (standup_driver.py:2048 refuses without one,
    findings row 181). The policy names the relay and REFERENCES the token by file, never carrying the value, the
    way the dns block's token_file does."""
    tok = tmp_path / "smtp.token"
    tok.write_text("a-real-looking-token\n")
    cfg = fr.Config(conf=_conf(mail={"server": "smtp.example.test", "address": "noreply@example.test",
                                     "token_file": str(tok), "port": 2525}))
    env = fr.Runner(cfg).driver_env()
    assert env["FRAME_MAIL_SERVER"] == "smtp.example.test"
    assert env["FRAME_MAIL_ADDRESS"] == "noreply@example.test"
    assert env["FRAME_MAIL_PORT"] == "2525"
    assert env["FRAME_MAIL_TOKEN"] == "a-real-looking-token"      # stripped of its newline


def test_an_unreadable_or_empty_token_supplies_NO_relay_rather_than_half_of_one(tmp_path):
    """The control, and the one that matters: the driver treats a half-supplied relay as an error, and an EMPTY
    password would be offered to the relay and rejected at the first send. Absent must read as absent, so that the
    plan refuses a production posture cleanly instead of the frame coming up mail-dead behind a configured-looking
    relay."""
    empty = tmp_path / "empty.token"
    empty.write_text("   \n")
    for token_file in (str(empty), str(tmp_path / "does-not-exist")):
        cfg = fr.Config(conf=_conf(mail={"server": "smtp.example.test", "address": "noreply@example.test",
                                         "token_file": token_file}))
        env = fr.Runner(cfg).driver_env()
        assert not any(k.startswith("FRAME_MAIL_") for k in env), (token_file, sorted(env))


def test_a_mail_block_missing_a_field_is_refused_at_load():
    with pytest.raises(SystemExit) as e:
        fr.Config(conf=_conf(mail={"server": "smtp.example.test"}))   # no address
    assert "mail" in str(e.value)


# ── §LANTERNT3: the operator socket, where the grant is bounded by which file a caller can see ──────────

@pytest.fixture()
def opsock(rig):
    """The SECOND listener, serving OPERATOR_OPS only, alongside the rig's full socket."""
    cfg, _, tmp_path = rig
    runner = fr.Runner(cfg)
    # the operator ops act on a frame THIS runner built, so the fixture records one; without it every test here
    # would be refused for the right reason at the wrong gate and prove nothing about the spec.
    runner.save_frame({"name": "juice", "stack_dir": str(tmp_path / "stack" / "juice-1"),
                       "spec": {"operators": []}, "state": "live", "created": fr.now(), "updated": fr.now()})
    srv = fr.make_server(cfg, runner, cfg.operator_socket, fr.OPERATOR_OPS)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield cfg, tmp_path
    srv.shutdown()


def test_the_operator_socket_serves_its_own_ops(opsock):
    cfg, _ = opsock
    r = fr.call(cfg.operator_socket, {"op": "operator_ping"}, timeout=30)
    assert r["ok"] is True, r
    assert sorted(r["result"]["ops"]) == sorted(fr.OPERATOR_OPS)
    # it tells a caller its own bound rather than making it discover one by being refused
    assert "teardown" in r["result"]["refused_here"]


def test_RED_the_operator_socket_refuses_teardown(opsock):
    """THE control this whole design exists for. A frame's registry mounts this socket; if `teardown` were
    reachable on it, a compromised frame could destroy other frames, and the sentence "we replaced an unbounded
    grant with a bounded one" would be false in exactly the way a commit message saying eight-tests-pass is."""
    cfg, _ = opsock
    for op in ("teardown", "standup", "resume", "reveal", "dns_remove"):
        r = fr.call(cfg.operator_socket, {"op": op, "name": "juice"}, timeout=30)
        assert r["ok"] is False, (op, r)
        assert "not served on this socket" in r.get("refused", ""), (op, r)


def test_RED_the_full_socket_refuses_the_operator_ops(opsock):
    """The bound runs BOTH ways: the console's socket does not gain a frame's ops either, so neither set is a
    superset of the other by accident. Two sets, not one flag."""
    cfg, _ = opsock
    for op in fr.OPERATOR_OPS:
        r = fr.call(cfg.socket, {"op": op, "frame": "juice"}, timeout=30)
        assert r["ok"] is False, (op, r)
        assert "not served on this socket" in r.get("refused", ""), (op, r)


def test_a_real_typo_is_told_apart_from_a_wrong_socket(opsock):
    """'not on this socket' and 'no such op' have different fixes — mount the other socket, or fix the caller.
    One message for both would send a reader hunting for a typo in a name that is spelled correctly."""
    cfg, _ = opsock
    r = fr.call(cfg.operator_socket, {"op": "operator_privision"}, timeout=30)   # deliberate typo
    assert r["ok"] is False and "unknown op" in r.get("refused", ""), r


def test_the_operator_ops_refuse_a_frame_this_runner_did_not_build(opsock):
    cfg, _ = opsock
    r = fr.call(cfg.operator_socket, {"op": "operator_status", "frame": "somebody-elses"}, timeout=30)
    assert r["ok"] is False and "not this runner's to act on" in r.get("refused", ""), r
    r = fr.call(cfg.operator_socket, {"op": "operator_status"}, timeout=30)
    assert r["ok"] is False and "name the frame" in r.get("refused", ""), r


def _spec(**over):
    """A spec with every required field, so a test can remove exactly one thing and see it refused.
    These are the names agentvault2-b5's operator_host_work actually reads, plus image_id, which is the runner's
    own. The seam lives in two places on purpose; neither side changes a key without telling the other."""
    base = {"frame": "juice", "operator_name": "Tartu", "safe_name": "tartu",
            "operator_did": "did:theprotocol:11111111-1111-1111-1111-111111111111",
            "docker_pull_token": "dpt_" + "0" * 16,
            "operator_secrets": {"TEG_PROXY_TRUST_SECRET": "a" * 64,
                                 "REGISTRY_PROXY_TRUST_SECRET": "b" * 64,
                                 "REDIS_PASSWORD_REGISTRY": "c" * 32,
                                 "REDIS_PASSWORD_TEG": "d" * 32,
                                 "AUDITOR_RO_PASSWORD": "e" * 32},
            "env": {"REGISTRY_NAME": "cloud-op-tartu"}}
    base.update(over)
    return base


def test_provision_refuses_a_spec_that_is_missing_anything(opsock):
    cfg, _ = opsock
    for drop in ("operator_name", "safe_name", "operator_did", "docker_pull_token", "operator_secrets"):
        spec = _spec(); spec.pop(drop)
        r = fr.call(cfg.operator_socket, {"op": "operator_provision", "frame": "juice", "spec": spec}, timeout=30)
        assert r["ok"] is False and drop in r.get("refused", ""), (drop, r)


def test_RED_provision_refuses_a_spec_carrying_the_database_or_a_token(opsock):
    """The seam is worth having ONLY because nothing on the far side holds the database. A spec that smuggles one
    is refused rather than forwarded, so the property is enforced here and not merely intended by the caller."""
    cfg, _ = opsock
    for bad in ({"DATABASE_URL": "postgresql://x"}, {"env": {"DATABASE_URL": "postgresql://x"}},
                {"env": {"API_KEY_SECRET": "x"}},
                # AT ANY DEPTH: a nested object is exactly where one would survive a shallow scan, and "it is in
                # env" was only ever one of the places it could hide. b5's module checks the same, on purpose.
                {"env": {"a": {"b": {"DATABASE_URL": "postgresql://x"}}}},
                {"env": {"nested": [{"JWT_SECRET_KEY": "x"}]}},
                {"operator_secrets": {"TEG_PROXY_TRUST_SECRET": "a" * 64,
                                      "REGISTRY_PROXY_TRUST_SECRET": "b" * 64,
                                      "REDIS_PASSWORD_REGISTRY": "c" * 32,
                                      "REDIS_PASSWORD_TEG": "d" * 32,
                                      "AUDITOR_RO_PASSWORD": "e" * 32,
                                      "SECRET_KEY": "smuggled"}}):
        spec = _spec(**bad)
        r = fr.call(cfg.operator_socket, {"op": "operator_provision", "frame": "juice", "spec": spec}, timeout=30)
        assert r["ok"] is False, (bad, r)
        assert "neither the frame's database nor" in r.get("refused", ""), (bad, r)


def test_RED_the_caller_may_not_name_the_image_at_all(opsock):
    """The contract changed on agentvault2-b5's recommendation and it is stronger than refusing a tag: the runner
    takes the image from the FRAME'S OWN registry container, so the one-shot is provably the code the frame runs
    — and a value nobody is asked for is a value nobody can lie about."""
    cfg, _ = opsock
    for named in ("agentvault2-registry-a:v0382", "sha256:" + "a" * 64, "latest"):
        r = fr.call(cfg.operator_socket,
                    {"op": "operator_provision", "frame": "juice", "spec": _spec(image_id=named)}, timeout=30)
        assert r["ok"] is False and "Do not send it" in r.get("refused", ""), (named, r)


def test_provision_refuses_when_the_frames_registry_is_not_running(opsock):
    """No container, no image id, and the runner will not guess one: running an image nobody can attribute to
    the frame is exactly what taking it from the container exists to prevent."""
    cfg, _ = opsock
    r = fr.call(cfg.operator_socket, {"op": "operator_provision", "frame": "juice", "spec": _spec()}, timeout=60)
    assert r["ok"] is False, r
    assert "is not running" in r.get("refused", "") or "not an allowlisted" in r.get("refused", ""), r


def test_a_bundle_phase_carries_no_secrets_and_a_full_one_must(opsock):
    """b5's measurement: a bundle job writes no env and no markers, so requiring the four secrets would put live
    secrets in a spec file on disk for a job that never opens them. A secret written where nothing reads it is a
    secret with only downside."""
    cfg, _ = opsock
    bare = {k: v for k, v in _spec().items() if k != "operator_secrets"}
    r = fr.call(cfg.operator_socket,
                {"op": "operator_provision", "frame": "juice", "spec": {**bare, "phase": "bundle"}}, timeout=60)
    assert "operator_secrets" not in r.get("refused", ""), r     # not refused FOR the secrets
    r = fr.call(cfg.operator_socket,
                {"op": "operator_provision", "frame": "juice", "spec": {**bare, "phase": "full"}}, timeout=60)
    assert r["ok"] is False and "operator_secrets" in r.get("refused", ""), r
    # and sending them in a bundle phase is refused rather than quietly written to disk
    r = fr.call(cfg.operator_socket,
                {"op": "operator_provision", "frame": "juice", "spec": {**_spec(), "phase": "bundle"}}, timeout=60)
    assert r["ok"] is False and "opens none of them" in r.get("refused", ""), r


def test_RED_a_stack_or_full_spec_without_the_read_only_password_is_refused_before_any_job(opsock):
    """§OPDIST: the auditor link needs a READ-ONLY credential, and the only alternative is the owner credential, which
    is refused. Without the key, the operator would provision and then read NOT CONNECTED forever. That is refused
    here, where a refusal costs nothing, rather than discovered after the activation code is spent."""
    cfg, _ = opsock
    four = {k: v for k, v in _spec()["operator_secrets"].items() if k != "AUDITOR_RO_PASSWORD"}
    for phase, extra in (("full", {}), ("stack", {"bundle_filename": "tartu.tar.gz", "compose": "services: {}"})):
        r = fr.call(cfg.operator_socket, {"op": "operator_provision", "frame": "juice",
                                          "spec": {**_spec(operator_secrets=four, **extra), "phase": phase}}, timeout=30)
        assert r["ok"] is False and "lacks AUDITOR_RO_PASSWORD" in r.get("refused", ""), (phase, r)


def test_an_unknown_phase_is_refused_not_defaulted_to_the_biggest_thing(opsock):
    cfg, _ = opsock
    r = fr.call(cfg.operator_socket,
                {"op": "operator_provision", "frame": "juice", "spec": {**_spec(), "phase": "everything"}},
                timeout=30)
    assert r["ok"] is False and "is not one of" in r.get("refused", ""), r


def test_the_success_path_stages_its_spec_and_launches_the_right_container(opsock, monkeypatch):
    """The path every other test here skips. It caught a real bug the refusal tests could not: the op created
    the job dir and launch created it again. It also pins the container's SHAPE, which is the security-relevant
    half — by image ID, no --privileged, no --pid=host, and the docker socket present because that is the whole
    point, while the host nginx reload stays with the runner rather than buying a container PID 1's namespace."""
    cfg, tmp_path = opsock
    runner = fr.Runner(cfg)
    runner.save_frame({"name": "juice", "stack_dir": str(tmp_path / "stack" / "juice-1"),
                       "spec": {"operators": []}, "state": "live", "created": fr.now(), "updated": fr.now()})
    seen = {}

    def fake_launch(op, uid, name, argv, request, **kw):
        seen.update(op=op, argv=argv, job_id=kw.get("job_id"), request=request)
        return {"id": kw.get("job_id"), "op": op, "name": name, "state": "running", "created": fr.now()}

    monkeypatch.setattr(runner, "launch", fake_launch)
    monkeypatch.setattr(runner, "host_gates", lambda: [])
    monkeypatch.setattr(runner, "active", lambda: None)
    # a real image id this host has, so the allowlist check is exercised rather than skipped
    fake_image = "sha256:" + "e" * 64
    monkeypatch.setattr(runner, "_operator_image", lambda name: fake_image)
    sd = tmp_path / "stack" / "juice-1"
    sd.mkdir(parents=True, exist_ok=True)
    # a REAL env file, so the identity-network read is exercised rather than stubbed. The name is deliberately
    # not derivable from the frame's slug, because on the live fleet it is not: lantern's is
    # lantern_network_identity while EU's and ASIA's are both fresh-identity.
    (sd / ".env.frame-test").write_text("FT_REG_IDENTITY_NETWORK=not-derivable-from-the-slug\n")
    # stubbed here on purpose: the real read asks docker whether the network EXISTS, and this rig has no such
    # network. The read itself is pinned by test_the_identity_network_is_read_from_the_env_that_names_it.
    monkeypatch.setattr(runner, "_frame_identity_network", lambda f: "not-derivable-from-the-slug")
    # stubbed for the same reason: the real read inspects juice-registry, which this rig does not run. The read is pinned
    # by the §OPDIST beacon tests below; what THIS test pins is that the op passes what it read into the container.
    inputs = {"env": {"SPIRE_CONTAINER": "juice-spire-server", "SPIRE_TRUST_DOMAIN": "juice.theprotocol.cloud"},
              "binds": [("/stack/juice-1/x509pop-certs", "/opt/spire-ca"), ("/tpl", "/app/nginx-templates")]}
    monkeypatch.setattr(runner, "_frame_provisioner_inputs", lambda f: inputs)
    spec = _spec()
    out = runner.handle({"op": "operator_provision", "frame": "juice", "spec": spec}, 0, fr.OPERATOR_OPS)
    assert out["started"] is True
    # §OPDIST (beacon, 2026-09-16): the registry's client reads `job_id` at the TOP of this answer. Without it, activation
    # raised "accepted operator_provision without returning a job id" while its bundle job went on to succeed, leaving an
    # application with a spent code, three SPIRE entries and a tar its row knows nothing about. Both shapes, one id.
    assert out.get("job_id") == seen["job_id"] and (out.get("job") or {}).get("id") == seen["job_id"], out

    argv = seen["argv"]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--privileged" not in argv and "--pid=host" not in argv, argv
    assert "/var/run/docker.sock:/var/run/docker.sock" in argv
    assert fake_image in argv, "the container must be named by the image ID read from the frame's container"
    assert not any(a.startswith("agentvault2-registry-a:") for a in argv), argv
    assert "SPIRE_CONTAINER=juice-spire-server" in argv and "/stack/juice-1/x509pop-certs:/opt/spire-ca:ro" in argv, \
        "the op must hand the one-shot the frame's own SPIRE target and CA, or the provisioner falls back to Frame A's"

    # the spec was staged BEFORE launch, which is the bug this test exists for
    staged = pathlib.Path(runner.job_dir(seen["job_id"])) / "spec.json"
    assert staged.exists(), "the container reads its spec the instant it starts; it cannot be written after"
    body = json.loads(staged.read_text())
    assert body["safe_name"] == "tartu" and body["frame"] == "juice"
    # stamped by the runner from the frame record, never taken from the caller
    assert body["frame_stack_dir"].endswith("juice-1"), body
    assert body["phase"] == "full"
    assert body["frame_identity_network"] == "not-derivable-from-the-slug", body
    assert "DATABASE_URL" not in json.dumps(body), "no database reaches the far side of the seam"


def test_launch_tolerates_a_job_dir_an_op_already_staged_into(rig):
    """The bug the success-path test does NOT catch, which I found by mutation-testing it: that test stubs
    launch, so the collision it was written for never happens there. This one drives the REAL launch against a
    job dir that has already been created and written into — which is exactly what operator_provision does,
    because the container reads its spec the instant it starts and so it cannot be written afterwards."""
    cfg, srv, tmp_path = rig
    runner = srv.runner
    job_id = "deadbeefcafe0001"
    jd = pathlib.Path(runner.job_dir(job_id))
    jd.mkdir(mode=0o700, parents=True)
    (jd / "spec.json").write_text('{"staged": true}')

    rec = runner.launch("operator_provision", 0, "juice", ["/bin/true"], request={}, progress=False,
                        job_id=job_id, needle="true")
    assert rec["id"] == job_id
    assert (jd / "spec.json").read_text() == '{"staged": true}', "staging must survive the launch"


def test_operator_status_polls_a_job_because_status_and_events_are_refused_here(opsock):
    """b5 caught this by ASKING which op to poll rather than assuming. `status` and `events` are frame ops and
    are refused on this socket, so without a job view a caller could submit and never learn the outcome — his
    poll loop would have spun to its deadline against a job that had already finished."""
    cfg, tmp_path = opsock
    runner = fr.Runner(cfg)
    runner.save_frame({"name": "juice", "stack_dir": str(tmp_path / "stack" / "juice-1"),
                       "spec": {"operators": []}, "state": "live", "created": fr.now(), "updated": fr.now()})
    pathlib.Path(runner.job_dir("a1b2c3d4e5f60001")).mkdir(mode=0o700, parents=True)
    runner.save_job({"id": "a1b2c3d4e5f60001", "op": "operator_provision", "name": "juice", "state": "succeeded",
                     "created": fr.now(), "ended": fr.now(), "exit_code": 0, "refused": False,
                     "result": {"stack_dir": "/opt/theprotocol/stack/cloud-op-tartu", "container_count": 9}})
    out = runner.handle({"op": "operator_status", "frame": "juice", "job_id": "a1b2c3d4e5f60001"}, 0,
                        fr.OPERATOR_OPS)
    assert out["job"]["state"] == "succeeded" and out["job"]["refused"] is False
    assert out["result"]["container_count"] == 9, out

    # and a job belonging to another frame is not readable through this one
    pathlib.Path(runner.job_dir("a1b2c3d4e5f60002")).mkdir(mode=0o700, parents=True)
    runner.save_job({"id": "a1b2c3d4e5f60002", "op": "operator_provision", "name": "somebody-else",
                     "state": "running", "created": fr.now()})
    with pytest.raises(fr.Refused):
        runner.handle({"op": "operator_status", "frame": "juice", "job_id": "a1b2c3d4e5f60002"}, 0, fr.OPERATOR_OPS)


def test_the_identity_network_is_read_from_the_env_that_names_it(rig, tmp_path_factory):
    """Not derived from the slug, because no slug rule survives the population: lantern's identity network is
    lantern_network_identity while EU's and ASIA's are both fresh-identity. Measured on the live fleet."""
    cfg, srv, tmp_path = rig
    runner = srv.runner
    sd = tmp_path / "stack" / "juice-1"
    sd.mkdir(parents=True, exist_ok=True)
    frame = {"name": "juice", "stack_dir": str(sd), "spec": {}, "state": "live"}

    (sd / ".env.frame-test").write_text("FT_REG_OTHER=x\n")
    with pytest.raises(fr.Refused) as e:
        runner._frame_identity_network(frame)
    assert "will not guess one" in str(e.value)

    (sd / ".env.frame-test").write_text("FT_REG_IDENTITY_NETWORK=a-network-that-does-not-exist\n")
    with pytest.raises(fr.Refused) as e:
        runner._frame_identity_network(frame)
    assert "does not exist on this host" in str(e.value), "a name that resolves to no network is not a network"


def test_the_entry_module_is_not_under_services(rig):
    """The cheap structural half. Importing agentvault_registry.services runs a package init that reaches
    config.Settings, which REQUIRES DATABASE_URL and API_KEY_SECRET — and the one-shot is given neither, on
    purpose. An entry point under services therefore dies at IMPORT, before reading a spec or touching a socket.
    This is a proxy for the real property and is kept only because it is free; the test below is the real one."""
    assert not fr.Runner.OPERATOR_ENTRY_MODULE.startswith("agentvault_registry.services"), \
        fr.Runner.OPERATOR_ENTRY_MODULE


def test_the_entry_point_reaches_its_own_contract_with_no_app_config(rig):
    """THE REAL PROPERTY, asked of the image rather than of a name: run the one-shot's entry point exactly as the
    runner launches it — no DATABASE_URL, no API_KEY_SECRET, PYTHONPATH as the image lacks it — and require that
    it reaches its OWN contract rather than a config error.

    Both halves of the launch are pinned here because both were wrong: the module was under services (b5 found
    it), and the argv carried no PYTHONPATH (the image has none; the running registry gets it from its env file).
    Either one alone kills the container before anything else matters, and no test that imports by path can see
    either, because a path import runs no package init and needs no PYTHONPATH."""
    cfg, srv, _ = rig
    tag = (cfg.images.get("registry") or [None])[0]
    if not tag or subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode != 0:
        pytest.skip(f"the allowlisted registry image {tag} is not on this host")
    mod = fr.Runner.OPERATOR_ENTRY_MODULE
    present = subprocess.run(
        ["docker", "run", "--rm", "--env-file", "/dev/null", "-e", "PYTHONPATH=/app/src",
         "--entrypoint", "python3", tag, "-c",
         f"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec({mod!r}) else 9)"],
        capture_output=True, text=True, timeout=120)
    if present.returncode == 9:
        # LOUD, not silent: this is the honest third state. The module ships in a later image than the one this
        # host allowlists today, so the property cannot be asked yet — and saying so is not the same as passing.
        pytest.skip(f"{tag} does not carry {mod} yet (it lands with the operator host-work image); "
                    f"the property is UNTESTED here, not satisfied")
    assert present.returncode == 0, present.stderr[-400:]

    r = subprocess.run(
        ["docker", "run", "--rm", "--env-file", "/dev/null", "-e", "PYTHONPATH=/app/src",
         "--entrypoint", "python3", tag, "-m", mod],
        capture_output=True, text=True, timeout=120)
    blob = (r.stdout + r.stderr)
    assert "ValidationError" not in blob and "DATABASE_URL" not in blob, \
        f"the entry point reached app config instead of its own contract:\n{blob[-600:]}"


@pytest.fixture()
def edge(rig, tmp_path, monkeypatch):
    """The edge apply, pointed at temp paths and a stubbed nginx. NEVER the live /etc/nginx: this code can break
    the edge for every site on the host, which is exactly why its revert path has to be proven rather than read."""
    cfg, srv, _ = rig
    runner = srv.runner
    sites, backups = tmp_path / "sites-enabled", tmp_path / "vhost-backups"
    sites.mkdir(); backups.mkdir()
    sni = tmp_path / "federation-mtls.conf"
    sni.write_text("map $ssl_preread_server_name $federation_upstream {\n"
                   "    existing.op.example    127.0.0.1:26043;\n"
                   "    # --- Default: the mainframe ---\n"
                   "    default                127.0.0.1:18443;\n"
                   "}\n")
    monkeypatch.setattr(fr.Runner, "NGINX_SITES", str(sites))
    monkeypatch.setattr(fr.Runner, "NGINX_BACKUPS", str(backups))
    monkeypatch.setattr(fr.Runner, "NGINX_SNI_MAP", str(sni))
    calls = []
    real_run = fr.subprocess.run

    def fake_run(argv, **kw):
        if argv and argv[0] == "nginx":
            calls.append(argv)
            bad = "REFUSE_ME" in (sites / "cloud-op-tartu").read_text() if (sites / "cloud-op-tartu").exists() else False
            rc = 1 if (argv[1:2] == ["-t"] and bad) else 0
            return subprocess.CompletedProcess(argv, rc, "", "bad config near REFUSE_ME" if rc else "")
        return real_run(argv, **kw)

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    jd = pathlib.Path(runner.job_dir("edgejob000000001"))
    jd.mkdir(mode=0o700, parents=True)
    (jd / "spec.json").write_text(json.dumps({"edge": {
        "domain": "tartu.op.example", "reg_port": 31500, "fed_port": 31543,
        "ssl_cert_name": "op.example", "ws_events_host": "localhost:8511"}}))
    return runner, sites, backups, sni, calls


def test_the_edge_writes_the_vhost_and_sni_then_tests_before_reloading(edge):
    runner, sites, _, sni, calls = edge
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": "server {\n server_name tartu.op.example;\n"
                                    " ssl_certificate /etc/letsencrypt/live/op.example/fullchain.pem;\n"
                                    " proxy_pass http://127.0.0.1:31500;\n}",
                      "sni_entry": "tartu.op.example    127.0.0.1:31543;"}}
    runner._apply_operator_edge(rec)
    assert (sites / "cloud-op-tartu").exists()
    assert "tartu.op.example    127.0.0.1:31543;" in sni.read_text()
    assert "existing.op.example" in sni.read_text(), "an unrelated entry must survive"
    # the SNI line goes ABOVE the default, or it can never match
    body = sni.read_text()
    assert body.index("tartu.op.example") < body.index("--- Default:")
    assert ["nginx", "-t"] in calls and ["nginx", "-s", "reload"] in calls
    assert calls.index(["nginx", "-t"]) < calls.index(["nginx", "-s", "reload"]), "test BEFORE reload, always"
    assert rec["state"] == "succeeded"


def test_RED_a_config_nginx_refuses_is_reverted_and_never_reloaded(edge):
    """The one that matters. If nginx -t refuses, everything written must come back out and reload must NEVER
    run — a reload of a broken config takes the whole host edge down, not just this operator."""
    runner, sites, _, sni, calls = edge
    before = sni.read_text()
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": "server {\n server_name tartu.op.example;\n REFUSE_ME\n}",
                      "sni_entry": "tartu.op.example 127.0.0.1:31543;"}}
    runner._apply_operator_edge(rec)
    assert not (sites / "cloud-op-tartu").exists(), "the vhost must be removed again"
    assert sni.read_text() == before, "the SNI map must be byte-identical to before"
    assert ["nginx", "-s", "reload"] not in calls, "a refused config must never be reloaded"
    assert rec["state"] == "failed"
    assert any("reverted" in n for n in rec["notes"]), rec["notes"]


def test_the_sni_entry_is_replaced_not_duplicated(edge):
    runner, _, _, sni, _ = edge
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": "server {\n server_name tartu.op.example;\n}",
                      "sni_entry": "tartu.op.example 127.0.0.1:31543;"}}
    runner._apply_operator_edge(rec)
    rec["result"]["sni_entry"] = "tartu.op.example 127.0.0.1:31599;"
    runner._apply_operator_edge(rec)
    assert sni.read_text().count("tartu.op.example") == 1, sni.read_text()
    assert "31599" in sni.read_text() and "31543" not in sni.read_text()


def test_a_result_with_no_vhost_writes_nothing_and_says_so(edge):
    runner, sites, _, _, calls = edge
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded", "result": {}}
    runner._apply_operator_edge(rec)
    assert not list(sites.iterdir()) and not calls
    assert any("no host_vhost" in n for n in rec["notes"]), rec["notes"]


@pytest.mark.parametrize("bad,why", [
    ("server {\n server_name someone-else.example;\n}", "answers to"),
    ("server {\n server_name tartu.op.example;\n proxy_pass http://evil.example:80;\n}", "proxies to"),
    ("server {\n server_name tartu.op.example;\n proxy_pass http://127.0.0.1:9999;\n}", "proxies to"),
    ("server {\n server_name tartu.op.example;\n ssl_certificate /etc/letsencrypt/live/other/x.pem;\n}",
     "presents"),
    ("server {\n server_name tartu.op.example;\n # DATABASE_URL=postgresql://u:p@h/db\n}", "credential"),
])
def test_RED_a_vhost_that_exceeds_what_the_spec_declares_is_refused(edge, bad, why):
    """b5 named the escalation rather than leaving it implied: a vhost the registry renders and the runner writes
    AS ROOT means the registry decides what this host serves. So it is checked against spec.edge, not trusted —
    whose name it answers to, where it sends traffic, whose certificate it presents. The last case is his other
    observation: both credential hunts walk dicts and lists and cannot see inside a STRING, and this is the first
    large string to cross."""
    runner, sites, _, sni, calls = edge
    before = sni.read_text()
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": bad, "sni_entry": "tartu.op.example 127.0.0.1:31543;"}}
    runner._apply_operator_edge(rec)
    assert rec["state"] == "failed", rec
    assert any(why in n for n in rec["notes"]), rec["notes"]
    assert not (sites / "cloud-op-tartu").exists() and sni.read_text() == before
    assert ["nginx", "-s", "reload"] not in calls


def test_an_unchecked_vhost_is_never_written(edge, tmp_path):
    """No edge block means nothing can be checked, and the answer to that is to refuse rather than to trust."""
    runner, sites, _, _, _ = edge
    (pathlib.Path(runner.job_dir("edgejob000000001")) / "spec.json").write_text("{}")
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": "server {\n server_name tartu.op.example;\n}"}}
    runner._apply_operator_edge(rec)
    assert rec["state"] == "failed" and not (sites / "cloud-op-tartu").exists()
    assert any("will not be written unchecked" in n for n in rec["notes"]), rec["notes"]


def test_image_drift_is_reported_when_a_frame_runs_something_unallowlisted(rig, monkeypatch):
    """The allowlist is a CARRIER no version roll touches, and it went stale three times in one day: twice caught
    by luck, once by a person, never by an instrument. A fleet census answers "what is running"; an allowlist
    answers "what may exist"; nothing we had asked the second question. This reports rather than refuses, because
    drift is not always wrong and a runner that refused a standup over it would refuse for a reason that has
    nothing to do with the standup."""
    cfg, srv, tmp_path = rig
    runner = srv.runner
    runner.save_frame({"name": "juice", "stack_dir": str(tmp_path), "spec": {}, "state": "live",
                       "created": fr.now(), "updated": fr.now()})

    def fake(argv, **kw):
        if argv[:2] == ["docker", "image"]:                       # the allowlisted tag resolves to AAA
            return subprocess.CompletedProcess(argv, 0, "sha256:" + "a" * 64, "")
        if argv[:2] == ["docker", "inspect"]:                     # the frame is running BBB
            return subprocess.CompletedProcess(argv, 0, "sha256:" + "b" * 64, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(fr.subprocess, "run", fake)
    drift = runner.image_drift()
    assert len(drift) == 1 and drift[0]["frame"] == "juice", drift
    assert "refused for an image that is correct" in drift[0]["note"]

    # and silent when they agree — a warning that is always on is a warning nobody reads
    monkeypatch.setattr(fr.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "sha256:" + "a" * 64, ""))
    assert runner.image_drift() == []


# ── §OPDIST (2026-09-16) — A CREDENTIAL INSIDE A STRING ──────────────────────────────────────────────────
# Both key hunts on this seam read KEY NAMES, so neither could see a credential inside a VALUE, while the stack
# phase REQUIRES `compose` — the largest string that crosses. The vhost check said so in its own docstring and
# fixed it for the vhost alone. These pin the widened rule AND, more importantly, pin that it does not refuse the
# legitimate path: the shape was chosen from a measurement, not from the four names.

SHIPPED_COMPOSE = HERE.parents[2] / "scripts" / "distribution" / "nginx-templates" / "docker-compose.operator.yml"


def test_the_shipped_operator_compose_is_accepted_which_is_the_control_that_decides_the_design():
    """THE CONTROL THAT MATTERS MOST. This compose carries DATABASE_URL six times and five DSNs; refusing the
    NAME — the obvious fix — would have refused every legitimate stack spec there has ever been, a gate that can
    only fail. It passes because every password in it is a `${PG_PASS_*}` placeholder. If this test ever goes red,
    the rule has started refusing the real path and the rule is wrong, not the compose."""
    if not SHIPPED_COMPOSE.exists():
        pytest.skip(f"LOUD SKIP: {SHIPPED_COMPOSE} is not in this tree, so the control cannot run")
    text = SHIPPED_COMPOSE.read_text()
    assert "DATABASE_URL" in text and "postgres" in text, "the control is measuring the wrong file"
    fr.scan_for_resolved_credentials(text, "spec.compose")  # must not raise


def test_RED_a_dsn_whose_password_is_resolved_is_refused():
    for bad in ("DATABASE_URL: postgresql://registry:hunter2@db:5432/agentvault_registry",
                "postgres://registry:s3cr3t@db/x",
                "postgresql+asyncpg://teg:literalpw@teg-db:5432/teg_layer",
                "services:\n  registry:\n    environment:\n      DATABASE_URL: postgres://u:pw@h/d\n"):
        with pytest.raises(fr.Refused) as e:
            fr.scan_for_resolved_credentials(bad, "spec.compose")
        assert "resolved value" in str(e.value), (bad, str(e.value))


def test_a_password_that_is_entirely_interpolation_is_topology_and_passes():
    for ok in ("DATABASE_URL: postgresql://registry:${PG_PASS_REGISTRY}@pgbouncer:6432/agentvault_registry",
               "postgres://u:$PG_PASS@h/d", "postgres://u:{{PG_PASS}}@h/d", "postgres://u:${A}${B}@h/d",
               "postgres://u@h/d"):  # a userinfo with no password is an address, not a credential
        fr.scan_for_resolved_credentials(ok, "spec.compose")


def test_RED_one_of_the_four_names_given_a_resolved_value_is_refused_even_with_no_dsn():
    with pytest.raises(fr.Refused) as e:
        fr.scan_for_resolved_credentials("API_KEY_SECRET=deadbeefdeadbeefdeadbeef", "spec.compose")
    assert "neither the frame's database nor a token" in str(e.value)
    fr.scan_for_resolved_credentials("API_KEY_SECRET=${API_KEY_SECRET}", "spec.compose")


def test_the_four_operator_secrets_are_not_refused_by_their_own_shape():
    """They are resolved by design and the one-shot is the thing that writes them. A scan that refused a 64-hex
    value would refuse every full and stack spec — the same failure as refusing the name, wearing entropy."""
    for v in ("a" * 64, "b" * 32, "0123456789abcdef" * 4):
        fr.scan_for_resolved_credentials(v, "spec.operator_secrets.TEG_PROXY_TRUST_SECRET")


def test_the_vhost_form_refuses_a_database_word_even_when_it_is_interpolated():
    """The surface-specific tightening, stated as a parameter rather than as a second rule: nginx never needs to
    name a database, so there the name alone is enough.

    ⚠ THIS TEST PINS THE RULE AND NOT THE WIRING — it passes the flag itself, so flipping the vhost's own call
    site to the lenient form leaves it green. A mutation run proved exactly that, which is why the test below
    exists. A unit test of a rule is not a test that the caller asks for it."""
    with pytest.raises(fr.Refused):
        fr.scan_for_resolved_credentials("# DATABASE_URL: ${X}", "vhost", allow_placeholders=False)
    with pytest.raises(fr.Refused):
        fr.scan_for_resolved_credentials("proxy_pass postgresql://x;", "vhost", allow_placeholders=False)
    fr.scan_for_resolved_credentials("server_name x.theprotocol.cloud;\nproxy_pass http://127.0.0.1:31300;",
                                     "vhost", allow_placeholders=False)


def test_RED_a_resolved_dsn_in_a_spec_string_is_refused_through_the_socket_at_any_depth(opsock):
    """Wired, not merely defined — and reached wherever a string can hide, including inside a list."""
    cfg, _ = opsock
    for bad in ({"compose": "DATABASE_URL: postgres://registry:hunter2@db/x"},
                {"env": {"SOME_BLOB": "postgres://registry:hunter2@db/x"}},
                {"env": {"deep": [{"blob": "postgres://registry:hunter2@db/x"}]}}):
        r = fr.call(cfg.operator_socket,
                    {"op": "operator_provision", "frame": "juice", "spec": _spec(**bad)}, timeout=30)
        assert r["ok"] is False, (bad, r)
        assert "resolved value" in r.get("refused", ""), (bad, r)


def test_a_spec_whose_strings_are_placeholders_gets_past_the_credential_scan(opsock):
    """Assert WHICH refusal fired: a spec carrying a placeholder compose must fail LATER, at the image check,
    never at the credential scan. A test that only asserted `ok is False` would pass with the gate refusing
    everything, which is the failure this whole rule was chosen to avoid."""
    cfg, _ = opsock
    spec = _spec(compose="DATABASE_URL: postgresql://registry:${PG_PASS_REGISTRY}@pgbouncer:6432/agentvault_registry")
    r = fr.call(cfg.operator_socket, {"op": "operator_provision", "frame": "juice", "spec": spec}, timeout=60)
    assert r["ok"] is False, r
    refused = r.get("refused", "")
    assert "resolved value" not in refused and "nor a token" not in refused, \
        f"the placeholder compose was refused by the credential scan: {refused}"
    assert "is not running" in refused or "not an allowlisted" in refused, refused


def test_the_vhost_check_itself_asks_for_the_strict_form(opsock):
    """FOUND BY MUTATION, not by review: flipping `allow_placeholders=False` to True inside _check_operator_vhost
    left every vhost test green, because they all called the scanner directly. This drives the method, so it can
    see the wiring — the "a gate that never calls the rail you changed cannot see the change you made" class."""
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    edge = {"domain": "tartu.theprotocol.cloud", "reg_port": "31300", "fed_port": "31343",
            "ssl_cert_name": "tartu.theprotocol.cloud"}
    good = ("server_name tartu.theprotocol.cloud;\n"
            "proxy_pass http://127.0.0.1:31300;\n"
            "ssl_certificate /etc/letsencrypt/live/tartu.theprotocol.cloud/fullchain.pem;\n")
    runner._check_operator_vhost(good, edge, "tartu")  # the legitimate vhost must still pass
    with pytest.raises(RuntimeError) as e:
        runner._check_operator_vhost(good + "# DATABASE_URL: ${PG_PASS_REGISTRY}\n", edge, "tartu")
    assert "DATABASE_URL" in str(e.value), str(e.value)


def test_RED_a_one_line_location_block_cannot_evade_any_of_the_three_property_checks(opsock):
    """A PARSER DIFFERENTIAL IN A GUARD IS THE GUARD BEING ABSENT.

    The three property checks were anchored with `^\\s*`, so they only saw a directive at the START of a line —
    while nginx reads one wherever it appears. Measured 2026-09-16: ONE line carrying a second server_name, a
    proxy_pass to an arbitrary OFF-HOST address and someone else's certificate was ACCEPTED, with all three
    checks finding nothing. Found only because I asserted to agentvault2-b5 that such a vhost would be refused
    and then measured the claim instead of shipping it.
    """
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    edge = {"domain": "tartu.theprotocol.cloud", "reg_port": "31300", "fed_port": "31343",
            "ssl_cert_name": "tartu.theprotocol.cloud"}
    good = ("server_name tartu.theprotocol.cloud;\n"
            "proxy_pass http://127.0.0.1:31300;\n"
            "ssl_certificate /etc/letsencrypt/live/tartu.theprotocol.cloud/fullchain.pem;\n")
    runner._check_operator_vhost(good, edge, "tartu")

    for label, line in (
        ("a second hostname", "location /x { server_name evil.example; }"),
        ("an off-host upstream", "location /x { proxy_pass http://10.0.0.9:9999; }"),
        ("an undeclared loopback port", "location /d { proxy_pass http://127.0.0.1:8099/; }"),
        ("someone else's certificate", "location /y { ssl_certificate /etc/letsencrypt/live/evil.example/f.pem; }"),
    ):
        with pytest.raises(RuntimeError):
            runner._check_operator_vhost(good + line + "\n", edge, "tartu")


def test_a_commented_directive_is_ignored_exactly_as_nginx_ignores_it():
    """The other half, and it is why comments are stripped rather than scanned: nginx does nothing with a
    commented directive, so refusing one would refuse a legitimate template. Resolve the question the way the
    thing being asked about resolves it. The CREDENTIAL scan still reads the full text, because a secret in a
    comment is still a secret this runner writes to disk as root."""
    edge = {"domain": "tartu.theprotocol.cloud", "reg_port": "31300",
            "ssl_cert_name": "tartu.theprotocol.cloud"}
    good = ("server_name tartu.theprotocol.cloud;\n"
            "proxy_pass http://127.0.0.1:31300;\n"
            "ssl_certificate /etc/letsencrypt/live/tartu.theprotocol.cloud/fullchain.pem;\n")
    fr.Runner._check_operator_vhost(None, good + "# proxy_pass http://example.invalid:1;\n", edge, "tartu")
    with pytest.raises(RuntimeError):
        fr.Runner._check_operator_vhost(None, good + "# DATABASE_URL: x\n", edge, "tartu")


# ── §OPDIST (2026-09-16, his answer "Both links first") — REGISTERING AN OPERATOR WITH ITS FRAME'S SERVICES ─────────
# A fake docker world: the kit auditor (its frames mount, its --uds command, its networks), the operator's db (found by
# compose labels, never by a spelled name), and an auditor that ANSWERS reload-venues by reading the venues.json the
# runner wrote, so the test checks the file, not the runner's intentions. Nothing here touches the live docker.

RO_PW = "ro+pw/with:odd@chars"


@pytest.fixture()
def world(rig, tmp_path, monkeypatch):
    cfg, srv, _ = rig
    runner = srv.runner
    frames = tmp_path / "kit-auditor-frames"
    frames.mkdir()
    (frames / "frames.json").write_text(json.dumps([{"id": "lantern", "mode": "prod", "currency": "AVT"}]))
    stack = tmp_path / "stack" / "cloud-op-tartu"
    state = {"auditor_nets": {"lantern_network": {}}, "reachable": True, "reload_status": 200, "calls": [],
             "note": ""}

    def inspect(name):
        if name == "lantern-auditor":
            return {"State": {"Running": True},
                    "Mounts": [{"Source": str(frames), "Destination": "/app/frames"}],
                    "Config": {"Cmd": ["sh", "-c", "umask 000 && exec uvicorn src.auditor.main:app --uds /sock/auditor/auditor.sock"]},
                    "NetworkSettings": {"Networks": dict(state["auditor_nets"])}}
        if name == "cloud-op-tartu-db":
            return {"State": {"Running": True},
                    "NetworkSettings": {"Networks": {"cloud-op-tartu_operator-net": {}}},
                    "Config": {"Env": ["POSTGRES_DB=agentvault_registry", "POSTGRES_USER=registry"],
                               "ExposedPorts": {"5432/tcp": {}}}}
        return None

    def fake_run(argv, **kw):
        state["calls"].append(argv)
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:2] == ["docker", "inspect"]:
            got = inspect(argv[2])
            return ok(json.dumps([got])) if got else subprocess.CompletedProcess(argv, 1, "", "No such object")
        if argv[:3] == ["docker", "ps", "-a"]:
            # split on the KEY, not the first "=": "label=" itself contains one (the first draft of this fake did
            # exactly that and never matched, so five tests reported NOT CONNECTED for a reason the code was right about)
            wd = next(a.split("working_dir=", 1)[1] for a in argv if a.startswith("label=com.docker.compose.project.working_dir="))
            svc = next(a.split("service=", 1)[1] for a in argv if a.startswith("label=com.docker.compose.service="))
            return ok("cloud-op-tartu-db\n" if (wd == str(stack) and svc == "db") else "")
        if argv[:3] == ["docker", "network", "connect"]:
            state["auditor_nets"][argv[3]] = {}
            return ok()
        if argv[:2] == ["docker", "exec"] and "lantern-registry" in argv:
            return ok("LNT\n")
        if argv[:3] == ["docker", "exec", "-i"] and argv[3] == "lantern-auditor":
            method, route = argv[-2], argv[-1]
            vp = frames / "venues.json"
            venues = json.loads(vp.read_text()) if vp.exists() else {}
            if method == "POST":
                return ok(json.dumps({"status": state["reload_status"], "body": {"venues": sorted(venues)}}))
            body = {"venues": {n: {"reachable": state["reachable"],
                                   "reach_status": state.get("reach_status") or ("ok" if state["reachable"] else "error"),
                                   "listings": [], "note": state["note"]} for n in venues}}
            return ok(json.dumps({"status": 200, "body": body}))
        raise AssertionError(f"unexpected subprocess in the links test: {argv}")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)

    def job(phase="stack", secrets=None, result=None):
        jid = f"{abs(hash((phase, str(secrets)))) % 16**16:016x}"   # the runner's job ids are 16 hex characters
        jd = pathlib.Path(runner.job_dir(jid))
        jd.mkdir(mode=0o700, parents=True, exist_ok=True)
        (jd / "spec.json").write_text(json.dumps({"phase": phase, "cloud_stack_dir": str(stack),
                                                  "operator_secrets": {"AUDITOR_RO_PASSWORD": RO_PW} if secrets is None else secrets}))
        return {"id": jid, "op": "operator_provision", "name": "lantern", "operator": "tartu", "state": "succeeded",
                "result": result or {}}

    return runner, frames, state, job


def test_RED_links_put_the_venue_in_the_frame_auditor_and_prove_reach(world):
    runner, frames, state, job = world
    rec = job()
    runner._register_operator_with_frame(rec)
    link = rec["links"]["auditor_venue"]
    assert link["connected"] is True and link["state"] == "CONNECTED", link
    assert ["docker", "network", "connect", "cloud-op-tartu_operator-net", "lantern-auditor"] in state["calls"]
    vp = frames / "venues.json"
    assert oct(vp.stat().st_mode & 0o777) == "0o600", "the carrier holds a password; the auditor reads it as uid 0"
    entry = json.loads(vp.read_text())["tartu"]
    from urllib.parse import quote, urlsplit
    u = urlsplit(entry["dsn"])
    assert (u.username, u.hostname, u.port, u.path) == ("auditor_ro", "cloud-op-tartu-db", 5432, "/agentvault_registry")
    assert u.password == quote(RO_PW, safe=""), "an odd password must be URL-quoted, not break the DSN"
    assert entry["currency"] == "LNT", "the frame's own published currency, not the kit's AVT literal"
    assert entry["frame"] == "lantern" and entry["mode"] == "prod"


def test_RED_no_ro_password_never_falls_back_to_the_owner_credential(world):
    runner, frames, state, job = world
    rec = job(secrets={})
    runner._register_operator_with_frame(rec)
    link = rec["links"]["auditor_venue"]
    assert link["connected"] is False and "AUDITOR_RO_PASSWORD" in link["why"], link
    assert not (frames / "venues.json").exists()
    assert not any(c[:3] == ["docker", "network", "connect"] for c in state["calls"])


def test_the_job_record_never_carries_the_password_even_when_the_auditor_echoes_it(world):
    runner, _, state, job = world
    state["reachable"] = False
    state["note"] = f"could not connect as auditor_ro:{RO_PW}@cloud-op-tartu-db"
    rec = job()
    runner._register_operator_with_frame(rec)
    assert rec["links"]["auditor_venue"]["connected"] is False
    assert RO_PW not in json.dumps(rec), "the password reached the job record, which operator_status can return"
    assert "<redacted>" in rec["links"]["auditor_venue"]["why"]


def test_unreachable_is_not_connected_with_the_auditors_own_reason(world):
    runner, _, state, job = world
    state["reachable"] = False
    state["note"] = "registry DB not reachable from the auditor"
    rec = job()
    runner._register_operator_with_frame(rec)
    link = rec["links"]["auditor_venue"]
    assert link["connected"] is False and "cannot reach it" in link["why"] and "not reachable" in link["why"], link


def test_RED_a_stale_reading_is_not_connected(world):
    # §OPDIST 2026-09-16: the auditor serves an EARLIER reading after a failed read ("stale", reachable True). A retry on
    # the same application keeps the same DSN, so an old cached reading could otherwise vouch for a new database whose
    # role cannot read the register. CONNECTED means the auditor's latest read of THIS entry succeeded.
    runner, _, state, job = world
    state["reach_status"] = "stale"
    state["note"] = ("the latest share read failed, so this is the reading from 2026-09-16T17:00:00+00:00: "
                     "permission denied for table exchange_trades")
    rec = job()
    runner._register_operator_with_frame(rec)
    link = rec["links"]["auditor_venue"]
    assert link["connected"] is False and link["state"] == "NOT CONNECTED", link
    assert "stale" in link["why"] and "permission denied for table exchange_trades" in link["why"], link


@pytest.fixture()
def tworld(world, tmp_path, monkeypatch):
    """§OPDIST 2026-09-16: operator_teardown and the auditor relink on world's fakes, plus the commands they add (the
    network disconnect, the project sweep, nginx). NEVER the live docker or /etc/nginx."""
    runner, frames, state, job = world
    inner = fr.subprocess.run
    stack = tmp_path / "stack" / "cloud-op-tartu"
    (stack / "spire").mkdir(parents=True)
    (stack / "docker-compose.operator.yml").write_text("services: {}\n")
    (stack / ".env.operator").write_text("X=1\n")
    (stack / "spire" / "agent-attestation.key").write_text("fixture, not a key\n")
    sites, backups = tmp_path / "sites-enabled", tmp_path / "vhost-backups"
    sites.mkdir(); backups.mkdir()
    (sites / "cloud-op-tartu").write_text("server { server_name tartu.op.example; }\n")
    sni = tmp_path / "federation-mtls.conf"
    sni.write_text("map $ssl_preread_server_name $federation_upstream {\n"
                   "    existing.op.example    127.0.0.1:26043;\n"
                   "    tartu.op.example    127.0.0.1:31543;\n"
                   "    # --- Default: the mainframe ---\n"
                   "    default                127.0.0.1:18443;\n"
                   "}\n")
    monkeypatch.setattr(fr.Runner, "NGINX_SITES", str(sites))
    monkeypatch.setattr(fr.Runner, "NGINX_BACKUPS", str(backups))
    monkeypatch.setattr(fr.Runner, "NGINX_SNI_MAP", str(sni))
    t = {"disconnect_rc": 0, "sticky": False, "named_like_it": [], "nginx_t_rc": 0, "order": [],
         "leftover": {"containers": ["c1", "c2"], "volumes": ["v1"], "networks": ["n1"]}}

    def outer(argv, **kw):
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:3] == ["docker", "network", "disconnect"]:
            t["order"].append("disconnect")
            if t["disconnect_rc"]:
                return subprocess.CompletedProcess(argv, 1, "", "fixture: the disconnect is refused")
            state["auditor_nets"].pop(argv[3], None)
            return ok()
        kind = {("docker", "ps", "-aq"): "containers", ("docker", "volume", "ls"): "volumes",
                ("docker", "network", "ls"): "networks"}.get(tuple(argv[:3]))
        if kind:
            assert "label=com.docker.compose.project=cloud-op-tartu" in argv, argv
            return ok("\n".join(t["leftover"][kind]) + "\n")
        if argv[:2] == ["docker", "rm"] or argv[:3] in (["docker", "volume", "rm"], ["docker", "network", "rm"]):
            t["order"].append("sweep")
            if not t["sticky"]:
                t["leftover"]["containers" if argv[1] == "rm" else argv[1] + "s"] = []
            return ok()
        if argv[:4] == ["docker", "ps", "-a", "--format"]:
            return ok("\n".join(["lantern-registry"] + t["named_like_it"]) + "\n")
        if argv and argv[0] == "nginx":
            t["order"].append(" ".join(argv))
            rc = t["nginx_t_rc"] if argv[1:2] == ["-t"] else 0
            return subprocess.CompletedProcess(argv, rc, "", "fixture: nginx refuses" if rc else "")
        return inner(argv, **kw)

    monkeypatch.setattr(fr.subprocess, "run", outer)
    runner.save_frame({"name": "lantern", "stack_dir": str(tmp_path / "stack" / "lantern-1"), "state": "live"})

    def provisioned(created="2026-09-16T10:00:00Z", op="operator_provision", phase="stack", st="succeeded", result=None,
                    refused=False):
        jid = f"{abs(hash((created, op, phase, st, refused))) % 16**16:016x}"
        rec = {"id": jid, "op": op, "name": "lantern", "operator": "tartu", "state": st, "created": created,
               "request": {"phase": phase}, "refused": refused,
               "result": result if result is not None else {"stack_dir": str(stack),
                                                            "sni_entry": "tartu.op.example    127.0.0.1:31543;"}}
        pathlib.Path(runner.job_dir(jid)).mkdir(mode=0o700, parents=True, exist_ok=True)
        runner.save_job(rec)
        return rec

    launched = []

    def fake_launch(op, uid, name, argv, request, **kw):
        t["order"].append("launch")
        launched.append({"op": op, "name": name, "argv": argv, "request": request, **kw})
        return {"id": kw.get("job_id"), "op": op, "name": name, "state": "running", "created": "now"}

    monkeypatch.setattr(runner, "launch", fake_launch)
    return {"runner": runner, "frames": frames, "state": state, "t": t, "stack": stack, "sites": sites,
            "backups": backups, "sni": sni, "provisioned": provisioned, "launched": launched}


def _teardown_req(**spec):
    return {"frame": "lantern", "spec": {"safe_name": "tartu", **spec}}


def _teardown_rec(w, jid="abcdef0000000001", provisioned_by_job=None):
    return {"id": jid, "op": "operator_teardown", "name": "lantern", "operator": "tartu", "state": "succeeded",
            "stack_dir": str(w["stack"]), "sni_name": "tartu.op.example", "unwire": {},
            "request": {"provisioned_by_job": provisioned_by_job}}


def test_RED_teardown_refuses_an_operator_this_runner_did_not_build(tworld):
    with pytest.raises(fr.Refused) as e:
        tworld["runner"].op_operator_teardown(_teardown_req(), 0)
    assert "nothing of this runner's to tear down" in str(e.value)
    assert not tworld["launched"]


def test_RED_the_newest_succeeded_job_decides_what_is_built(tworld):
    runner, provisioned = tworld["runner"], tworld["provisioned"]
    provisioned(created="2026-09-16T10:00:00Z")
    assert "tartu" in runner._operators_built("lantern")
    provisioned(created="2026-09-16T11:00:00Z", op="operator_teardown", phase="teardown")
    assert "tartu" not in runner._operators_built("lantern"), "a succeeded teardown undoes the provision before it"
    provisioned(created="2026-09-16T12:00:00Z", phase="bundle")
    assert "tartu" not in runner._operators_built("lantern"), "a bundle job builds no running operator"
    provisioned(created="2026-09-16T13:00:00Z")
    provisioned(created="2026-09-16T14:00:00Z", op="operator_teardown", phase="teardown", st="failed")
    assert "tartu" in runner._operators_built("lantern"), "a FAILED teardown must leave the operator tear-down-able"


def test_RED_teardown_refuses_purge_and_launches_nothing(tworld):
    tworld["provisioned"]()
    with pytest.raises(fr.Refused) as e:
        tworld["runner"].op_operator_teardown(_teardown_req(purge=True), 0)
    assert "purge" in str(e.value) and not tworld["launched"]


def test_RED_teardown_takes_the_stack_dir_from_the_provision_record_never_the_caller(tworld):
    tworld["provisioned"]()
    tworld["runner"].op_operator_teardown(_teardown_req(stack_dir="/etc", cloud_stack_dir="/etc"), 0)
    argv = tworld["launched"][0]["argv"]
    assert argv[:4] == ["docker", "compose", "-p", "cloud-op-tartu"]
    assert os.path.realpath(str(tworld["stack"] / "docker-compose.operator.yml")) in argv
    assert "/etc" not in " ".join(argv)
    assert argv[-3:] == ["down", "-v", "--remove-orphans"], "fresh passwords meet a kept volume on a re-provision"


def test_RED_teardown_brings_down_the_same_file_set_up_read(tworld):
    tworld["provisioned"]()
    (tworld["stack"] / "docker-compose.operator.dbtls.yml").write_text("services: {}\n")
    tworld["runner"].op_operator_teardown(_teardown_req(), 0)
    argv = tworld["launched"][0]["argv"]
    base = os.path.realpath(str(tworld["stack"] / "docker-compose.operator.yml"))
    over = os.path.realpath(str(tworld["stack"] / "docker-compose.operator.dbtls.yml"))
    assert argv[4:8] == ["-f", base, "-f", over], "base first, then every override the stack carries, as `up` passed them"


def test_RED_teardown_refuses_a_recorded_stack_dir_outside_the_stack_root(tworld):
    elsewhere = tworld["stack"].parent.parent / "elsewhere" / "cloud-op-tartu"
    elsewhere.mkdir(parents=True)
    tworld["provisioned"](result={"stack_dir": str(elsewhere), "sni_entry": "tartu.op.example 127.0.0.1:1;"})
    with pytest.raises(fr.Refused) as e:
        tworld["runner"].op_operator_teardown(_teardown_req(), 0)
    assert "refused rather than tearing down whatever it resolves to" in str(e.value) and not tworld["launched"]


def test_RED_the_auditor_leaves_the_network_and_the_venue_goes_before_compose_down(tworld):
    w = tworld
    w["provisioned"]()
    w["state"]["auditor_nets"]["cloud-op-tartu_operator-net"] = {}
    venues = w["frames"] / "venues.json"
    venues.write_text(json.dumps({"tartu": {"dsn": f"postgresql://auditor_ro:{RO_PW}@cloud-op-tartu-db:5432/x"},
                                  "other": {"dsn": "postgresql://auditor_ro:y@cloud-op-other-db:5432/x"}}))
    w["runner"].op_operator_teardown(_teardown_req(), 0)
    assert w["t"]["order"].index("disconnect") < w["t"]["order"].index("launch")
    assert "cloud-op-tartu_operator-net" not in w["state"]["auditor_nets"]
    left = json.loads(venues.read_text())
    assert "tartu" not in left and "other" in left, "only this operator's venue goes"
    assert oct(venues.stat().st_mode & 0o777) == "0o600"
    unwire = w["launched"][0]["extra"]["unwire"]
    assert unwire["network_disconnected"] and unwire["venue_removed"] and unwire["reload_venues"] == "applied", unwire


def test_RED_a_disconnect_that_fails_refuses_with_nothing_changed(tworld):
    w = tworld
    w["provisioned"]()
    w["state"]["auditor_nets"]["cloud-op-tartu_operator-net"] = {}
    venues = w["frames"] / "venues.json"
    venues.write_text(json.dumps({"tartu": {"dsn": "postgresql://auditor_ro:y@cloud-op-tartu-db:5432/x"}}))
    w["t"]["disconnect_rc"] = 1
    with pytest.raises(fr.Refused) as e:
        w["runner"].op_operator_teardown(_teardown_req(), 0)
    assert "nothing was torn down" in str(e.value)
    assert not w["launched"] and "tartu" in json.loads(venues.read_text())


def test_RED_finish_sweeps_then_removes_the_edge_then_deletes_the_stack_dir(tworld):
    w = tworld
    rec = _teardown_rec(w)
    w["runner"]._finish_operator_teardown(rec)
    assert rec["state"] == "succeeded", rec["notes"]
    assert rec["result"]["sweep"]["containers"] == {"swept": 2, "left": 0}
    assert not (w["sites"] / "cloud-op-tartu").exists()
    body = w["sni"].read_text()
    assert "tartu.op.example" not in body and "existing.op.example" in body and "default" in body
    order = w["t"]["order"]
    assert order.index("sweep") < order.index("nginx -t") < order.index("nginx -s reload")
    assert not w["stack"].exists(), "the stack dir, attestation key included, must not survive a teardown"
    assert rec["result"]["nginx_removed"] is True and rec["result"]["stack_removed"] is True
    assert list(w["backups"].glob("cloud-op-tartu.*.torn-down")), "the vhost is backed up before it goes"


def test_RED_a_succeeded_teardown_retires_the_provisions_admin_password(tworld):
    # beacon/jelgava: the torn-down provision's job record kept the first-boot admin password of a database that was gone
    w = tworld
    runner = w["runner"]
    prov = w["provisioned"](result={"stack_dir": str(w["stack"]), "sni_entry": "tartu.op.example 127.0.0.1:1;",
                                    "admin_password": "live-looking-fixture-pw"})
    rj = pathlib.Path(runner.job_dir(prov["id"])) / "result.json"
    rj.write_text(json.dumps(prov["result"]))
    rec = _teardown_rec(w, provisioned_by_job=prov["id"])
    runner._finish_operator_teardown(rec)
    assert rec["state"] == "succeeded", rec["notes"]
    assert "live-looking-fixture-pw" not in rj.read_text(), "result.json still holds the torn-down operator's password"
    assert "live-looking-fixture-pw" not in json.dumps(runner.job(prov["id"])), "job.json still holds it"
    assert oct(rj.stat().st_mode & 0o777) == "0o600"
    assert any("admin_password" in n for n in rec["notes"]), rec["notes"]


def test_RED_an_operator_jobs_result_file_is_owner_only_once_the_runner_reads_it(tworld):
    runner = tworld["runner"]
    jid = "abcdef000000000a"
    jd = pathlib.Path(runner.job_dir(jid))
    jd.mkdir(mode=0o700, parents=True, exist_ok=True)
    (jd / "result.json").write_text(json.dumps({"admin_password": "fixture"}))
    os.chmod(jd / "result.json", 0o644)                       # how the one-shot (uid 1000) leaves it
    runner.save_job({"id": jid, "op": "operator_provision", "name": "lantern", "operator": "tartu", "state": "running",
                     "created": "2026-09-16T16:00:00Z", "request": {"phase": "stack"}})
    runner._finish(jid, 4)
    assert oct((jd / "result.json").stat().st_mode & 0o777) == "0o600"


def test_a_failed_teardown_keeps_the_provisions_credential(tworld):
    w = tworld
    runner = w["runner"]
    w["t"]["sticky"] = True
    prov = w["provisioned"](result={"stack_dir": str(w["stack"]), "admin_password": "still-live-fixture-pw"})
    rec = _teardown_rec(w, provisioned_by_job=prov["id"])
    runner._finish_operator_teardown(rec)
    assert rec["state"] == "failed" and "still-live-fixture-pw" in json.dumps(runner.job(prov["id"])), \
        "a stack that is not gone still has its admin account; its password must not be scrubbed"


def test_RED_a_stack_that_is_not_gone_fails_and_keeps_the_edge_and_the_dir(tworld):
    w = tworld
    w["t"]["sticky"] = True
    rec = _teardown_rec(w)
    w["runner"]._finish_operator_teardown(rec)
    assert rec["state"] == "failed"
    assert (w["sites"] / "cloud-op-tartu").exists() and w["stack"].exists()
    assert not any(o.startswith("nginx") for o in w["t"]["order"])


def test_RED_an_unlabelled_container_named_like_the_operator_fails_the_teardown(tworld):
    w = tworld
    w["t"]["named_like_it"] = ["cloud-op-tartu-registry"]
    rec = _teardown_rec(w)
    w["runner"]._finish_operator_teardown(rec)
    assert rec["state"] == "failed" and w["stack"].exists()
    assert any("cloud-op-tartu-registry" in n for n in rec["notes"]), rec["notes"]


def test_RED_an_edge_removal_nginx_refuses_is_restored_and_the_dir_kept(tworld):
    w = tworld
    before_site, before_sni = (w["sites"] / "cloud-op-tartu").read_text(), w["sni"].read_text()
    w["t"]["nginx_t_rc"] = 1
    rec = _teardown_rec(w)
    w["runner"]._finish_operator_teardown(rec)
    assert rec["state"] == "failed"
    assert (w["sites"] / "cloud-op-tartu").read_text() == before_site and w["sni"].read_text() == before_sni
    assert "nginx -s reload" not in w["t"]["order"], "a refused config is never reloaded"
    assert w["stack"].exists()


def test_RED_finish_runs_the_teardown_host_work_only_after_a_succeeded_compose_down(tworld):
    w = tworld
    runner = w["runner"]
    for jid, code in (("abcdef0000000002", 1), ("abcdef0000000003", 0)):
        pathlib.Path(runner.job_dir(jid)).mkdir(mode=0o700, parents=True, exist_ok=True)
        runner.save_job({**_teardown_rec(w, jid), "state": "running", "created": "2026-09-16T16:00:00Z", "request": {}})
        runner._finish(jid, code)
        if code:
            assert runner.job(jid)["state"] == "failed" and w["stack"].exists() and not w["t"]["order"], \
                "a failed compose down must touch nothing else"
    done = runner.job("abcdef0000000003")
    assert done["state"] == "succeeded" and done["reason"] is None and not w["stack"].exists(), done.get("notes")


_COMPOSE_DOWN_LOG = (" Container cloud-op-tartu-registry  Stopping\n Container cloud-op-tartu-registry  Stopped\n"
                     " Container cloud-op-tartu-registry  Removing\n Container cloud-op-tartu-registry  Removed\n"
                     " Container cloud-op-tartu-db  Removed\n Container cloud-op-tartu-redis  Removed\n"
                     " Volume cloud-op-tartu_registry-data  Removing\n Volume cloud-op-tartu_registry-data  Removed\n"
                     " Network cloud-op-tartu_operator-net  Removed\n")


def test_RED_the_teardown_result_carries_what_compose_down_reported_removing(tworld):
    # V0391's registry reads containers_removed or network_removed as "the host half removed something"; beacon's first
    # runner-route teardown removed all of jelgava and still answered without them, so the registry stamped nothing
    w = tworld
    rec = _teardown_rec(w, "abcdef0000000004")
    jd = pathlib.Path(w["runner"].job_dir(rec["id"]))
    jd.mkdir(mode=0o700, parents=True, exist_ok=True)
    (jd / "stdout.log").write_text(_COMPOSE_DOWN_LOG)
    w["runner"]._finish_operator_teardown(rec)
    res = rec["result"]
    assert rec["state"] == "succeeded", rec["notes"]
    assert res["containers_removed"] == 3 + 2, "compose's three `Removed` containers plus the two the sweep removed"
    assert res["volumes_removed"] == 1 + 1 and res["network_removed"] is True
    assert res["nginx_removed"] is True and res["notes"] and res["venue_unwired"] is False


def test_RED_a_retried_teardown_answers_the_succeeded_job_instead_of_refusing(tworld):
    w = tworld
    runner = w["runner"]
    w["provisioned"](created="2026-09-16T10:00:00Z")
    done = w["provisioned"](created="2026-09-16T11:00:00Z", op="operator_teardown", phase="teardown",
                            result={"phase": "teardown", "sweep": {"containers": {"swept": 0, "left": 0}},
                                    "nginx_removed": True, "stack_removed": True})
    (pathlib.Path(runner.job_dir(done["id"])) / "stdout.log").write_text(_COMPOSE_DOWN_LOG)
    status = runner.op_operator_status({"frame": "lantern", "job_id": done["id"]}, 0)
    assert status["job"]["state"] == "succeeded"
    assert status["result"]["containers_removed"] == 3 and status["result"]["network_removed"] is True, \
        "a record that predates the removal fields gains them from its own compose output, where the result is read"
    out = runner.op_operator_teardown(_teardown_req(), 0)
    assert out["started"] is False and out["already_torn_down"] is True and out["job_id"] == done["id"], out
    assert not w["launched"], "a teardown already done must not launch a second compose down"


def test_RED_a_provision_that_failed_after_starting_work_is_tear_down_able(tworld):
    # beacon/jelgava 908a9513d677432c: after a succeeded teardown, a re-provision failed at compose up with seven
    # containers running; "already torn down" there would strand them and their initialised volumes
    w = tworld
    w["provisioned"](created="2026-09-16T10:00:00Z")
    w["provisioned"](created="2026-09-16T11:00:00Z", op="operator_teardown", phase="teardown")
    w["provisioned"](created="2026-09-16T12:00:00Z", st="failed", result={})
    out = w["runner"].op_operator_teardown(_teardown_req(), 0)
    assert out["started"] is True and not out.get("already_torn_down"), out
    launched = w["launched"][0]
    assert launched["request"]["partial"] is True
    assert os.path.realpath(str(w["stack"] / "docker-compose.operator.yml")) in launched["argv"], \
        "a failed provision recorded no stack dir; the operator's own name under the stack root is used"
    assert "tartu" not in w["runner"]._operators_built("lantern"), "a partial stack is never relinked as built"


def test_RED_a_refused_provision_decides_nothing(tworld):
    w = tworld
    w["provisioned"](created="2026-09-16T10:00:00Z")
    done = w["provisioned"](created="2026-09-16T11:00:00Z", op="operator_teardown", phase="teardown")
    w["provisioned"](created="2026-09-16T12:00:00Z", st="failed", result={}, refused=True)
    out = w["runner"].op_operator_teardown(_teardown_req(), 0)
    assert out["already_torn_down"] is True and out["job_id"] == done["id"] and not w["launched"], out


def test_RED_the_only_venue_leaving_reads_applied(tworld):
    # an empty venue list is the auditor's answer when this operator was its only venue (beacon, jelgava)
    w = tworld
    w["provisioned"]()
    (w["frames"] / "venues.json").write_text(json.dumps({"tartu": {"dsn": "postgresql://auditor_ro:y@h:5432/x"}}))
    w["runner"].op_operator_teardown(_teardown_req(), 0)
    assert w["launched"][0]["extra"]["unwire"]["reload_venues"] == "applied"


def test_RED_relink_reattaches_only_the_operators_this_runner_built(tworld):
    w = tworld
    w["provisioned"]()
    (w["frames"] / "venues.json").write_text(json.dumps({
        "tartu": {"dsn": "postgresql://auditor_ro:x@cloud-op-tartu-db:5432/agentvault_registry"},
        "intruder": {"dsn": "postgresql://auditor_ro:z@cloud-op-intruder-db:5432/agentvault_registry"}}))
    assert "cloud-op-tartu_operator-net" not in w["state"]["auditor_nets"]   # as after a recreate
    out = w["runner"]._relink_auditor("lantern")
    connects = [c for c in w["state"]["calls"] if c[:3] == ["docker", "network", "connect"]]
    assert connects == [["docker", "network", "connect", "cloud-op-tartu_operator-net", "lantern-auditor"]], connects
    assert out["operators"]["tartu"]["state"] == "ATTACHED" and out["operators"]["tartu"]["was"] == "re-attached"
    assert out["venues_with_no_runner_job"] == ["intruder"], "a venues.json name is named, never attached"
    assert out["state"] == "RELINKED"


def test_relink_is_a_frame_op_never_an_operator_op():
    assert "relink_auditor" in fr.OPS and "relink_auditor" not in fr.OPERATOR_OPS


def test_RED_relink_refuses_a_frame_this_runner_did_not_build(tworld):
    with pytest.raises(fr.Refused):
        tworld["runner"].op_relink_auditor({"frame": "orchard"}, 0)


def test_RED_a_succeeded_resume_relinks_the_auditor(tworld, monkeypatch):
    runner = tworld["runner"]
    called = []
    monkeypatch.setattr(runner, "_relink_auditor", lambda name: called.append(name) or {"state": "RELINKED"})
    jid = "abcdef0000000009"
    pathlib.Path(runner.job_dir(jid)).mkdir(mode=0o700, parents=True, exist_ok=True)
    runner.save_job({"id": jid, "op": "resume", "name": "lantern", "state": "running",
                     "created": "2026-09-16T16:00:00Z", "request": {}})
    runner._finish(jid, 0)
    assert called == ["lantern"] and runner.job(jid)["relink"] == {"state": "RELINKED"}


def test_an_unparsable_venues_file_is_left_untouched(world):
    runner, frames, _, job = world
    (frames / "venues.json").write_text("{ not json")
    rec = job()
    runner._register_operator_with_frame(rec)
    assert rec["links"]["auditor_venue"]["connected"] is False
    assert (frames / "venues.json").read_text() == "{ not json"


def test_a_refused_reload_is_not_connected(world):
    runner, _, state, job = world
    state["reload_status"] = 422
    rec = job()
    runner._register_operator_with_frame(rec)
    assert rec["links"]["auditor_venue"]["connected"] is False and "422" in rec["links"]["auditor_venue"]["why"]


def test_a_refused_reload_that_echoes_the_password_is_redacted_too(world, monkeypatch):
    """Redaction happens on TWO paths, and the first version of these tests pinned only the reach path: a mutation that
    removed the reload path's redaction had nothing to fail. An auditor error that echoes the DSN must not carry the
    password into the job record either."""
    runner, _, state, job = world
    real = fr.subprocess.run

    def echoing(argv, **kw):
        if argv[:3] == ["docker", "exec", "-i"] and argv[-2] == "POST":
            return subprocess.CompletedProcess(argv, 0, json.dumps(
                {"status": 422, "body": {"error": f"cannot use postgresql://auditor_ro:{RO_PW}@cloud-op-tartu-db"}}), "")
        return real(argv, **kw)

    monkeypatch.setattr(fr.subprocess, "run", echoing)
    rec = job()
    runner._register_operator_with_frame(rec)
    assert rec["links"]["auditor_venue"]["connected"] is False
    assert RO_PW not in json.dumps(rec), "the reload refusal carried the password into the job record"
    assert "<redacted>" in rec["links"]["auditor_venue"]["why"]


def test_a_bundle_job_registers_nothing(world):
    runner, frames, state, job = world
    rec = job(phase="bundle")
    runner._register_operator_with_frame(rec)
    assert "links" not in rec or not rec["links"]
    assert not state["calls"] and not (frames / "venues.json").exists()


def test_registering_twice_neither_reconnects_nor_rewrites(world):
    runner, frames, state, job = world
    runner._register_operator_with_frame(job())
    mtime = (frames / "venues.json").stat().st_mtime_ns
    state["calls"].clear()
    rec = job()
    runner._register_operator_with_frame(rec)
    assert rec["links"]["auditor_venue"]["connected"] is True
    assert not any(c[:3] == ["docker", "network", "connect"] for c in state["calls"]), "already a member: no reconnect"
    assert (frames / "venues.json").stat().st_mtime_ns == mtime, "an unchanged entry must not be rewritten"


def test_the_runner_takes_no_directory_step_because_the_operator_reads_the_parents_public_proxy(world):
    """Pins an ABSENCE, so the step is not re-invented. Measured 2026-09-16: an operator reads its parent's index through
    the parent's public directory proxy (health and graphql 200 from inside amsterdam and against lantern), so the
    directory link is two env values the provisioner writes. The fake raises on any subprocess it does not know, so a
    docker exec into a directory container would fail this test as well as the assertion."""
    runner, _, state, job = world
    rec = job(result={"operator_spiffe_id": "spiffe://lantern.theprotocol.cloud/operator/tartu/svid-writer"})
    runner._register_operator_with_frame(rec)
    assert "directory_reader" not in rec["links"], rec["links"]
    assert not any("directory" in " ".join(c) for c in state["calls"]), state["calls"]


def test_finish_marks_links_pending_then_done_and_only_after_a_succeeded_provision(rig, monkeypatch):
    """The wiring: a poller that sees 'succeeded' must also see the links are still being made, and a failed or
    non-provision job must never register anything."""
    cfg, srv, _ = rig
    runner = srv.runner
    seen = []
    monkeypatch.setattr(runner, "_apply_operator_edge", lambda rec: None)

    def fake_register(rec):
        # what a POLLER reads is the saved record, so that is what must say pending while registration runs
        saved = runner.job(rec["id"])
        seen.append((rec["id"], rec.get("links_state"), saved.get("links_state")))

    monkeypatch.setattr(runner, "_register_operator_with_frame", fake_register)
    for jid, op, code in (("f1a0000000000001", "operator_provision", 0), ("f1a0000000000002", "operator_provision", 4),
                          ("f1a0000000000003", "standup", 0)):
        jd = pathlib.Path(runner.job_dir(jid)); jd.mkdir(mode=0o700, parents=True, exist_ok=True)
        (jd / "result.json").write_text("{}")
        runner.save_job({"id": jid, "op": op, "name": "lantern", "operator": "tartu", "state": "running", "created": fr.now()})
        runner._finish(jid, code)
    assert [s[0] for s in seen] == ["f1a0000000000001"], seen
    assert seen[0][1] == "pending" and seen[0][2] == "pending", \
        f"registration must run while the SAVED record says pending, so a poller cannot read succeeded as connected: {seen}"
    assert runner.job("f1a0000000000001")["links_state"] == "done"


# ── §OPDIST (2026-09-16) — THE ONE-SHOT'S USER, FOUND BY THE FIRST LIVE RUN ─────────────────────────────────────────────
# Tartu's first provision died in 1 s: `PermissionError: [Errno 13] Permission denied: '/work/spec.json'`. The runner staged
# a 0600 root spec in a 0700 root dir, and the registry image runs as its own user (agentvault, uid 1000). Every test here
# FAKED the launch, which is how it survived. The last test below starts a REAL container from the real registry image.

def test_the_oneshot_runs_as_the_image_user_with_the_socket_group_and_gid_0(opsock):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    argv = runner._operator_oneshot_argv("a" * 16, "/tmp/jd", "sha256:" + "b" * 64)
    groups = [argv[i + 1] for i, a in enumerate(argv) if a == "--group-add"]
    assert str(os.stat("/var/run/docker.sock").st_gid) in groups, groups
    assert "0" in groups, "without gid 0 the image user cannot traverse a runner-built frame's 0750 stack dir"
    for forbidden in ("--user", "-u", "--privileged", "--pid"):
        assert forbidden not in argv, f"{forbidden} in the one-shot's argv"


def test_staging_is_0770_and_0640_whatever_the_umask(opsock, tmp_path):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    old = os.umask(0o077)
    try:
        jd = tmp_path / "jobs" / ("c" * 16)
        spec_path = runner._stage_operator_work(str(jd), {"phase": "bundle"})
    finally:
        os.umask(old)
    assert oct(os.stat(jd).st_mode & 0o777) == "0o770"
    assert oct(os.stat(spec_path).st_mode & 0o777) == "0o640"


def _local_registry_image():
    r = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "agentvault2-registry-a"],
                       capture_output=True, text=True, timeout=30)
    tags = [t for t in (r.stdout or "").split() if re.fullmatch(r"agentvault2-registry-a:v0\d{3}", t)]
    return sorted(tags)[-1] if tags else None


import re  # noqa: E402  (the helper above needs it at module level)


def test_RED_a_real_oneshot_container_can_read_its_spec_write_its_result_reach_the_bundles_and_the_socket(opsock, tmp_path):
    """THE TEST THAT WOULD HAVE CAUGHT IT. The production staging and the production argv, one real container from the
    real registry image; only the final command is swapped for a probe of the four things the one-shot needs."""
    if not os.path.exists("/var/run/docker.sock"):
        pytest.skip("LOUD SKIP: no docker socket, so the one-shot cannot be started here; the property is UNTESTED")
    image = _local_registry_image()
    if not image:
        pytest.skip("LOUD SKIP: no local agentvault2-registry-a:vNNNN image; the property is UNTESTED, not satisfied")
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    stack_root = pathlib.Path(cfg.stack_root)
    frame_dir = stack_root / "probe-frame-1"
    bundles = frame_dir / "operator-bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    os.chmod(stack_root, 0o755); os.chmod(frame_dir, 0o750); os.chmod(bundles, 0o777)   # a runner-built frame's shape
    job_id = "d" * 16
    jd = pathlib.Path(runner.job_dir(job_id))
    runner._stage_operator_work(str(jd), {"phase": "bundle", "frame_stack_dir": str(frame_dir)})
    argv = runner._operator_oneshot_argv(job_id, str(jd), image)
    cut = argv.index("--entrypoint")
    probe = (
        "import json, os, socket\n"
        "out = {'uid': os.getuid()}\n"
        "spec = json.load(open('/work/spec.json')); out['spec'] = spec.get('phase') == 'bundle'\n"
        "open('/work/result.json', 'w').write('{}'); out['result'] = True\n"
        "p = os.path.join(spec['frame_stack_dir'], 'operator-bundles', 'probe.txt'); open(p, 'w').write('x'); out['bundle'] = True\n"
        "s = socket.socket(socket.AF_UNIX); s.settimeout(10); s.connect('/var/run/docker.sock')\n"
        "s.sendall(b'GET /_ping HTTP/1.0\\r\\nHost: docker\\r\\n\\r\\n'); out['socket'] = b'OK' in s.recv(4096)\n"
        "print(json.dumps(out))\n")
    argv = argv[:cut] + ["--entrypoint", "python3", image, "-c", probe]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"the one-shot could not do its job: {(r.stderr or r.stdout)[-400:]}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got == {"uid": 1000, "spec": True, "result": True, "bundle": True, "socket": True}, got
    assert (jd / "result.json").exists() and (bundles / "probe.txt").stat().st_uid == 1000


# ── §OPDIST — the Redis ACL the one-shot (uid 1000) cannot chown; the result names it, the runner (root) makes the change ─

@pytest.fixture()
def acl(opsock):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    stack = pathlib.Path(cfg.stack_root) / "cloud-op-tartu"
    stack.mkdir(parents=True, exist_ok=True)
    f = stack / "redis-users.acl"
    f.write_text("user default off\n")
    os.chown(f, 1000, 1000); os.chmod(f, 0o600)

    def rec(**result):
        return {"id": "e" * 16, "op": "operator_provision", "operator": "tartu", "state": "succeeded", "result": result}

    return runner, stack, f, rec


def test_RED_a_named_acl_gets_the_redis_owner_and_keeps_its_group(acl):
    runner, _, f, rec = acl
    r = rec(redis_acl_chown_needed=True, redis_acl_path=str(f), redis_acl_uid=999)
    runner._apply_operator_redis_acl(r)
    st = os.stat(f)
    assert (st.st_uid, st.st_gid) == (999, 1000) and r["state"] == "succeeded", (st.st_uid, st.st_gid, r)
    assert any("owner -> 999" in n for n in r["notes"])


@pytest.mark.parametrize("result", [{}, {"redis_acl_chown_needed": False, "redis_acl_path": "x", "redis_acl_uid": 999}])
def test_no_request_changes_nothing(acl, result):
    runner, _, f, rec = acl
    r = rec(**result)
    runner._apply_operator_redis_acl(r)
    assert os.stat(f).st_uid == 1000 and r["state"] == "succeeded" and "notes" not in r


@pytest.mark.parametrize("path_kind", ["outside_root", "sibling", "symlink_out"])
def test_RED_a_path_outside_this_operators_stack_is_refused_and_untouched(acl, tmp_path, path_kind):
    runner, stack, f, rec = acl
    # ⚠ never a real host file: if the guard ever regressed, a test aimed at /etc would perform a root chown on the host
    if path_kind == "outside_root":
        outside = tmp_path / "not-under-the-stack-root.acl"; outside.write_text("x"); target = str(outside)
    elif path_kind == "sibling":
        other = stack.parent / "cloud-op-narva"; other.mkdir(exist_ok=True)
        (other / "redis-users.acl").write_text("x"); target = str(other / "redis-users.acl")
    else:
        outside = tmp_path / "outside.acl"; outside.write_text("x")
        link = stack / "evil.acl"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(outside); target = str(link)
    before = os.stat(os.path.realpath(target)).st_uid
    r = rec(redis_acl_chown_needed=True, redis_acl_path=target, redis_acl_uid=999)
    runner._apply_operator_redis_acl(r)
    assert r["state"] == "failed" and any("REFUSED" in n for n in r["notes"]), r
    assert os.stat(os.path.realpath(target)).st_uid == before


@pytest.mark.parametrize("uid", [0, -1, 70000, "999", True, None])
def test_RED_a_uid_that_is_not_a_uid_is_refused(acl, uid):
    runner, _, f, rec = acl
    r = rec(redis_acl_chown_needed=True, redis_acl_path=str(f), redis_acl_uid=uid)
    runner._apply_operator_redis_acl(r)
    assert r["state"] == "failed" and os.stat(f).st_uid == 1000, (uid, r)


def test_finish_applies_the_acl_after_a_succeeded_provision(acl, monkeypatch):
    runner, _, f, _ = acl
    monkeypatch.setattr(runner, "_apply_operator_edge", lambda rec: None)
    monkeypatch.setattr(runner, "_register_operator_with_frame", lambda rec: None)
    jid = "f2a0000000000001"
    jd = pathlib.Path(runner.job_dir(jid)); jd.mkdir(mode=0o700, parents=True, exist_ok=True)
    (jd / "result.json").write_text(json.dumps({"redis_acl_chown_needed": True, "redis_acl_path": str(f), "redis_acl_uid": 999}))
    runner.save_job({"id": jid, "op": "operator_provision", "name": "lantern", "operator": "tartu", "state": "running",
                     "created": fr.now()})
    runner._finish(jid, 0)
    assert os.stat(f).st_uid == 999 and runner.job(jid)["state"] == "succeeded"


# ── §OPDIST (2026-09-16) — THE ONE-SHOT'S SPIRE TARGET, CA AND TEMPLATES, FOUND BY BEACON'S FIRST PROVISION ─────────────
# Job d1de1776f2394128 died in 1 s: `FileNotFoundError: CA key not found at /opt/spire-ca/attestation-ca.key`. The bundle
# phase runs operator_provisioner.provision_operator, which reads its SPIRE target from ENV (SPIRE_CONTAINER and
# SPIRE_TRUST_DOMAIN default to Frame A's `agentvault-spire-server` and `agentvault.com`) and its attestation CA and nginx
# templates from DIRECTORIES the frame's registry has as mounts and the image does not carry. The one-shot had none of it.
# Had the CA been there, the next call would have registered the operator's SPIRE entries in FRAME A's server.

def _frame_world(tmp_path, *, env=None, mounts=None, spire_wd=None):
    """A fake docker for _frame_provisioner_inputs: the frame's registry container and the SPIRE container it names."""
    sd = str(tmp_path / "stack" / "juice-1")
    ca_src, tpl_src = str(tmp_path / "stack" / "juice-1" / "x509pop-certs"), str(tmp_path / "tpl")
    env = env if env is not None else [
        "SPIRE_CONTAINER=juice-spire-server", "SPIRE_TRUST_DOMAIN=juice.theprotocol.cloud",
        "SPIRE_SERVER_ADDRESS=juice-spire.theprotocol.cloud", "SPIRE_SERVER_PORT=8515",
        "DATABASE_URL=postgresql+asyncpg://u:not-a-real-password@db/x", "TEG_ADMIN_API_KEY=" + "f" * 64,
        "PATH=/usr/local/bin:/usr/bin"]
    mounts = mounts if mounts is not None else [
        {"Type": "bind", "Source": ca_src, "Destination": "/opt/spire-ca", "RW": False},
        {"Type": "bind", "Source": tpl_src, "Destination": "/app/nginx-templates", "RW": False},
        {"Type": "bind", "Source": sd + "/operator-bundles", "Destination": "/app/operator-bundles", "RW": True}]
    wd = spire_wd if spire_wd is not None else sd

    def fake_run(argv, **kw):
        if argv[:2] == ["docker", "inspect"] and argv[2] == "juice-registry":
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Config": {"Env": env}, "Mounts": mounts}]), "")
        if argv[:2] == ["docker", "inspect"] and argv[2] == "juice-spire-server":
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Config": {"Labels": {
                "com.docker.compose.project.working_dir": wd}}, "State": {"Running": True}}]), "")
        return subprocess.CompletedProcess(argv, 1, "", "no such object")

    return {"name": "juice", "stack_dir": sd}, fake_run, ca_src, tpl_src


def test_RED_the_oneshot_carries_the_frames_spire_target_ca_and_templates_and_nothing_else(opsock, tmp_path, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    frame, fake_run, ca_src, tpl_src = _frame_world(tmp_path)
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    inputs = runner._frame_provisioner_inputs(frame)
    argv = runner._operator_oneshot_argv("a" * 16, "/tmp/jd", "sha256:" + "b" * 64, inputs)
    assert "SPIRE_CONTAINER=juice-spire-server" in argv and "SPIRE_TRUST_DOMAIN=juice.theprotocol.cloud" in argv, argv
    assert "SPIRE_SERVER_ADDRESS=juice-spire.theprotocol.cloud" in argv and "SPIRE_SERVER_PORT=8515" in argv, argv
    assert f"{ca_src}:/opt/spire-ca:ro" in argv and f"{tpl_src}:/app/nginx-templates:ro" in argv, argv
    flat = " ".join(argv)
    for leak in ("DATABASE_URL", "not-a-real-password", "TEG_ADMIN_API_KEY", "f" * 64, "PATH=/usr/local"):
        assert leak not in flat, f"{leak} crossed into the one-shot: only the allowlisted names may"
    # the inputs sit before the image, where docker reads options
    assert argv.index("--entrypoint") > max(i for i, a in enumerate(argv) if a in ("-e", "-v"))


@pytest.mark.parametrize("missing", ["SPIRE_CONTAINER", "SPIRE_TRUST_DOMAIN"])
def test_RED_a_frame_registry_without_its_spire_target_is_refused(opsock, tmp_path, monkeypatch, missing):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    env = [e for e in ["SPIRE_CONTAINER=juice-spire-server", "SPIRE_TRUST_DOMAIN=juice.theprotocol.cloud"]
           if not e.startswith(missing + "=")]
    frame, fake_run, _, _ = _frame_world(tmp_path, env=env)
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(fr.Refused) as e:
        runner._frame_provisioner_inputs(frame)
    assert missing in str(e.value) and "Frame A" in str(e.value), e.value


def test_RED_a_spire_container_outside_the_frames_own_stack_is_refused(opsock, tmp_path, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    frame, fake_run, _, _ = _frame_world(tmp_path, spire_wd=str(tmp_path / "stack" / "some-other-frame-1"))
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(fr.Refused) as e:
        runner._frame_provisioner_inputs(frame)
    assert "juice-spire-server" in str(e.value) and "own stack" in str(e.value), e.value


@pytest.mark.parametrize("dest", ["/opt/spire-ca", "/app/nginx-templates"])
def test_RED_a_frame_registry_without_the_ca_or_templates_mount_is_refused(opsock, tmp_path, monkeypatch, dest):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    frame, _, ca_src, tpl_src = _frame_world(tmp_path)
    mounts = [m for m in [{"Type": "bind", "Source": ca_src, "Destination": "/opt/spire-ca"},
                          {"Type": "bind", "Source": tpl_src, "Destination": "/app/nginx-templates"}] if m["Destination"] != dest]
    frame, fake_run, _, _ = _frame_world(tmp_path, mounts=mounts)
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(fr.Refused) as e:
        runner._frame_provisioner_inputs(frame)
    assert dest in str(e.value), e.value


def test_RED_an_allowlisted_value_of_an_unexpected_shape_is_refused_without_echoing_it(opsock, tmp_path, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    odd = "juice.theprotocol.cloud; curl evil"
    frame, fake_run, _, _ = _frame_world(tmp_path, env=["SPIRE_CONTAINER=juice-spire-server", f"SPIRE_TRUST_DOMAIN={odd}"])
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(fr.Refused) as e:
        runner._frame_provisioner_inputs(frame)
    assert "SPIRE_TRUST_DOMAIN" in str(e.value) and "curl" not in str(e.value), e.value


@pytest.mark.parametrize("field,value", [("spire_container", "eu-spire-server"), ("spire_trust_domain", "eu.theprotocol.cloud")])
def test_RED_a_spec_naming_another_spire_is_refused_before_anything_is_staged(opsock, monkeypatch, field, value):
    """The stack phase execs into spec.spire_container with the docker socket. A frame's registry must not be able to aim
    that at another frame's SPIRE by saying so: the value is compared with the frame's own, and a disagreement refuses."""
    cfg, tmp_path = opsock
    runner = fr.Runner(cfg)
    monkeypatch.setattr(runner, "host_gates", lambda: [])
    monkeypatch.setattr(runner, "active", lambda: None)
    monkeypatch.setattr(runner, "_operator_image", lambda name: "sha256:" + "e" * 64)
    (tmp_path / "stack" / "juice-1").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(runner, "_frame_identity_network", lambda f: "juice_network_identity")
    monkeypatch.setattr(runner, "_frame_provisioner_inputs", lambda f: {
        "env": {"SPIRE_CONTAINER": "juice-spire-server", "SPIRE_TRUST_DOMAIN": "juice.theprotocol.cloud"}, "binds": []})
    launched = []
    monkeypatch.setattr(runner, "launch", lambda *a, **k: launched.append(a) or {"id": "x", "state": "running"})
    with pytest.raises(fr.Refused) as e:
        runner.handle({"op": "operator_provision", "frame": "juice", "spec": {**_spec(), field: value}}, 0, fr.OPERATOR_OPS)
    assert field in str(e.value) and not launched, e.value
    assert not list(pathlib.Path(cfg.state, "jobs").glob("*/spec.json")) if pathlib.Path(cfg.state, "jobs").exists() else True


def test_RED_a_real_oneshot_reads_the_frames_ca_and_templates_through_its_binds(opsock, tmp_path):
    """The mount half proven by a REAL container as the image user, the way the spec half is above: a 0644 root CA key in
    a 0755 dir under a 0750 root stack dir, bound read-only at the provisioner's own default path."""
    if not os.path.exists("/var/run/docker.sock"):
        pytest.skip("LOUD SKIP: no docker socket, so the one-shot cannot be started here; the property is UNTESTED")
    image = _local_registry_image()
    if not image:
        pytest.skip("LOUD SKIP: no local agentvault2-registry-a:vNNNN image; the property is UNTESTED, not satisfied")
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    stack_root = pathlib.Path(cfg.stack_root)
    frame_dir = stack_root / "probe-frame-2"
    ca = frame_dir / "x509pop-certs"; ca.mkdir(parents=True, exist_ok=True)
    (ca / "attestation-ca.key").write_text("probe-not-a-key\n")
    tpl = tmp_path / "tpl"; tpl.mkdir(); (tpl / "nginx.conf.template").write_text("probe\n")
    os.chmod(stack_root, 0o755); os.chmod(frame_dir, 0o750); os.chmod(ca, 0o755); os.chmod(ca / "attestation-ca.key", 0o644)
    os.chmod(tmp_path, 0o755); os.chmod(tpl, 0o755); os.chmod(tpl / "nginx.conf.template", 0o644)
    inputs = {"env": {"SPIRE_CONTAINER": "probe-spire-server", "SPIRE_TRUST_DOMAIN": "probe.theprotocol.cloud"},
              "binds": [(str(ca), "/opt/spire-ca"), (str(tpl), "/app/nginx-templates")]}
    job_id = "f" * 16
    jd = pathlib.Path(runner.job_dir(job_id))
    runner._stage_operator_work(str(jd), {"phase": "bundle", "frame_stack_dir": str(frame_dir)})
    argv = runner._operator_oneshot_argv(job_id, str(jd), image, inputs)
    cut = argv.index("--entrypoint")
    probe = ("import json, os\n"
             "print(json.dumps({'uid': os.getuid(), 'ca': open('/opt/spire-ca/attestation-ca.key').read().strip(),\n"
             "  'tpl': sorted(os.listdir('/app/nginx-templates')), 'td': os.environ.get('SPIRE_TRUST_DOMAIN'),\n"
             "  'ro': not os.access('/opt/spire-ca', os.W_OK)}))\n")
    r = subprocess.run(argv[:cut] + ["--entrypoint", "python3", image, "-c", probe], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"the one-shot could not read what the provisioner reads: {(r.stderr or r.stdout)[-400:]}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got == {"uid": 1000, "ca": "probe-not-a-key", "tpl": ["nginx.conf.template"], "td": "probe.theprotocol.cloud",
                   "ro": True}, got


# ── §OPDIST (2026-09-16) — THE IMAGE CARRIES NO COMPOSE PLUGIN ───────────────────────────────────────────────────────────
# Measured in V0385 as uid 1000 with the socket group: `docker: unknown command: docker compose`. The Dockerfile copies
# only /usr/local/bin/docker out of docker:cli, because the in-registry path ran compose in a docker:cli SIDECAR, while
# host_work's stack phase calls `docker compose` itself: every stack phase would fail after the activation code is spent.

def _provision_stubs(runner, monkeypatch, launched):
    monkeypatch.setattr(runner, "host_gates", lambda: [])
    monkeypatch.setattr(runner, "active", lambda: None)
    monkeypatch.setattr(runner, "_operator_image", lambda name: "sha256:" + "e" * 64)
    monkeypatch.setattr(runner, "_frame_identity_network", lambda f: "juice_network_identity")
    monkeypatch.setattr(runner, "_frame_provisioner_inputs", lambda f: {
        "env": {"SPIRE_CONTAINER": "juice-spire-server", "SPIRE_TRUST_DOMAIN": "juice.theprotocol.cloud"},
        "binds": [("/stack/juice-1/x509pop-certs", "/opt/spire-ca")]})

    def fake_launch(op, uid, name, argv, request, **kw):
        launched.append(argv)
        return {"id": kw.get("job_id"), "op": op, "name": name, "state": "running", "created": fr.now()}

    monkeypatch.setattr(runner, "launch", fake_launch)


def test_RED_the_oneshot_gets_the_hosts_compose_plugin_read_only(opsock, tmp_path, monkeypatch):
    cfg, rig_tmp = opsock
    runner = fr.Runner(cfg)
    (rig_tmp / "stack" / "juice-1").mkdir(parents=True, exist_ok=True)
    plugin = tmp_path / "docker-compose"; plugin.write_text("#!/bin/sh\n"); os.chmod(plugin, 0o755)
    monkeypatch.setattr(fr.Runner, "COMPOSE_PLUGIN_CANDIDATES", (str(tmp_path / "absent"), str(plugin)))
    launched = []
    _provision_stubs(runner, monkeypatch, launched)
    runner.handle({"op": "operator_provision", "frame": "juice", "spec": _spec()}, 0, fr.OPERATOR_OPS)
    assert launched and f"{plugin}:{fr.Runner.COMPOSE_PLUGIN_DEST}:ro" in launched[0], launched
    assert "/stack/juice-1/x509pop-certs:/opt/spire-ca:ro" in launched[0], "the frame's binds must survive the plugin's"


def test_RED_a_host_without_a_compose_plugin_is_refused_before_anything_is_launched(opsock, tmp_path, monkeypatch):
    cfg, rig_tmp = opsock
    runner = fr.Runner(cfg)
    (rig_tmp / "stack" / "juice-1").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fr.Runner, "COMPOSE_PLUGIN_CANDIDATES", (str(tmp_path / "absent-1"), str(tmp_path / "absent-2")))
    launched = []
    _provision_stubs(runner, monkeypatch, launched)
    with pytest.raises(fr.Refused) as e:
        runner.handle({"op": "operator_provision", "frame": "juice", "spec": _spec()}, 0, fr.OPERATOR_OPS)
    assert "compose" in str(e.value) and not launched, e.value


def test_RED_a_real_oneshot_runs_docker_compose_through_the_bound_plugin(opsock):
    if not os.path.exists("/var/run/docker.sock"):
        pytest.skip("LOUD SKIP: no docker socket, so the one-shot cannot be started here; the property is UNTESTED")
    image = _local_registry_image()
    if not image:
        pytest.skip("LOUD SKIP: no local agentvault2-registry-a:vNNNN image; the property is UNTESTED, not satisfied")
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    try:
        plugin = runner._host_compose_plugin()
    except fr.Refused as exc:
        pytest.skip(f"LOUD SKIP: this host has no compose plugin ({exc}); the property is UNTESTED, not satisfied")
    job_id = "9" * 16
    jd = pathlib.Path(runner.job_dir(job_id))
    runner._stage_operator_work(str(jd), {"phase": "stack"})
    argv = runner._operator_oneshot_argv(job_id, str(jd), image, {"env": {}, "binds": [(plugin, runner.COMPOSE_PLUGIN_DEST)]})
    cut = argv.index("--entrypoint")
    # DOCKER_CONFIG pointed away on purpose: host_work sets it to the operator's own config right before `compose up`
    probe = ("import json, os, subprocess\n"
             "os.environ['DOCKER_CONFIG'] = '/tmp/elsewhere'\n"
             "r = subprocess.run(['docker', 'compose', 'version'], capture_output=True, text=True)\n"
             "print(json.dumps({'uid': os.getuid(), 'rc': r.returncode, 'says': (r.stdout or r.stderr).strip()[:60]}))\n")
    r = subprocess.run(argv[:cut] + ["--entrypoint", "python3", image, "-c", probe], capture_output=True, text=True, timeout=120)
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["uid"] == 1000 and got["rc"] == 0 and "Compose" in got["says"], got


# ── §OPDIST (2026-09-16) — A FINISHED OPERATOR JOB KEEPS NO CREDENTIAL IN ITS SPEC ───────────────────────────────────────
# Measured by the footprint census on beacon: three finished operator jobs still held a docker_pull_token in spec.json.
# Those were inert, but a stack job's spec also carries the operator's LIVE secrets (the markers, the Redis passwords, the
# auditor's read-only password) and every resolved env value, and nothing reads any of them once the job's own post-steps
# (the edge check and the frame links) have. A secret written where nothing reads it is only downside.

def _staged_operator_job(runner, jid, *, phase="stack"):
    jd = pathlib.Path(runner.job_dir(jid))
    runner._stage_operator_work(str(jd), {
        "phase": phase, "frame": "juice", "operator_name": "tartu", "safe_name": "tartu", "operator_did": "did:x",
        "docker_pull_token": "dpt_" + "a" * 64,
        "operator_secrets": {"TEG_PROXY_TRUST_SECRET": "s" * 40, "AUDITOR_RO_PASSWORD": "ro-password-value-0123456789"},
        "env": {"FEDERATION_LICENSE_KEY": "lic-value-0123456789", "REGISTRY_NAME": "tartu"},
        "compose": {"domain": "tartu.op.theprotocol.cloud"}})
    runner.save_job({"id": jid, "op": "operator_provision", "name": "juice", "operator": "tartu", "state": "running",
                     "created": fr.now()})
    return jd / "spec.json"


def test_RED_a_finished_operator_job_leaves_no_credential_in_its_spec(opsock):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    spec_path = _staged_operator_job(runner, "5c0b000000000001")
    runner._finish("5c0b000000000001", 4)
    body = json.loads(spec_path.read_text())
    flat = json.dumps(body)
    for value in ("dpt_" + "a" * 64, "s" * 40, "ro-password-value-0123456789", "lic-value-0123456789"):
        assert value not in flat, "a credential outlived the job that consumed it"
    # the record keeps its shape: what was passed stays readable by NAME
    assert set(body["operator_secrets"]) == {"TEG_PROXY_TRUST_SECRET", "AUDITOR_RO_PASSWORD"} and "docker_pull_token" in body
    assert body["safe_name"] == "tartu" and body["compose"]["domain"] == "tartu.op.theprotocol.cloud", body
    assert oct(os.stat(spec_path).st_mode & 0o777) == "0o640"


def test_RED_the_scrub_runs_only_after_the_links_have_read_the_spec(opsock, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    jid = "5c0b000000000002"
    spec_path = _staged_operator_job(runner, jid)
    (pathlib.Path(runner.job_dir(jid)) / "result.json").write_text("{}")
    seen = {}
    monkeypatch.setattr(runner, "_apply_operator_edge", lambda rec: None)
    monkeypatch.setattr(runner, "_apply_operator_redis_acl", lambda rec: None)

    def fake_register(rec):
        seen["pw"] = json.loads(spec_path.read_text())["operator_secrets"]["AUDITOR_RO_PASSWORD"]

    monkeypatch.setattr(runner, "_register_operator_with_frame", fake_register)
    runner._finish(jid, 0)
    assert seen.get("pw") == "ro-password-value-0123456789", "the links must read the real value before the scrub"
    assert "ro-password-value-0123456789" not in spec_path.read_text()


# ── §OPDIST V0386 (agentvault2-b5, 2026-09-16) — the bundle spec now carries the SPIRE target itself ─────────────────────
# spire_container, spire_trust_domain, spire_server_address, spire_server_port on the bundle and full phases. The registry
# resolves them, the one-shot refuses a bundle without them, and this runner holds every one of them to the FRAME's own
# values: three places, one rule, because the place that was wrong was the one nobody checked.

def _v0386_stubs(runner, monkeypatch, launched, frame_env):
    monkeypatch.setattr(runner, "host_gates", lambda: [])
    monkeypatch.setattr(runner, "active", lambda: None)
    monkeypatch.setattr(runner, "_operator_image", lambda name: "sha256:" + "e" * 64)
    monkeypatch.setattr(runner, "_frame_identity_network", lambda f: "juice_network_identity")
    monkeypatch.setattr(runner, "_host_compose_plugin", lambda: "/usr/libexec/docker/cli-plugins/docker-compose")
    monkeypatch.setattr(runner, "_frame_provisioner_inputs", lambda f: {"env": dict(frame_env), "binds": []})
    monkeypatch.setattr(runner, "launch", lambda *a, **k: launched.append(a) or {"id": k.get("job_id"), "state": "running"})


FRAME_SPIRE = {"SPIRE_CONTAINER": "juice-spire-server", "SPIRE_TRUST_DOMAIN": "juice.theprotocol.cloud",
               "SPIRE_SERVER_ADDRESS": "juice-spire.theprotocol.cloud", "SPIRE_SERVER_PORT": "8515"}


@pytest.mark.parametrize("field,value", [("spire_server_address", "eu-spire.theprotocol.cloud"), ("spire_server_port", "8444")])
def test_RED_a_bundle_spec_naming_another_spire_server_is_refused(opsock, monkeypatch, field, value):
    cfg, tmp_path = opsock
    runner = fr.Runner(cfg)
    (tmp_path / "stack" / "juice-1").mkdir(parents=True, exist_ok=True)
    launched = []
    _v0386_stubs(runner, monkeypatch, launched, FRAME_SPIRE)
    spec = {**_spec(), "phase": "bundle", "spire_container": "juice-spire-server",
            "spire_trust_domain": "juice.theprotocol.cloud", "spire_server_address": "juice-spire.theprotocol.cloud",
            "spire_server_port": 8515}
    spec.pop("operator_secrets", None)
    spec[field] = value
    with pytest.raises(fr.Refused) as e:
        runner.handle({"op": "operator_provision", "frame": "juice", "spec": spec}, 0, fr.OPERATOR_OPS)
    assert field in str(e.value) and not launched, e.value


def test_RED_a_spec_value_the_frame_does_not_carry_cannot_be_verified_and_is_refused(opsock, monkeypatch):
    cfg, tmp_path = opsock
    runner = fr.Runner(cfg)
    (tmp_path / "stack" / "juice-1").mkdir(parents=True, exist_ok=True)
    launched = []
    _v0386_stubs(runner, monkeypatch, launched, {k: v for k, v in FRAME_SPIRE.items() if k != "SPIRE_SERVER_ADDRESS"})
    spec = {**_spec(), "phase": "bundle", "spire_server_address": "juice-spire.theprotocol.cloud"}
    spec.pop("operator_secrets", None)
    with pytest.raises(fr.Refused) as e:
        runner.handle({"op": "operator_provision", "frame": "juice", "spec": spec}, 0, fr.OPERATOR_OPS)
    assert "spire_server_address" in str(e.value) and not launched, e.value


def test_a_v0386_bundle_spec_matching_the_frame_is_launched_port_as_an_integer_included(opsock, monkeypatch):
    """The control: the four keys are not unknown to this runner, and 8515 the integer equals "8515" the env value."""
    cfg, tmp_path = opsock
    runner = fr.Runner(cfg)
    (tmp_path / "stack" / "juice-1").mkdir(parents=True, exist_ok=True)
    launched = []
    _v0386_stubs(runner, monkeypatch, launched, FRAME_SPIRE)
    spec = {**_spec(), "phase": "bundle", "spire_container": "juice-spire-server",
            "spire_trust_domain": "juice.theprotocol.cloud", "spire_server_address": "juice-spire.theprotocol.cloud",
            "spire_server_port": 8515}
    spec.pop("operator_secrets", None)
    out = runner.handle({"op": "operator_provision", "frame": "juice", "spec": spec}, 0, fr.OPERATOR_OPS)
    assert out.get("started") is True and len(launched) == 1, out


# ── §OPDIST (2026-09-16) — an operator job's REASON, for the page that said "not run" about a job that ran ─────────────
# Frame Management drew the frame-standup step list for an operator_provision job (no step events), so every step read
# "not run" while the one-shot had extracted, written env and markers, chowned the ACL and failed at compose up; the
# rail carried no reason at all. The runner now writes `reason` on the job record: string or null, null unless the job
# failed/cancelled/lost, one line, at most 600 characters, credentials redacted BEFORE it is stored.

PLANT_TOKEN = "dpt_" + "0123456789abcdef" * 4
PLANT_DSN = "postgresql+asyncpg://registry:0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a6978@pgbouncer:6432/agentvault_registry"


def _finished_operator_job(runner, jid, code, *, stdout=None, notes=None):
    jd = pathlib.Path(runner.job_dir(jid))
    jd.mkdir(mode=0o700, parents=True, exist_ok=True)
    (jd / "spec.json").write_text(json.dumps({"phase": "stack", "docker_pull_token": PLANT_TOKEN}))
    if stdout is not None:
        (jd / "stdout.log").write_text(stdout)
    if notes is not None:
        (jd / "result.json").write_text(json.dumps({"phase": "stack", "notes": notes}))
    runner.save_job({"id": jid, "op": "operator_provision", "name": "juice", "operator": "tartu", "state": "running",
                     "created": fr.now()})
    runner._finish(jid, code)
    return runner.job(jid)


def test_RED_a_failed_operator_job_carries_a_redacted_one_line_reason(opsock, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    stdout = ("[provision:tartu] could not chown the ACL\nTraceback (most recent call last):\n  File x\n"
              f"compose up failed (exit 1): token {PLANT_TOKEN} dsn {PLANT_DSN} password=hunter2hunter2\n")
    rec = _finished_operator_job(runner, "7ea5000000000001", 4, stdout=stdout,
                                 notes=["phase: stack", "parent peer row: FAILED (psql exit 1: relation does not exist)"])
    reason = rec.get("reason")
    assert isinstance(reason, str) and reason, rec
    assert "compose up failed (exit 1)" in reason and "parent peer row: FAILED" in reason, reason
    for secret in (PLANT_TOKEN, "0f1e2d3c4b5a6978", "hunter2hunter2"):
        assert secret not in reason, f"a credential reached the job record: {reason}"
    assert "\n" not in reason and len(reason) <= 600, reason


def test_RED_a_failed_operator_job_with_no_output_says_so(opsock):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    rec = _finished_operator_job(runner, "7ea5000000000002", 125)
    assert rec.get("reason") == "no output: the one-shot exited 125 before writing anything", rec


def test_a_succeeded_operator_job_has_no_reason(opsock, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    monkeypatch.setattr(runner, "_apply_operator_edge", lambda rec: None)
    monkeypatch.setattr(runner, "_apply_operator_redis_acl", lambda rec: None)
    monkeypatch.setattr(runner, "_register_operator_with_frame", lambda rec: None)
    rec = _finished_operator_job(runner, "7ea5000000000003", 0, stdout="ok\n", notes=["phase: stack"])
    assert rec.get("state") == "succeeded" and rec.get("reason") is None, rec


def test_RED_operator_status_hands_the_reason_to_the_frame(opsock):
    cfg, _ = opsock
    runner = fr.Runner(cfg)
    _finished_operator_job(runner, "7ea5000000000004", 3, stdout="the spec is missing ['compose'] (phase stack)\n")
    out = runner.handle({"op": "operator_status", "frame": "juice", "job_id": "7ea5000000000004"}, 0, fr.OPERATOR_OPS)
    assert (out.get("job") or {}).get("reason") == "the spec is missing ['compose'] (phase stack)", out


def test_RED_a_job_the_edge_step_fails_after_the_oneshot_succeeded_still_carries_a_reason(opsock, monkeypatch):
    cfg, _ = opsock
    runner = fr.Runner(cfg)

    def failing_edge(rec):
        rec["state"] = "failed"
        rec.setdefault("notes", []).append("edge: REFUSED the vhost names another frame's certificate")

    monkeypatch.setattr(runner, "_apply_operator_edge", failing_edge)
    monkeypatch.setattr(runner, "_register_operator_with_frame", lambda rec: None)
    rec = _finished_operator_job(runner, "7ea5000000000005", 0, stdout="stack phase finished\n", notes=["phase: stack"])
    assert rec.get("state") == "failed" and "edge: REFUSED" in (rec.get("reason") or ""), rec


# §OPDIST 2026-09-16 20:04Z, beacon: the teardown of jelgava was refused at "59 GB free under /opt/theprotocol/stack is
# under 60 GB". The floors exist to stop a job from taking what the host does not have; a teardown takes nothing and gives
# memory and disk back, so a floor that refuses it shuts the one job that could lift the host above that floor. The frame
# teardown never took the host gates at all; the operator teardown takes the load gate only.

def test_RED_an_operator_teardown_is_not_refused_by_the_floors_it_raises(tworld):
    runner = tworld["runner"]
    tworld["provisioned"]()
    runner.cfg.min_free_gb = 10 ** 9
    runner.cfg.min_mem_gib = 10 ** 9
    floors = runner.host_gates()
    assert any("GB free" in p for p in floors) and any("MemAvailable" in p for p in floors), \
        "the floors must bite on this host, or the teardown below proves nothing"
    runner.op_operator_teardown(_teardown_req(), 0)
    assert [j["op"] for j in tworld["launched"]] == ["operator_teardown"]


def test_the_load_gate_still_refuses_an_operator_teardown_and_the_floors_still_bind_a_provision(tworld, monkeypatch):
    runner = tworld["runner"]
    tworld["provisioned"]()
    runner.cfg.max_load = 0
    with pytest.raises(fr.Refused, match=r"load1=.* is at or above 0"):
        runner.op_operator_teardown(_teardown_req(), 0)
    assert tworld["launched"] == []
    runner.cfg.max_load = 10 ** 6
    runner.cfg.min_free_gb = 10 ** 9
    # the spec checks come first and are not what this test is about: a provision that passes them meets the floors
    monkeypatch.setattr(runner, "_operator_frame", lambda req, uid=None: {"name": "lantern"})
    monkeypatch.setattr(runner, "_operator_spec", lambda req: {"safe_name": "tartu"})
    with pytest.raises(fr.Refused, match=r"GB free .* is under"):
        runner.op_operator_provision({"frame": "lantern", "spec": {"safe_name": "tartu"}}, 0)
    assert tworld["launched"] == []


# ── §PUSH (2026-10-06): an operator's public push vhost, checked against spec.edge and written beside the console's ──
_PUSH_OK = """server {
    listen 443 ssl http2;
    server_name tartu-push.op.example;
    ssl_certificate /etc/letsencrypt/live/op.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/op.example/privkey.pem;
    location = /v1/health {
        limit_except GET { deny all; }
        proxy_pass http://127.0.0.1:31599;
    }
    location ~ "^/[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*/(json|sse|raw|ws|auth)$" {
        limit_except GET { deny all; }
        proxy_pass http://127.0.0.1:31599;
    }
    location / {
        return 403;
    }
}
"""
_CONSOLE = ("server {\n server_name tartu.op.example;\n"
            " ssl_certificate /etc/letsencrypt/live/op.example/fullchain.pem;\n proxy_pass http://127.0.0.1:31500;\n}")


def _push_edge(runner, **over):
    edge = {"domain": "tartu.op.example", "reg_port": 31500, "fed_port": 31543, "ssl_cert_name": "op.example",
            "ws_events_host": "localhost:8511", "push_host": "tartu-push.op.example", "push_port": 31599}
    edge.update(over)
    (pathlib.Path(runner.job_dir("edgejob000000001")) / "spec.json").write_text(json.dumps({"edge": edge}))


def test_the_push_vhost_is_written_beside_the_console_and_tested_before_the_reload(edge):
    runner, sites, _, _, calls = edge
    _push_edge(runner)
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": _CONSOLE, "push_vhost": _PUSH_OK}}
    runner._apply_operator_edge(rec)
    assert rec["state"] == "succeeded", rec
    assert (sites / "cloud-op-tartu-push").read_text() == _PUSH_OK and (sites / "cloud-op-tartu").exists()
    assert calls.index(["nginx", "-t"]) < calls.index(["nginx", "-s", "reload"])
    assert any("subscribe only" in n for n in rec["notes"]), rec["notes"]


@pytest.mark.parametrize("over,vhost,why", [
    ({"push_host": "evil.example"}, _PUSH_OK, "declares push host"),
    ({"push_host": "push.tartu.op.example"}, _PUSH_OK, "declares push host"),
    ({"push_port": 9999}, _PUSH_OK, "declares push port"),
    ({}, _PUSH_OK.replace("server_name tartu-push.op.example", "server_name tartu.op.example"), "answers to"),
    ({}, _PUSH_OK.replace("127.0.0.1:31599;\n    }\n    location / {", "127.0.0.1:31500;\n    }\n    location / {"),
     "proxies to"),
    # the old method-only shape: GET publish/delete forms would reach the relay through the catch-all
    ({}, _PUSH_OK.replace("location / {\n        return 403;\n    }",
                          "location / {\n        limit_except GET { deny all; }\n        proxy_pass http://127.0.0.1:31599;\n    }"),
     "reach the relay"),
    ({}, _PUSH_OK.replace("location / {\n        return 403;\n    }", "location / {\n        return 404;\n    }"),
     "does not refuse"),
])
def test_RED_a_push_vhost_beyond_its_declaration_or_not_subscribe_only_is_refused_and_reverted(edge, over, vhost, why):
    runner, sites, _, sni, calls = edge
    _push_edge(runner, **over)
    before = sni.read_text()
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": _CONSOLE, "push_vhost": vhost, "sni_entry": "tartu.op.example 127.0.0.1:31543;"}}
    runner._apply_operator_edge(rec)
    assert rec["state"] == "failed", rec
    assert any(why in n for n in rec["notes"]), rec["notes"]
    assert not (sites / "cloud-op-tartu-push").exists() and not (sites / "cloud-op-tartu").exists()
    assert sni.read_text() == before and ["nginx", "-s", "reload"] not in calls


def test_a_result_without_a_push_vhost_writes_the_console_alone(edge):
    runner, sites, _, _, _ = edge
    _push_edge(runner)
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": _CONSOLE}}
    runner._apply_operator_edge(rec)
    assert rec["state"] == "succeeded" and (sites / "cloud-op-tartu").exists()
    assert not (sites / "cloud-op-tartu-push").exists()


def test_the_edge_removal_takes_the_push_vhost_with_the_console(edge):
    runner, sites, backups, _, calls = edge
    _push_edge(runner)
    rec = {"id": "edgejob000000001", "op": "operator_provision", "operator": "tartu", "state": "succeeded",
           "result": {"host_vhost": _CONSOLE, "push_vhost": _PUSH_OK}}
    runner._apply_operator_edge(rec)
    out = runner._remove_operator_edge("tartu", None)
    assert out["nginx_removed"] is True, out
    assert not (sites / "cloud-op-tartu").exists() and not (sites / "cloud-op-tartu-push").exists()
    assert any(p.name.startswith("cloud-op-tartu-push.") and p.name.endswith(".torn-down") for p in backups.iterdir())

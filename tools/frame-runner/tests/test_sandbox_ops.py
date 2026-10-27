"""§TESTBED (2026-09-19): the frame runner's sandbox ops, unadopt, and the calling frame named by its container.

His words: "the sandbox provisioning should be also in the frontend mcp-tester view ... all provisioned thru the proper
lanes". A kit frame's console asks the runner (on the operator socket it already mounts) to stand ITS sandbox up; the
runner launches the export's frame-sandbox.py as a job, lets that job's children (the sandboxes' own operator provisions)
past the one-job slot, and acts for the calling frame only. A FAKE engine and fake docker answers; nothing here touches
the host's stacks, docker or /etc.
"""
import importlib.util
import json
import os
import pathlib
import sys
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_sbx", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

FAKE_ENGINE = r'''
import json, os, sys, time
argv = sys.argv[1:]
def val(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": argv}) + "\n")
progress = val("--progress-file")
def emit(step, event, **kw):
    with open(progress, "a") as f:
        f.write(json.dumps({"step": step, "event": event, **kw}) + "\n")
emit("plan", "start"); emit("plan", "end", sentence="1 sandbox(es)")
if val("--for") == "slowframe":
    time.sleep(30)
emit("ready", "live", sentence="ready")
'''


@pytest.fixture
def world(tmp_path, monkeypatch):
    stack = tmp_path / "stack"
    stack.mkdir()
    engine = tmp_path / "frame-sandbox.py"
    engine.write_text(FAKE_ENGINE)
    plist = tmp_path / "protected.list"
    plist.write_text("eu\n")
    cfg = fr.Config(conf={"sandboxes": True, "allowed_uids": [os.getuid(), 1000], "min_free_gb": 0, "max_load": 10 ** 6,
                          "min_mem_gib": 0},
                    socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "standup_driver.py"), python=sys.executable, stack_root=str(stack),
                    protected_list=str(plist), frame_sandbox=str(engine))
    runner = fr.Runner(cfg)
    os.makedirs(os.path.join(cfg.state, "frames"), exist_ok=True)
    os.makedirs(os.path.join(cfg.state, "jobs"), exist_ok=True)

    def frame(name, sandbox_of=None, adopted=True, secrets=None):
        sd = stack / f"{name}-100"
        sd.mkdir()
        fu = {"name": name, "public_name": f"{name}.example.org", "console": f"https://{name}.example.org",
              "secrets_dir": str(secrets or (stack / f"{name}-secrets")), "edge_health": 200}
        if sandbox_of:
            fu["sandbox_of"] = sandbox_of
        (sd / "frame-up.json").write_text(json.dumps(fu))
        runner.save_frame({"name": name, "adopted": adopted, "stack_dir": str(sd), "state": "live (adopted)"})
        return sd
    monkeypatch.setattr(fr, "mem_available_gib", lambda: 64.0)
    yield {"cfg": cfg, "runner": runner, "frame": frame, "tmp": tmp_path, "stack": stack}
    for rec in runner.running_jobs():
        try:
            os.killpg(rec["pid"], 9)
        except (ProcessLookupError, PermissionError):
            pass


def _wait_ended(runner, job_id, s=20):
    deadline = time.time() + s
    while time.time() < deadline:
        rec = runner.job(job_id)
        if rec.get("state") not in ("running", "cancelling"):
            return rec
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} still running")


def test_a_runner_without_the_policy_refuses_the_sandbox_ops_in_its_own_words(world):
    runner = world["runner"]
    runner.cfg.sandboxes = False
    with pytest.raises(fr.Refused, match="does not offer sandboxes"):
        runner.handle({"op": "sandbox_status", "frame": "larch"}, os.getuid(), allowed=fr.OPERATOR_OPS)


def test_status_lists_this_frames_sandboxes_and_the_topologies(world):
    world["frame"]("larch")
    world["frame"]("larchsbx", sandbox_of="larch")
    world["frame"]("other")
    world["frame"]("othersbx", sandbox_of="other")
    st = world["runner"].op_sandbox_status({"frame": "larch"}, os.getuid())
    assert st["supported"] is True and [s["name"] for s in st["sandboxes"]] == ["larchsbx"]
    assert st["sandboxes"][0]["tester"] == "https://larchsbx.example.org/#/admin/mcp-tester"
    assert {(t["frames"], t["operators"]) for t in st["topologies"]} == {(1, False), (1, True), (2, False), (2, True)}
    assert st["job"] is None


def test_a_sandbox_does_not_provision_sandboxes(world):
    world["frame"]("larch")
    world["frame"]("larchsbx", sandbox_of="larch")
    with pytest.raises(fr.Refused, match="itself the sandbox of larch"):
        world["runner"].op_sandbox_status({"frame": "larchsbx"}, os.getuid())


def test_up_launches_the_engine_with_the_topology_and_names_its_children(world):
    world["frame"]("larch")
    runner = world["runner"]
    out = runner.op_sandbox_up({"frame": "larch", "frames": 2, "operators": True}, os.getuid())
    job = runner.job(out["job"]["id"])
    assert job["op"] == "sandbox_up" and job["children"] == ["larchsbx", "larchsbxb"]
    rec = _wait_ended(runner, job["id"])
    assert rec["state"] == "succeeded"
    call = json.loads((world["tmp"] / "engine_calls.jsonl").read_text().splitlines()[-1])["argv"]
    assert call[:6] == ["up", "--for", "larch", "--frames", "2", "--stack-root"] and "--operators" in call
    ev = runner.op_sandbox_events({"frame": "larch", "job_id": job["id"]}, os.getuid())
    assert [e["event"] for e in ev["events"]] == ["start", "end", "live"] and ev["next"] == 3


def test_the_shape_is_closed(world):
    world["frame"]("larch")
    for bad in ({"frames": 3}, {"frames": "1"}, {"operators": "yes"}):
        with pytest.raises(fr.Refused, match="frames is 1 or 2"):
            world["runner"].op_sandbox_up({"frame": "larch", **bad}, os.getuid())


def test_the_memory_estimate_is_on_top_of_the_floor(world, monkeypatch):
    world["frame"]("larch")
    world["runner"].cfg.min_mem_gib = 15
    monkeypatch.setattr(fr, "mem_available_gib", lambda: 20.0)
    with pytest.raises(fr.Refused, match="would fall under this host's floor"):
        world["runner"].op_sandbox_up({"frame": "larch", "frames": 2, "operators": True}, os.getuid())


def test_one_job_at_a_time_with_the_sandbox_jobs_children_let_through(world):
    world["frame"]("slowframe")
    runner = world["runner"]
    out = runner.op_sandbox_up({"frame": "slowframe", "frames": 1, "operators": True}, os.getuid())
    try:
        with pytest.raises(fr.Refused, match="one job at a time"):
            runner.op_sandbox_up({"frame": "slowframe", "frames": 1}, os.getuid())
        runner._refuse_if_busy_for("slowframesbx")          # the child: its operator provision passes
        with pytest.raises(fr.Refused, match="one job at a time"):
            runner._refuse_if_busy_for("slowframesbxb")     # not a child of a one-frame job
        with pytest.raises(fr.Refused, match="one job at a time"):
            runner._refuse_if_busy_for("unrelated")
    finally:
        os.killpg(runner.job(out["job"]["id"])["pid"], 9)


def test_events_of_another_frames_job_are_refused(world):
    world["frame"]("larch")
    world["frame"]("other")
    runner = world["runner"]
    out = runner.op_sandbox_up({"frame": "other", "frames": 1}, os.getuid())
    _wait_ended(runner, out["job"]["id"])
    with pytest.raises(fr.Refused, match="not a sandbox job of larch"):
        runner.op_sandbox_events({"frame": "larch", "job_id": out["job"]["id"]}, os.getuid())


def test_reveal_hands_the_sandboxs_admin_login_and_refuses_one_that_is_not_there(world):
    world["frame"]("larch")
    sec = world["stack"] / "larchsbx-secrets"
    sec.mkdir()
    (sec / ".larchsbx_frame_admin.secret.json").write_text(json.dumps({"admin_email": "admin@sbx", "admin_password": "p" * 24}))
    world["frame"]("larchsbx", sandbox_of="larch", secrets=sec)
    got = world["runner"].op_sandbox_reveal({"frame": "larch", "which": "a"}, os.getuid())
    assert got == {"sandbox": "larchsbx", "console": "https://larchsbx.example.org", "email": "admin@sbx", "password": "p" * 24}
    with pytest.raises(fr.Refused, match="no sandbox b"):
        world["runner"].op_sandbox_reveal({"frame": "larch", "which": "b"}, os.getuid())


def test_the_calling_frame_is_its_container_not_its_claim(world, monkeypatch):
    world["frame"]("larch")
    world["frame"]("other")
    runner = world["runner"]
    monkeypatch.setattr(fr, "container_of_pid", lambda pid: "a" * 64)

    class Done:
        returncode, stdout, stderr = 0, "other-100\n", ""
    monkeypatch.setattr(fr.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(fr.Refused, match="not the calling frame"):
        runner.op_sandbox_status({"frame": "larch", "_peer_pid": 4242}, 1000)
    assert runner.op_sandbox_status({"frame": "other", "_peer_pid": 4242}, 1000)["frame"] == "other"
    assert runner.op_sandbox_status({"frame": "larch", "_peer_pid": 4242}, 0)["frame"] == "larch"   # root names any
    monkeypatch.setattr(fr, "container_of_pid", lambda pid: None)
    with pytest.raises(fr.Refused, match="runs in no container"):
        runner.op_sandbox_status({"frame": "other", "_peer_pid": 4242}, 1000)


def test_a_caller_cannot_forge_its_own_pid(world):
    world["frame"]("larch")
    seen = {}
    world["runner"].op_sandbox_status = lambda req, uid: seen.update(req) or {}
    world["runner"].handle({"op": "sandbox_status", "frame": "larch", "_peer_pid": 1}, 1000,
                           allowed=fr.OPERATOR_OPS + fr.SANDBOX_OPS, pid=777)
    assert seen["_peer_pid"] == 777          # the kernel's pid, not the one the request carried
    seen.clear()
    world["runner"].handle({"op": "sandbox_status", "frame": "larch", "_peer_pid": 1}, 1000,
                           allowed=fr.OPERATOR_OPS + fr.SANDBOX_OPS)
    assert "_peer_pid" not in seen           # no kernel pid (a direct call): the forged one is dropped, not kept


def test_container_of_pid_reads_the_cgroup(tmp_path, monkeypatch):
    cid = "b" * 64
    real_open = open

    def fake_open(path, *a, **k):
        if str(path) == "/proc/4242/cgroup":
            return real_open(tmp_path / "cg", *a, **k)
        return real_open(path, *a, **k)
    (tmp_path / "cg").write_text(f"0::/system.slice/docker-{cid}.scope\n")
    monkeypatch.setattr("builtins.open", fake_open)
    assert fr.container_of_pid(4242) == cid
    (tmp_path / "cg").write_text("0::/user.slice/user-0.slice/session-1.scope\n")
    assert fr.container_of_pid(4242) is None
    assert fr.frame_of_project("larch-1789") == "larch" and fr.frame_of_project("larch-edge") == "larch"
    assert fr.frame_of_project("cloud-op-x") is None


def test_unadopt_forgets_an_adopted_frame_once_it_is_gone(world, monkeypatch):
    runner = world["runner"]
    world["frame"]("larchsbx", sandbox_of="larch")
    with pytest.raises(fr.Refused, match="root only"):
        runner.op_unadopt({"name": "larchsbx"}, 1000)

    class Exists:
        returncode, stdout, stderr = 0, "running\n", ""

    class Gone:
        returncode, stdout, stderr = 1, "", "Error: No such object"
    monkeypatch.setattr(fr.subprocess, "run", lambda *a, **k: Exists())
    with pytest.raises(fr.Refused, match="still exists"):
        runner.op_unadopt({"name": "larchsbx"}, 0)
    monkeypatch.setattr(fr.subprocess, "run", lambda *a, **k: Gone())
    assert runner.op_unadopt({"name": "larchsbx"}, 0)["forgotten"] is True
    assert runner.frame("larchsbx") is None
    assert runner.op_unadopt({"name": "larchsbx"}, 0)["forgotten"] is False


def test_unadopt_refuses_a_frame_the_runner_built(world, monkeypatch):
    runner = world["runner"]
    world["frame"]("built", adopted=False)
    with pytest.raises(fr.Refused, match="its lifecycle is teardown"):
        runner.op_unadopt({"name": "built"}, 0)

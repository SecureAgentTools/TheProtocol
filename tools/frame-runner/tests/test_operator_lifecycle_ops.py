"""§F6 WP6.2 (2026-09-26): the lifecycle of a frame's cloud operators, and the federation delete a revoke needs.

The registry restarted an operator's services and read its logs through a docker:cli sidecar that held the host Docker
socket. Here the runner does the same two compose verbs, and every rule has a planted bad argument that must be refused
BEFORE compose runs (the recorder sees no compose call), a good request whose exact argv is pinned, and a binding that
reads the OPERATOR's own container rather than anything the request says. Nothing here touches docker or the host.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_oplifecycle", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

TD = "sbx.example.org"
PEER = "peer.example.org"
OP = "sbxop"
SECRET_ENV = "OPERATOR_DB_PASSWORD=not-for-any-answer"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    stack = tmp_path / "stack"
    cfg = fr.Config(conf={"images": {"registry": ["agentvault2-registry-a:v0461"]}, "allowed_uids": [0, 1000],
                          "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0},
                    socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "driver.py"), teardown=str(tmp_path / "td.sh"), python=sys.executable,
                    stack_root=str(stack), protected_list=str(tmp_path / "protected.list"),
                    template=str(tmp_path / "template.yml.tmpl"))
    os.makedirs(cfg.state, exist_ok=True)
    runner = fr.Runner(cfg)
    wd = stack / f"cloud-op-{OP}"
    wd.mkdir(parents=True)
    (wd / "docker-compose.operator.yml").write_text("services: {}\n")
    (wd / ".env.operator").write_text("X=1\n")
    world = {"containers": {f"cloud-op-{OP}": ["opreg1"]}, "compose": [], "ps": [], "spire": [],
             "compose_rc": 0, "compose_out": b"Container cloud-op-sbxop-registry  Restarting\n", "timeout": False,
             "inspect": {"opreg1": {"Config": {
                 "Labels": {"com.docker.compose.project": f"cloud-op-{OP}",
                            "com.docker.compose.project.working_dir": str(wd),
                            "com.docker.compose.project.config_files": str(wd / "docker-compose.operator.yml"),
                            "com.docker.compose.project.environment_file": str(wd / ".env.operator")},
                 "Env": [f"SPIRE_TRUST_DOMAIN={TD}", f"REGISTRY_SAFE_NAME={OP}", SECRET_ENV]}}}}

    def fake_run(cmd, **kw):
        if cmd[:2] == ["docker", "ps"]:
            world["ps"].append(cmd)
            project = next(a[len("label=com.docker.compose.project="):] for a in cmd if a.startswith("label=com.docker.compose.project="))
            return subprocess.CompletedProcess(cmd, 0, "".join(f"{i}\n" for i in world["containers"].get(project, [])), "")
        if cmd[:2] == ["docker", "compose"]:
            world["compose"].append((cmd, kw))
            if world["timeout"]:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"), output=b"partial\n", stderr=b"")
            return subprocess.CompletedProcess(cmd, world["compose_rc"], world["compose_out"], b"")
        raise AssertionError(f"unexpected command: {cmd}")

    def spire_exec(spire, argv, stdin=None, timeout=30):
        world["spire"].append(list(argv))
        return {"rc": 0, "stdout": "ok\n", "stderr": ""}

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_docker_inspect", lambda cid: json.loads(json.dumps(world["inspect"].get(cid))))
    monkeypatch.setattr(runner, "_spire_exec", spire_exec)
    monkeypatch.setattr(runner, "_frame_spire", lambda project: ("sbx-spire-server", TD))
    # the caller: pid 4242 runs in container "c" of compose project sbx-1788464843 (frame "sbx")
    monkeypatch.setattr(fr, "container_of_pid", lambda pid: "c" if pid == 4242 else None)
    monkeypatch.setattr(runner, "_project_of_container", lambda cid: "sbx-1788464843" if cid == "c" else "")
    return runner, world, wd, cfg


def call(runner, op, uid=1000, pid=4242, allowed=None, **fields):
    return runner.handle({"op": op, **fields}, uid, fr.OPERATOR_OPS if allowed is None else allowed, pid=pid)


def refused(runner, world, op, match, **kw):
    before = len(world["compose"])
    with pytest.raises(fr.Refused) as exc:
        call(runner, op, **kw)
    assert match in str(exc.value), str(exc.value)
    assert len(world["compose"]) == before, f"{op} ran compose before refusing: {world['compose'][before:]}"
    return str(exc.value)


# ── the federation delete a revoke needs ─────────────────────────────────────────────────────────────────────────

def test_federation_delete_names_a_peer_and_never_our_own(rig):
    runner, world, _, _ = rig
    out = call(runner, "spire_federation_delete", trust_domain=f"spiffe://{PEER}/")
    assert world["spire"][-1] == ["federation", "delete", "-id", f"spiffe://{PEER}"]
    assert out["frame"] == "sbx" and out["rc"] == 0
    for bad, why in ((TD, "this frame's own"), ("localhost", "not a DNS name"), ("peer.example.org;rm", "not a DNS name"),
                     ("", "not a DNS name")):
        n = len(world["spire"])
        with pytest.raises(fr.Refused) as exc:
            call(runner, "spire_federation_delete", trust_domain=bad)
        assert why in str(exc.value) and len(world["spire"]) == n
    with pytest.raises(fr.Refused):
        call(runner, "spire_federation_delete", trust_domain=PEER, frame="asia")


# ── where the ops are served ─────────────────────────────────────────────────────────────────────────────────────

def test_the_lifecycle_ops_live_on_the_operator_socket_only(rig):
    runner, world, _, _ = rig
    for op in fr.OPERATOR_LIFECYCLE_OPS + ("spire_federation_delete",):
        assert op in fr.OPERATOR_OPS and op not in fr.OPS
    refused(runner, world, "operator_restart", "not served on this socket", allowed=fr.OPS, operator=OP)


# ── restart: one exact compose argv on the operator's own stack ──────────────────────────────────────────────────

def test_restart_runs_one_exact_compose_argv_on_the_operators_own_stack(rig):
    runner, world, wd, _ = rig
    out = call(runner, "operator_restart", operator=OP, service="registry")
    cmd, kw = world["compose"][-1]
    assert cmd == ["docker", "compose", "-p", f"cloud-op-{OP}", "-f", str(wd / "docker-compose.operator.yml"),
                   "--env-file", str(wd / ".env.operator"), "restart", "registry"]
    assert kw["cwd"] == str(wd) and not kw.get("shell") and kw["stdin"] is subprocess.DEVNULL
    assert out["restarted"] is True and out["rc"] == 0 and out["operator"] == OP and out["frame"] == "sbx"
    call(runner, "operator_restart", operator=OP, service="all")
    assert world["compose"][-1][0][-1] == "restart"            # "all" is compose's own "every service"
    refused(runner, world, "operator_restart", "service:", operator=OP)   # naming none restarts none


def test_the_overrides_up_read_are_the_files_restart_reads(rig):
    runner, world, wd, _ = rig
    (wd / "docker-compose.operator.dbtls.yml").write_text("services: {}\n")
    labels = world["inspect"]["opreg1"]["Config"]["Labels"]
    labels["com.docker.compose.project.config_files"] = ",".join(
        [str(wd / "docker-compose.operator.yml"), str(wd / "docker-compose.operator.dbtls.yml")])
    call(runner, "operator_restart", operator=OP, service="teg-layer")
    cmd = world["compose"][-1][0]
    assert cmd[4:9] == ["-f", str(wd / "docker-compose.operator.yml"), "-f", str(wd / "docker-compose.operator.dbtls.yml"),
                        "--env-file"]


def test_a_service_outside_the_closed_set_is_refused_before_compose(rig):
    runner, world, _, _ = rig
    for bad in ("registry; rm -rf /", "../registry", "postgres", "--help", "REGISTRY", ""):
        refused(runner, world, "operator_restart", "service:", operator=OP, service=bad)
        refused(runner, world, "operator_logs", "service:", operator=OP, service=bad)


def test_an_operator_name_is_a_plain_name(rig):
    runner, world, _, _ = rig
    for bad in ("../etc", "Op", "a", "x" * 50, None, "sbxop/../x", "-p"):
        refused(runner, world, "operator_restart", "operator:", operator=bad)
    assert world["ps"] == [], "a refused name must not even be looked up"


# ── the binding: the operator's own container says whose it is ─────────────────────────────────────────────────

def test_an_operator_of_another_frame_is_refused(rig):
    runner, world, _, _ = rig
    world["inspect"]["opreg1"]["Config"]["Env"][0] = "SPIRE_TRUST_DOMAIN=asia.example.org"
    why = refused(runner, world, "operator_restart", "not an operator of the calling frame", operator=OP)
    assert "asia.example.org" not in why, "a refusal must not echo the other frame's env"
    refused(runner, world, "operator_logs", "not an operator of the calling frame", operator=OP)
    world["inspect"]["opreg1"]["Config"]["Env"] = [f"REGISTRY_SAFE_NAME={OP}"]
    refused(runner, world, "operator_restart", "not an operator of the calling frame", operator=OP)


def test_a_frame_claim_is_not_a_binding(rig):
    runner, world, _, _ = rig
    with pytest.raises(fr.Refused) as exc:
        call(runner, "operator_restart", operator=OP, frame="asia")
    assert "not the calling frame" in str(exc.value) and world["compose"] == []
    with pytest.raises(fr.Refused) as exc:
        call(runner, "operator_restart", pid=999, operator=OP)
    assert "runs in no container" in str(exc.value) and world["compose"] == []


def test_the_stack_must_be_the_operators_own(rig, tmp_path):
    runner, world, wd, _ = rig
    labels = world["inspect"]["opreg1"]["Config"]["Labels"]
    good = dict(labels)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "docker-compose.operator.yml").write_text("services: {}\n")
    cases = (
        ("com.docker.compose.project.working_dir", str(elsewhere), "compose working dir"),
        ("com.docker.compose.project.working_dir", "", "compose working dir"),
        ("com.docker.compose.project.config_files", str(elsewhere / "docker-compose.operator.yml"), "compose files"),
        ("com.docker.compose.project.config_files", str(wd / "docker-compose.yml"), "compose files"),
        ("com.docker.compose.project.config_files", "", "compose files"),
        ("com.docker.compose.project.environment_file", str(wd / ".env"), "env file"),
    )
    for key, val, why in cases:
        labels.clear()
        labels.update(good)
        labels[key] = val
        refused(runner, world, "operator_restart", why, operator=OP)
    labels.clear()
    labels.update(good)
    (wd / ".env.operator").unlink()
    refused(runner, world, "operator_restart", "env file", operator=OP)


def test_one_registry_container_and_its_own_name(rig):
    runner, world, _, _ = rig
    world["containers"][f"cloud-op-{OP}"] = []
    refused(runner, world, "operator_restart", "0 registry container(s)", operator=OP)
    world["containers"][f"cloud-op-{OP}"] = ["opreg1", "opreg2"]
    refused(runner, world, "operator_restart", "2 registry container(s)", operator=OP)
    world["containers"][f"cloud-op-{OP}"] = ["opreg1"]
    world["inspect"]["opreg1"]["Config"]["Env"][1] = "REGISTRY_SAFE_NAME=someoneelse"
    refused(runner, world, "operator_restart", "names itself differently", operator=OP)
    world["inspect"]["opreg1"]["Config"]["Env"].pop(1)          # the Frame A era carried no REGISTRY_SAFE_NAME
    assert call(runner, "operator_restart", operator=OP, service="registry")["rc"] == 0


def test_a_job_on_the_operators_stack_refuses(rig, monkeypatch):
    runner, world, _, _ = rig
    monkeypatch.setattr(runner, "running_jobs", lambda: [{"id": "j1", "op": "operator_teardown", "operator": OP}])
    refused(runner, world, "operator_restart", "is running on this operator's stack", operator=OP)
    monkeypatch.setattr(runner, "running_jobs", lambda: [{"id": "j2", "op": "operator_provision", "operator": "other"}])
    assert call(runner, "operator_restart", operator=OP, service="registry")["rc"] == 0


def test_the_host_names_the_frame_project(rig):
    runner, world, _, _ = rig
    assert call(runner, "operator_restart", uid=0, pid=None, project="sbx-1788464843", operator=OP, service="registry")["frame"] == "sbx"
    refused(runner, world, "operator_restart", "project:", uid=0, pid=None, project="../x", operator=OP)


# ── logs: a bounded tail, a capped answer, an audit with no line in it ───────────────────────────────────────────

def test_logs_tail_is_bounded(rig):
    runner, world, wd, _ = rig
    for bad, why in ((5, "10 to 2000"), (5000, "10 to 2000"), ("abc", "whole number"), (True, "whole number"),
                     (20.5, "whole number"), ("-20", "whole number"), ([20], "whole number")):
        refused(runner, world, "operator_logs", why, operator=OP, service="registry", tail=bad)
    call(runner, "operator_logs", operator=OP, service="teg-layer", tail="50")
    cmd, _ = world["compose"][-1]
    assert cmd[-4:] == ["logs", "--no-color", "--tail=50", "teg-layer"]
    call(runner, "operator_logs", operator=OP, service="all")
    assert world["compose"][-1][0][-3:] == ["logs", "--no-color", "--tail=200"]


def test_logs_keep_the_newest_bytes_and_say_when_cut(rig):
    runner, world, _, _ = rig
    world["compose_out"] = b"old\n" * (fr.MAX_LOG_BYTES // 4) + b"NEWEST LINE\n"
    out = call(runner, "operator_logs", operator=OP, service="registry", tail=2000)
    assert out["truncated"] is True and out["output"].endswith("NEWEST LINE\n")
    assert len(out["output"].encode()) == fr.MAX_LOG_BYTES
    world["compose_out"] = b"short\n"
    out = call(runner, "operator_logs", operator=OP, service="registry")
    assert out["truncated"] is False and out["output"] == "short\n"


def test_the_audit_names_the_act_never_a_line_or_an_env_value(rig):
    runner, world, _, cfg = rig
    world["compose_out"] = b"a log line that must stay out of the audit\n"
    call(runner, "operator_logs", operator=OP, service="registry", tail=30)
    world["compose_rc"] = 1
    out = call(runner, "operator_restart", operator=OP, service="redis")
    assert out["restarted"] is False and out["rc"] == 1
    text = open(os.path.join(cfg.state, "audit.jsonl")).read()
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["op"] for r in rows] == ["operator_logs", "operator_restart"]
    assert rows[0]["tail"] == 30 and rows[0]["operator"] == OP and rows[1]["rc"] == 1 and rows[1]["service"] == "redis"
    assert "must stay out" not in text and "not-for-any-answer" not in text
    for answer in (out, call(runner, "operator_logs", operator=OP, service="registry")):
        assert "not-for-any-answer" not in json.dumps(answer) and TD not in json.dumps(answer.get("output", ""))


def test_a_compose_that_hangs_answers_124(rig):
    runner, world, _, _ = rig
    world["timeout"] = True
    out = call(runner, "operator_restart", operator=OP, service="registry")
    assert out["rc"] == 124 and out["restarted"] is False and "timed out" in out["output_tail"]

"""§NIGHTPROV (2026-09-27, his words "1 yes 2 approved 3 00:30z. go ahead."): the nightly provisioning job's pair.

The frame runner may build SANDBOX-posture frames at night, DNS names and a certificate per frame, created and removed
automatically. What that must mean and nothing more, pinned here on a real server with a FAKE driver:
  - only names in the job's namespace (nt<yymmdd>[x<n>] + a/b) are built as a nightly sandbox, and only for root: Frame
    Management (uid 1000) can neither build one nor take a name in that namespace;
  - the sandbox shape is DERIVED from the name, never taken from the caller: posture sandbox, the tester against the
    frame itself, the pair's shared fixture file and identity net, --wire-only sni,bundle, no mail relay;
  - the pair's b federates with its a, and only once a is a live frame this runner built;
  - every other frame keeps exactly what it had (production posture, --wire-prod, the relay): the controls.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import threading
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_nightly", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)
_tspec = importlib.util.spec_from_file_location("test_frame_runner_rig", HERE / "test_frame_runner.py")
base = importlib.util.module_from_spec(_tspec)
_tspec.loader.exec_module(base)

REGISTRY, TEG = "agentvault2-registry-a:v0470", "agentvault2-teg-layer:opprov1"
NIGHT = dict(base.SPEC, frame_label="Nightly A", ticker="NTA", currency_name="Nightly Unit A", registry_image=REGISTRY,
             teg_image=TEG, location_label="Falkenstein, Germany", lat=50.48, lng=12.37)


def _rig(tmp_path, nightly=True, workers=None):
    (tmp_path / "stack").mkdir()
    (tmp_path / "standup_driver.py").write_text(base.FAKE_DRIVER)
    shutil.copy(base.REPO_ROOT / "scripts" / "hetzner_demo" / "template_shape.py", tmp_path / "template_shape.py")
    (tmp_path / "template.yml.tmpl").write_text(base.FIXTURE_TEMPLATE)
    teardown = tmp_path / "teardown_hetzner_frame.sh"
    teardown.write_text(base.FAKE_TEARDOWN)
    teardown.chmod(0o755)
    plist = tmp_path / "protected-frames.list"
    plist.write_text("# fixture\neu\nasia\n")
    tok = tmp_path / "smtp.token"
    tok.write_text("a-real-looking-token\n")
    conf = {"images": {"registry": [REGISTRY], "teg": [TEG]}, "allowed_uids": [os.getuid(), 1000], "min_free_gb": 0,
            "max_load": 10 ** 6, "min_mem_gib": 0,
            "mail": {"server": "smtp.example.test", "address": "noreply@example.test", "token_file": str(tok)}}
    if nightly:
        conf["nightly"] = {"dir": str(tmp_path / "nightly")}
        if workers is not None:
            conf["nightly"]["registry_workers"] = workers
    cfg = fr.Config(conf=conf, socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "standup_driver.py"), teardown=str(teardown), python=sys.executable,
                    stack_root=str(tmp_path / "stack"), protected_list=str(plist), template=str(tmp_path / "template.yml.tmpl"))
    srv = fr.make_server(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return cfg, srv


@pytest.fixture
def rig(tmp_path):
    cfg, srv = _rig(tmp_path)
    yield cfg, srv, tmp_path
    active = srv.runner.active()
    if active:
        fr.os.killpg(active["pid"], 9)
    srv.shutdown()
    srv.server_close()


def call(cfg, **req):
    return fr.call(cfg.socket, req, timeout=60)


def wait_state(cfg, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = call(cfg, op="status", job_id=job_id)["result"]["job"]
        if rec["state"] in ("succeeded", "failed", "cancelled", "lost"):
            return rec
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never finished")


def last_call(tmp_path, name, plan=None):
    calls = [c for c in base.calls(tmp_path) if c["argv"][c["argv"].index("--name") + 1] == name]
    if plan is not None:
        calls = [c for c in calls if ("--plan" in c["argv"]) == plan]
    return calls[-1]


def val(argv, flag):
    return argv[argv.index(flag) + 1]


@pytest.fixture(autouse=True)
def _root_only():
    if os.getuid() != 0:
        pytest.skip("the nightly names are root's: these tests call the socket as root, as the host's job does")


def test_a_nightly_frame_is_a_sandbox_derived_from_its_name(rig):
    cfg, _, tmp_path = rig
    r = call(cfg, op="plan", spec={**NIGHT, "name": "nt260927x1a"})
    assert r["ok"] is True and r["result"]["plan_ok"] is True, r
    c = last_call(tmp_path, "nt260927x1a", plan=True)
    argv = c["argv"]
    assert val(argv, "--posture") == "sandbox" and val(argv, "--env-label") == "sandbox"
    assert "--tester-self" in argv
    assert val(argv, "--tester-fixture-secrets") == os.path.join(str(tmp_path / "nightly"), "nt260927x1", "fixtures.secret.json")
    assert val(argv, "--identity-net") == "nt260927x1-identity" and "--identity-net-external" in argv
    assert val(argv, "--wire-only") == "sni,bundle" and "--wire-prod" not in argv
    # the pair reaches each other's bundle endpoint over their identity net, never through the host's published port
    assert val(argv, "--bundle-public-url") == "https://nt260927x1a-spire-server:8443/"
    assert "--federate-with" not in argv, "the pair's a is the anchor; it federates with nothing at its own standup"
    assert not any(k.startswith("FRAME_MAIL_") for k in c["env_keys"]), "a nightly sandbox mails nobody"


def test_the_pairs_b_federates_with_its_a_and_only_once_a_is_live(rig):
    cfg, _, tmp_path = rig
    early = call(cfg, op="plan", spec={**NIGHT, "name": "nt260927x1b", "ticker": "NTB"})
    assert early["ok"] is False and "nt260927x1a is not a live frame this runner built" in early["refused"], early
    rec = wait_state(cfg, call(cfg, op="standup", spec={**NIGHT, "name": "nt260927x1a"})["result"]["job"]["id"])
    assert rec["state"] == "succeeded", rec
    a = next(f for f in call(cfg, op="status")["result"]["frames"] if f["name"] == "nt260927x1a")
    assert a["state"] == "live" and a["spec"]["nightly"] == {"pair": "nt260927x1", "role": "a"}
    r = call(cfg, op="plan", spec={**NIGHT, "name": "nt260927x1b", "ticker": "NTB"})
    assert r["ok"] is True, r
    argv = last_call(tmp_path, "nt260927x1b", plan=True)["argv"]
    assert val(argv, "--federate-with") == a["stack_dir"]
    assert val(argv, "--identity-net") == "nt260927x1-identity", "one identity net for the pair"


def test_a_resume_keeps_the_nightly_shape(rig):
    cfg, _, tmp_path = rig
    wait_state(cfg, call(cfg, op="standup", spec={**NIGHT, "name": "nt260927x1a"})["result"]["job"]["id"])
    rid = call(cfg, op="resume", name="nt260927x1a", from_step="wire")["result"]["job"]["id"]
    assert wait_state(cfg, rid)["state"] == "succeeded"
    c = [x for x in base.calls(tmp_path) if "--resume-stack-dir" in x["argv"]][-1]
    assert val(c["argv"], "--posture") == "sandbox" and "--tester-self" in c["argv"] and "--wire-prod" not in c["argv"]
    assert not any(k.startswith("FRAME_MAIL_") for k in c["env_keys"])


def test_frame_management_can_neither_build_one_nor_take_the_namespace(rig):
    _, srv, _ = rig
    for op in ("plan", "standup"):
        with pytest.raises(fr.Refused, match="only the host's nightly job"):
            srv.runner.handle({"op": op, "spec": {**NIGHT, "name": "nt260927a"}}, 1000)
    for name in ("nt260927", "nt260927c", "nt260927x1", "nt260927-lab"):
        with pytest.raises(fr.Refused, match="in the nightly job's names"):
            srv.runner.handle({"op": "plan", "spec": {**NIGHT, "name": name}}, 0)


def test_a_policy_without_nightly_refuses_the_names(tmp_path):
    cfg, srv = _rig(tmp_path, nightly=False)
    try:
        r = call(cfg, op="plan", spec={**NIGHT, "name": "nt260927a"})
        assert r["ok"] is False and "does not offer nightly pairs" in r["refused"], r
        assert call(cfg, op="ping")["result"]["nightly"] is False
    finally:
        srv.shutdown()
        srv.server_close()


def test_control_every_other_frame_keeps_its_production_shape(rig):
    cfg, _, tmp_path = rig
    assert call(cfg, op="ping")["result"]["nightly"] is True
    r = call(cfg, op="plan", spec={**NIGHT, "name": "juice"})
    assert r["ok"] is True, r
    c = last_call(tmp_path, "juice", plan=True)
    argv = c["argv"]
    assert val(argv, "--posture") == "production" and val(argv, "--env-label") == "production"
    assert "--wire-prod" in argv and "--wire-only" not in argv
    for flag in ("--tester-self", "--tester-fixture-secrets", "--identity-net", "--federate-with", "--bundle-public-url"):
        assert flag not in argv, flag
    assert "FRAME_MAIL_SERVER" in c["env_keys"], "a production frame keeps its relay"
    # this plan was asked by ROOT, the nightly job's own uid: the name decides the shape, never the caller


def test_the_pairs_registry_takes_the_policys_worker_count_and_only_the_pair(tmp_path):
    """sbx-alpha, the suites' standing target, runs 8 registry workers; a runner-built frame takes the provisioner's 4.
    The pair takes the policy's count (a nightly frame, its resume); every other frame keeps what it had."""
    cfg, srv = _rig(tmp_path, workers=8)
    try:
        assert call(cfg, op="plan", spec={**NIGHT, "name": "nt260927x1a"})["ok"] is True
        assert val(last_call(tmp_path, "nt260927x1a", plan=True)["argv"], "--registry-workers") == "8"
        rec = wait_state(cfg, call(cfg, op="standup", spec={**NIGHT, "name": "nt260927x1a"})["result"]["job"]["id"])
        assert rec["state"] == "succeeded", rec
        rid = call(cfg, op="resume", name="nt260927x1a", from_step="wire")["result"]["job"]["id"]
        assert wait_state(cfg, rid)["state"] == "succeeded"
        resumed = [x for x in base.calls(tmp_path) if "--resume-stack-dir" in x["argv"]][-1]["argv"]
        assert val(resumed, "--registry-workers") == "8", "a resume renders the same frame"
        assert call(cfg, op="plan", spec={**NIGHT, "name": "juice"})["ok"] is True
        assert "--registry-workers" not in last_call(tmp_path, "juice", plan=True)["argv"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_control_no_count_in_the_policy_passes_none(rig):
    cfg, _, tmp_path = rig
    assert call(cfg, op="plan", spec={**NIGHT, "name": "nt260927x1a"})["ok"] is True
    assert "--registry-workers" not in last_call(tmp_path, "nt260927x1a", plan=True)["argv"]


@pytest.mark.parametrize("bad", [17, -1, True, "8", 2.5])
def test_a_worker_count_the_driver_would_refuse_stops_the_runner_at_start(tmp_path, bad):
    with pytest.raises(SystemExit, match="nightly.registry_workers"):
        _rig(tmp_path, workers=bad)

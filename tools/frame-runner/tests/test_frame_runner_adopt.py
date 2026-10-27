"""§HELLOFRAME lane 6 (2026-09-18): `adopt`, the narrow bridge for a frame this runner did not build.

frame-up stands a frame up on a stranger's host with its own flow and the runner refuses operator work for a frame it
holds no record of ("was not built by this runner"). `adopt` records such a frame — root only, the full socket only,
the same three facts `built_frame` demands — and marks it adopted: operator ops accept it, lifecycle ops refuse it.
docker is a fake that answers for `<name>-registry`; nothing here touches the host."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def _runner(tmp_path, monkeypatch, **conf):
    base = {"images": {"registry": ["agentvault2-registry-a:v0359"], "teg": ["agentvault2-teg-layer:v0351"]},
            "allowed_uids": [os.getuid()], "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0}
    base.update(conf)
    plist = tmp_path / "protected.list"
    plist.write_text("# fixture\neu\nasia\n")
    cfg = fr.Config(conf=base, socket=str(tmp_path / "run" / "fr.sock"),
                    operator_socket=str(tmp_path / "run" / "operator" / "fr.sock"),
                    state=str(tmp_path / "state"), driver=str(tmp_path / "standup_driver.py"),
                    teardown=str(tmp_path / "teardown.sh"), python=sys.executable,
                    stack_root=str(tmp_path / "stack"), protected_list=str(plist),
                    template=str(tmp_path / "template.yml.tmpl"))
    (tmp_path / "stack").mkdir(exist_ok=True)
    return fr.Runner(cfg)


def _stack(tmp_path, name="harbor", *, meta_name=None, where=None):
    d = (where or (tmp_path / "stack")) / f"{name}-1789000000"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"name": meta_name if meta_name is not None else name, "ts": 1789000000, "stack_dir": str(d),
            "trust_domain": f"{name}.example", "ticker": "HBR", "currency_name": "Harbor Unit",
            "frame_label": "Harbor", "env_label": "production", "public_url": f"https://{name}.example",
            "secrets_dir": str(tmp_path / "secrets")}
    (d / "hetzner-demo-run.json").write_text(json.dumps(meta))
    return d


def _fake_docker(monkeypatch, running=True, missing=False):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            if missing:
                return subprocess.CompletedProcess(argv, 1, "", f"Error: No such object: {argv[2]}")
            return subprocess.CompletedProcess(argv, 0, "true\n" if running else "false\n", "")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    return calls


def _audit(runner):
    p = pathlib.Path(runner.cfg.state) / "audit.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def test_adopt_is_a_full_socket_op_and_never_an_operator_socket_op():
    assert "adopt" in fr.OPS and "adopt" not in fr.OPERATOR_OPS


def test_adopt_records_the_frame_from_the_drivers_run_record_and_is_idempotent(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    stack = _stack(tmp_path)
    calls = _fake_docker(monkeypatch)
    out = runner.op_adopt({"name": "harbor", "stack_dir": str(stack)}, 0)
    assert out == {"name": "harbor", "stack_dir": str(stack), "recorded": True, "already": False, "adopted": True,
                   "reference": False}
    assert calls == [["docker", "inspect", "harbor-registry", "--format", "{{.State.Running}}"]]
    rec = runner.frame("harbor")
    assert rec["adopted"] is True and rec["built_by_job"] is None and rec["stack_dir"] == str(stack)
    assert rec["spec"] == {"name": "harbor", "frame_label": "Harbor", "ticker": "HBR", "currency_name": "Harbor Unit",
                           "trust_domain": "harbor.example", "public_url": "https://harbor.example",
                           "env_label": "production"}
    assert rec["secrets_dir"] == str(tmp_path / "secrets") and rec["dns_managed"] is False
    assert rec["state"] == "live (adopted)" and rec["created"] and rec["updated"]
    assert [a["op"] for a in _audit(runner)] == ["adopt"] and _audit(runner)[0]["already"] is False
    again = runner.op_adopt({"name": "harbor", "stack_dir": str(stack) + "/"}, 0)
    assert again == {"name": "harbor", "stack_dir": str(stack), "recorded": False, "already": True, "adopted": True,
                     "reference": False}
    assert runner.frame("harbor") == rec, "an already-recorded frame is left exactly as it was"
    assert _audit(runner)[-1]["already"] is True


def test_an_adopted_frame_is_the_operator_ops_frame_and_not_the_lifecycle_ops_frame(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    stack = _stack(tmp_path)
    _fake_docker(monkeypatch)
    runner.op_adopt({"name": "harbor", "stack_dir": str(stack)}, 0)
    assert runner._operator_frame({"frame": "harbor"})["stack_dir"] == str(stack)
    with pytest.raises(fr.Refused, match="adopted by this runner, not built"):
        runner.built_frame("harbor")
    for op in (runner.op_resume, runner.op_teardown, runner.op_reveal):
        with pytest.raises(fr.Refused, match="adopted"):
            op({"name": "harbor", "from_step": fr.RESUMABLE_STEPS[0]}, 0)


def test_the_status_listing_carries_an_adopted_frame(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    stack = _stack(tmp_path)
    _fake_docker(monkeypatch)
    runner.op_adopt({"name": "harbor", "stack_dir": str(stack)}, 0)
    frames = runner.op_status({}, 0)["frames"]
    assert [f["name"] for f in frames] == ["harbor"] and frames[0]["adopted"] is True


@pytest.mark.parametrize("req,uid,why", [
    ({"name": "harbor", "stack_dir": "STACK"}, 1000, "root only"),
    ({"name": "Harbor", "stack_dir": "STACK"}, 0, "not a frame name"),
    ({"name": "eu", "stack_dir": "STACK"}, 0, "protected frame"),
    ({"name": "harbor"}, 0, "not a directory directly under"),
    ({"name": "harbor", "stack_dir": "ELSEWHERE"}, 0, "not a directory directly under"),
    ({"name": "harbor", "stack_dir": "NESTED"}, 0, "not a directory directly under"),
    ({"name": "harbor", "stack_dir": "OTHERNAME"}, 0, "does not name harbor"),
    ({"name": "harbor", "stack_dir": "NOMETA"}, 0, "does not name harbor"),
])
def test_RED_what_adopt_refuses_before_touching_a_record(tmp_path, monkeypatch, req, uid, why):
    runner = _runner(tmp_path, monkeypatch)
    stack = _stack(tmp_path)
    other = _stack(tmp_path, "harbor", meta_name="someone-else")
    nested = _stack(tmp_path, "harbor", where=tmp_path / "stack" / "deeper")
    nometa = tmp_path / "stack" / "harbor-2"
    nometa.mkdir()
    elsewhere = _stack(tmp_path, "harbor", where=tmp_path / "elsewhere")
    calls = _fake_docker(monkeypatch)
    paths = {"STACK": str(stack), "ELSEWHERE": str(elsewhere), "NESTED": str(nested), "OTHERNAME": str(other),
             "NOMETA": str(nometa)}
    if "stack_dir" in req:
        req = {**req, "stack_dir": paths[req["stack_dir"]]}
    with pytest.raises(fr.Refused, match=why):
        runner.op_adopt(req, uid)
    assert runner.frame(req["name"]) is None and not calls, "refused before docker is asked and before any record"


def test_RED_a_frame_whose_registry_is_not_running_is_not_adopted(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    stack = _stack(tmp_path)
    _fake_docker(monkeypatch, running=False)
    with pytest.raises(fr.Refused, match="harbor-registry is not running"):
        runner.op_adopt({"name": "harbor", "stack_dir": str(stack)}, 0)
    _fake_docker(monkeypatch, missing=True)
    with pytest.raises(fr.Refused, match="No such object"):
        runner.op_adopt({"name": "harbor", "stack_dir": str(stack)}, 0)
    assert runner.frame("harbor") is None


def test_RED_a_name_already_recorded_elsewhere_is_not_moved(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    first = _stack(tmp_path)
    _fake_docker(monkeypatch)
    runner.op_adopt({"name": "harbor", "stack_dir": str(first)}, 0)
    second = tmp_path / "stack" / "harbor-1789999999"
    second.mkdir()
    (second / "hetzner-demo-run.json").write_text(json.dumps({"name": "harbor"}))
    with pytest.raises(fr.Refused, match="already recorded at"):
        runner.op_adopt({"name": "harbor", "stack_dir": str(second)}, 0)
    assert runner.frame("harbor")["stack_dir"] == str(first)


@pytest.mark.skipif(os.getuid() != 0, reason="the adopt op admits uid 0 only; the CLI test needs a root peer")
def test_the_cli_speaks_to_the_full_socket_and_exits_0_2_3(tmp_path, monkeypatch, capsys):
    runner = _runner(tmp_path, monkeypatch)
    stack = _stack(tmp_path)
    real_run = fr.subprocess.run

    def fake_run(argv, **kw):
        if argv[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, "true\n", "")
        return real_run(argv, **kw)

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    (tmp_path / "run").mkdir(exist_ok=True)
    srv = fr.make_server(runner.cfg, runner)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("FRAME_RUNNER_SOCKET", runner.cfg.socket)
        assert fr.main(["adopt", "--name", "harbor", "--stack-dir", str(stack)]) == 0
        out = capsys.readouterr()
        assert json.loads(out.out.strip().splitlines()[-1])["recorded"] is True and "recorded at" in out.err
        assert fr.main(["adopt", "--name", "harbor", "--stack-dir", str(stack)]) == 0, "idempotent"
        assert "already recorded" in capsys.readouterr().err
        assert fr.main(["adopt", "--name", "nobody", "--stack-dir", str(stack)]) == 2
        assert "REFUSED" in capsys.readouterr().err
        assert fr.main(["adopt", "--name", "harbor", "--stack-dir", str(stack), "--socket", str(tmp_path / "none.sock")]) == 3
        assert "did not answer" in capsys.readouterr().err
        assert fr.main(["adopt", "--name", "harbor"]) == 2, "argparse refusal is exit 2 too"
    finally:
        srv.shutdown()
        srv.server_close()


# ── §F6 stage 3 (2026-09-27): one of OUR frames, recorded as a REFERENCE for operator work only ─────────────────────────
def test_one_of_ours_is_recorded_only_as_a_reference_and_only_on_the_explicit_word(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    eu = _stack(tmp_path, "eu")
    calls = _fake_docker(monkeypatch)
    with pytest.raises(fr.Refused, match="protected frame.*reference=true records one of ours"):
        runner.op_adopt({"name": "eu", "stack_dir": str(eu)}, 0)
    assert runner.frame("eu") is None and not calls
    out = runner.op_adopt({"name": "eu", "stack_dir": str(eu), "reference": True}, 0)
    assert out["recorded"] is True and out["reference"] is True and out["adopted"] is True
    rec = runner.frame("eu")
    assert rec["reference"] is True and rec["adopted"] is True and rec["state"] == "live (reference)"
    assert runner._operator_frame({"frame": "eu"})["stack_dir"] == str(eu), "its registry may ask for operator work"
    # its lifecycle is refused twice over: the protected name first, the adopted record behind it
    with pytest.raises(fr.Refused, match="protected frame"):
        runner.built_frame("eu")
    for op in (runner.op_resume, runner.op_teardown, runner.op_reveal):
        with pytest.raises(fr.Refused, match="protected frame"):
            op({"name": "eu", "from_step": fr.RESUMABLE_STEPS[0]}, 0)
    again = runner.op_adopt({"name": "eu", "stack_dir": str(eu), "reference": True}, 0)
    assert again["already"] is True and again["reference"] is True
    assert _audit(runner)[0]["reference"] is True


@pytest.mark.parametrize("req,uid,why", [
    ({"name": "harbor", "reference": True}, 0, "not on the protected list"),     # a stranger's frame is never a reference
    ({"name": "eu", "reference": True}, 1000, "root only"),
    ({"name": "eu", "reference": "true"}, 0, "protected frame"),                  # the word is the boolean, not a string
])
def test_RED_what_a_reference_adopt_refuses(tmp_path, monkeypatch, req, uid, why):
    runner = _runner(tmp_path, monkeypatch)
    stacks = {"harbor": _stack(tmp_path), "eu": _stack(tmp_path, "eu")}
    calls = _fake_docker(monkeypatch)
    with pytest.raises(fr.Refused, match=why):
        runner.op_adopt({**req, "stack_dir": str(stacks[req["name"]])}, uid)
    assert runner.frame(req["name"]) is None and not calls


def test_a_reference_is_forgotten_live_only_on_the_explicit_word_and_a_strangers_frame_never_live(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    eu, harbor = _stack(tmp_path, "eu"), _stack(tmp_path)
    _fake_docker(monkeypatch)                           # both registries answer: running
    runner.op_adopt({"name": "eu", "stack_dir": str(eu), "reference": True}, 0)
    runner.op_adopt({"name": "harbor", "stack_dir": str(harbor)}, 0)
    with pytest.raises(fr.Refused, match="takes reference=true"):
        runner.op_unadopt({"name": "eu"}, 0)
    assert runner.frame("eu") is not None
    assert runner.op_unadopt({"name": "eu", "reference": True}, 0)["forgotten"] is True, "the rollback of the reference"
    assert runner.frame("eu") is None
    with pytest.raises(fr.Refused, match="still exists"):   # control: a stranger's frame is still forgotten dead only
        runner.op_unadopt({"name": "harbor", "reference": True}, 0)
    assert runner.frame("harbor") is not None

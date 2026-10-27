"""§F6 B1 (2026-09-27): the operator's identity network of a frame born before FT_REG_IDENTITY_NETWORK existed.

Measured on sbx-beta (stood up 2026-09-03): its env file carries no FT_REG_IDENTITY_NETWORK, its registry's own
IDENTITY_NETWORK names `sandbox-federation-identity` (what the registry's provisioner reads on its direct route), and the
registry is attached to it. With HOST_REACH_PREFER=runner the runner refused the activation's bundle job and the admin
provision ("carries no FT_REG_IDENTITY_NETWORK ... will not guess one"). The env file still wins wherever it names the
network; the registry's own value is taken only when the registry is ON that network. docker is a fake here."""
import importlib.util
import json
import pathlib
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_idnet", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def _runner(tmp_path):
    plist = tmp_path / "protected.list"
    plist.write_text("eu\n")
    (tmp_path / "stack").mkdir(exist_ok=True)
    cfg = fr.Config(conf={"images": {"registry": ["r:1"], "teg": ["t:1"]}, "min_free_gb": 0, "max_load": 10 ** 6,
                          "min_mem_gib": 0}, state=str(tmp_path / "state"), stack_root=str(tmp_path / "stack"),
                    protected_list=str(plist))
    return fr.Runner(cfg)


def _frame(tmp_path, env_text):
    sd = tmp_path / "stack" / "beta-1"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / ".env.frame-test").write_text(env_text)
    return {"name": "beta", "stack_dir": str(sd), "spec": {}, "state": "live (reference)"}


def _fake_docker(monkeypatch, env, networks, existing=("sandbox-federation-identity", "fresh-identity")):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"] and argv[2] == "beta-registry":
            doc = [{"Config": {"Env": env}, "NetworkSettings": {"Networks": {n: {} for n in networks}}}]
            return subprocess.CompletedProcess(argv, 0, json.dumps(doc), "")
        if argv[:3] == ["docker", "network", "inspect"]:
            ok = argv[3] in existing
            return subprocess.CompletedProcess(argv, 0 if ok else 1, argv[3] + "\n" if ok else "", "" if ok else "No such network")
        raise AssertionError(f"unexpected command {argv}")
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    return calls


def test_a_frame_born_before_the_key_is_read_from_its_registry_when_the_registry_is_on_it(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    frame = _frame(tmp_path, "FT_REG_OTHER=x\n")
    _fake_docker(monkeypatch, ["IDENTITY_NETWORK=sandbox-federation-identity", "A=b"],
                 ["sandbox-federation-identity", "sbx_beta_network"])
    assert runner._frame_identity_network(frame) == "sandbox-federation-identity"


def test_the_env_file_still_wins_and_the_registry_is_not_asked(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    frame = _frame(tmp_path, "FT_REG_IDENTITY_NETWORK=fresh-identity\n")
    calls = _fake_docker(monkeypatch, ["IDENTITY_NETWORK=sandbox-federation-identity"], ["sandbox-federation-identity"])
    assert runner._frame_identity_network(frame) == "fresh-identity"
    assert not any(c[:2] == ["docker", "inspect"] for c in calls), "the frames the key already names read exactly as before"


@pytest.mark.parametrize("env, networks", [
    (["IDENTITY_NETWORK=sandbox-federation-identity"], ["sbx_beta_network"]),     # named, but the registry is not on it
    (["A=b"], ["sandbox-federation-identity"]),                                   # not named at all
    (["IDENTITY_NETWORK="], ["sandbox-federation-identity"]),                     # named empty
    (["IDENTITY_NETWORK=bad name;rm"], ["bad name;rm"]),                          # not a network name
])
def test_RED_a_registry_value_that_is_not_its_network_is_refused(tmp_path, monkeypatch, env, networks):
    runner = _runner(tmp_path)
    frame = _frame(tmp_path, "FT_REG_OTHER=x\n")
    _fake_docker(monkeypatch, env, networks)
    with pytest.raises(fr.Refused, match="will not guess one"):
        runner._frame_identity_network(frame)


def test_RED_a_named_network_that_does_not_exist_is_refused(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    frame = _frame(tmp_path, "FT_REG_OTHER=x\n")
    _fake_docker(monkeypatch, ["IDENTITY_NETWORK=gone-identity"], ["gone-identity"], existing=())
    with pytest.raises(fr.Refused, match="does not exist on this host"):
        runner._frame_identity_network(frame)

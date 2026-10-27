"""§HELLOFRAME lane 6 (2026-09-18): a runner INSTANCE, a second runner beside a host's production one.

The network's own host runs the production frame runner (its unit, its policy, its sockets under /run/theprotocol);
proving frame-up --with-runner there must not touch it. FRAME_RUNNER_INSTANCE=<name> scopes every path the runner
owns; unset, every default is byte-identical to before this knob existed (the first test pins those strings)."""
import importlib.util
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

SINGLE = {"unit": "theprotocol-frame-runner", "config": "/etc/theprotocol/frame-runner.json",
          "socket": "/run/theprotocol/frame-runner.sock", "operator_socket": "/run/theprotocol/operator/frame-runner.sock",
          "state": "/var/lib/theprotocol/frame-runner", "runtime_dir": "theprotocol", "state_dir": "theprotocol/frame-runner"}


def test_no_instance_is_the_single_runner_byte_for_byte(monkeypatch):
    for k in ("FRAME_RUNNER_INSTANCE", "FRAME_RUNNER_SOCKET", "FRAME_RUNNER_OPERATOR_SOCKET", "FRAME_RUNNER_STATE",
              "FRAME_RUNNER_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    assert fr.instance_paths("") == SINGLE and fr.instance_paths() == SINGLE
    cfg = fr.Config(conf={})
    assert cfg.instance == "" and cfg.socket == SINGLE["socket"] and cfg.operator_socket == SINGLE["operator_socket"]
    assert cfg.state == SINGLE["state"] and cfg.config_path == SINGLE["config"]


def test_an_instance_owns_its_own_sockets_state_policy_and_unit(monkeypatch):
    for k in ("FRAME_RUNNER_SOCKET", "FRAME_RUNNER_OPERATOR_SOCKET", "FRAME_RUNNER_STATE", "FRAME_RUNNER_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    p = fr.instance_paths("hello")
    assert p == {"unit": "theprotocol-frame-runner-hello", "config": "/etc/theprotocol/frame-runner-hello.json",
                 "socket": "/run/theprotocol/hello/frame-runner.sock",
                 "operator_socket": "/run/theprotocol/hello/operator/frame-runner.sock",
                 "state": "/var/lib/theprotocol/frame-runner-hello",
                 "runtime_dir": "theprotocol/hello", "state_dir": "theprotocol/frame-runner-hello"}
    monkeypatch.setenv("FRAME_RUNNER_INSTANCE", "hello")
    cfg = fr.Config(conf={})
    assert cfg.instance == "hello" and cfg.socket == p["socket"] and cfg.operator_socket == p["operator_socket"]
    assert cfg.state == p["state"] and cfg.config_path == p["config"]
    monkeypatch.delenv("FRAME_RUNNER_INSTANCE")
    kw = fr.Config(conf={}, instance="hello")
    assert kw.socket == p["socket"] and kw.state == p["state"]
    # a second instance shares nothing with the first
    q = fr.instance_paths("other")
    assert not set(q.values()) & set(p.values())


def test_an_explicit_path_still_wins_over_the_instance(monkeypatch):
    monkeypatch.setenv("FRAME_RUNNER_INSTANCE", "hello")
    monkeypatch.setenv("FRAME_RUNNER_STATE", "/srv/state")
    monkeypatch.setenv("FRAME_RUNNER_CONFIG", "/srv/policy.json")
    monkeypatch.delenv("FRAME_RUNNER_SOCKET", raising=False)
    monkeypatch.delenv("FRAME_RUNNER_OPERATOR_SOCKET", raising=False)
    cfg = fr.Config(conf={})
    assert cfg.state == "/srv/state" and cfg.config_path == "/srv/policy.json"
    assert cfg.socket == "/run/theprotocol/hello/frame-runner.sock"
    kw = fr.Config(conf={}, socket="/tmp/x/fr.sock")
    assert kw.socket == "/tmp/x/fr.sock" and kw.operator_socket == "/tmp/x/operator/frame-runner.sock"


@pytest.mark.parametrize("bad", ["Hello", "hello world", "-hello", "a" * 33, "hello.", "../x"])
def test_RED_an_instance_is_named_like_a_frame_or_refused(bad, monkeypatch):
    with pytest.raises(ValueError):
        fr.instance_paths(bad)
    monkeypatch.setenv("FRAME_RUNNER_INSTANCE", bad)
    with pytest.raises(SystemExit):
        fr.Config(conf={})

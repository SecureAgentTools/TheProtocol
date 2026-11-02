"""V0653 (ao) item 2 (the dev machine's beta.30 test, room seq 582 and 587/588): the kit can take the frame runner off a
host, everything its installer put there and nothing else.

frame-runner-install.py --remove: the unit (disabled and stopped), its policy and the installer's backups of it, the
protected-frames list once no other runner instance remains, the socket group only when the installer created it
(the policy records that since V0653) and no other runner remains; refused while the runner holds a frame whose
registry container exists; its state kept unless --purge-state; --dry-run touches nothing. frame-down --with-runner
runs it once the frame is gone, for a runner that frame installed (never its parent's). Every host path and call is a
scratch one here. BASE (kit beta.31): there is no --remove and no --with-runner.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fri = _load("frame_runner_install_v0653", "frame-runner-install.py")
fdown = _load("frame_down_v0653", "frame-down.py")


@pytest.fixture()
def host(tmp_path, monkeypatch):
    etc, units, state = tmp_path / "etc", tmp_path / "units", tmp_path / "state"
    for d in (etc, units, state / "frames"):
        d.mkdir(parents=True)
    paths = {"unit": "theprotocol-frame-runner", "config": str(etc / "frame-runner.json"), "state": str(state),
             "socket": "/run/theprotocol/frame-runner.sock", "operator_socket": "/run/theprotocol/operator/frame-runner.sock",
             "instance": ""}
    monkeypatch.setattr(fri, "runner_paths", lambda root, instance: dict(paths))
    monkeypatch.setattr(fri.os, "geteuid", lambda: 0)
    groups = {"deploy"}
    monkeypatch.setattr(fri, "group_exists", lambda g: g in groups)
    (units / "theprotocol-frame-runner.service").write_text("[Unit]\n")
    (etc / "frame-runner.json").write_text(json.dumps({"socket_group": "deploy", "socket_group_created": True}))
    (etc / "frame-runner.json.bak-pre-install-20261101T000000Z").write_text("{}")
    (etc / "protected-frames.list").write_text("# frames\n")
    calls = []

    def sh(argv):
        calls.append(argv)
        if argv[0] == "groupdel":
            groups.discard(argv[1])
        return subprocess.CompletedProcess(argv, 0, "", "")

    return {"tmp": tmp_path, "etc": etc, "units": units, "state": state, "calls": calls, "sh": sh, "groups": groups}


def _remove(host, *, dry=False, purge=False, live=()):
    a = argparse.Namespace(export_root=str(host["tmp"]), instance="", dry_run=dry, socket_group="deploy", purge_state=purge)
    return fri.remove(a, sh=host["sh"], exists=lambda name: name in {f"{n}-registry" for n in live},
                      unit_dir=str(host["units"]), protected=str(host["etc"] / "protected-frames.list"))


def test_removes_what_the_installer_put_there(host, capsys):
    assert _remove(host) == 0
    assert not (host["units"] / "theprotocol-frame-runner.service").exists()
    assert sorted(os.listdir(host["etc"])) == []                      # the policy, its backup, the protected list
    assert host["calls"] == [["systemctl", "disable", "--now", "theprotocol-frame-runner"], ["systemctl", "daemon-reload"],
                             ["groupdel", "deploy"]]
    assert host["state"].is_dir() and "kept the runner's state" in capsys.readouterr().out


def test_refused_while_the_runner_holds_a_frame_that_runs(host):
    (host["state"] / "frames" / "lantern.json").write_text("{}")
    with pytest.raises(fri.Refused) as e:
        _remove(host, live=("lantern",))
    assert "lantern" in e.value.why and "nothing was removed" in e.value.why
    assert (host["units"] / "theprotocol-frame-runner.service").exists() and host["calls"] == []


def test_a_frame_whose_registry_is_gone_does_not_hold_it(host):
    (host["state"] / "frames" / "lantern.json").write_text("{}")
    assert _remove(host, live=()) == 0


def test_another_instance_keeps_the_shared_list_and_the_group(host, capsys):
    (host["units"] / "theprotocol-frame-runner-hello.service").write_text("[Unit]\n")
    assert _remove(host) == 0
    assert (host["etc"] / "protected-frames.list").exists() and "deploy" in host["groups"]
    assert "another runner instance remains" in capsys.readouterr().out


def test_a_group_the_host_had_before_stays(host, capsys):
    (host["etc"] / "frame-runner.json").write_text(json.dumps({"socket_group": "deploy", "socket_group_created": False}))
    assert _remove(host) == 0
    assert "deploy" in host["groups"] and ["groupdel", "deploy"] not in host["calls"]
    assert "groupdel deploy" in capsys.readouterr().out


def test_a_dry_run_touches_nothing(host):
    assert _remove(host, dry=True) == 0
    assert host["calls"] == [] and (host["units"] / "theprotocol-frame-runner.service").exists()
    assert len(os.listdir(host["etc"])) == 3


def test_purge_state_removes_the_runners_state(host):
    assert _remove(host, purge=True) == 0
    assert not host["state"].exists()


def test_the_policy_records_a_group_the_installer_creates_and_keeps_the_record(monkeypatch):
    base = dict(images_prefix="p", version="V0653", image_registry="", image_teg="", image_event_store="",
                image_auditor="", image_directory="", posture="production", socket_group="deploy", allowed_uids="0,1000",
                edge="caddy", domain="x.example", max_load="40", min_mem_gib="8", min_free_gb="20", mail_server="",
                export_root="/e", instance="")
    assert fri.build_policy(argparse.Namespace(**base, group_missing=True))["socket_group_created"] is True
    again = fri.build_policy(argparse.Namespace(**base, group_missing=False), {"socket_group": "deploy", "socket_group_created": True})
    assert again["socket_group_created"] is True
    assert fri.build_policy(argparse.Namespace(**base, group_missing=False))["socket_group_created"] is False


def test_frame_down_finds_the_runner_instance_it_installed():
    assert fdown.runner_instance({"installed": True, "instance": "hello"}) == "hello"
    assert fdown.runner_instance({"installed": True, "instance": ""}) == ""
    assert fdown.runner_instance({"installed": True, "socket": "/run/theprotocol/frame-runner.sock"}) == ""
    assert fdown.runner_instance({"installed": True, "socket": "/run/theprotocol/hello/frame-runner.sock"}) == "hello"
    assert fdown.runner_instance({"installed": True, "socket": "/elsewhere.sock"}) is None


def test_frame_down_leaves_a_parents_runner_alone(capsys, monkeypatch):
    monkeypatch.setattr(fdown, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran the remover")))
    a = argparse.Namespace(name="lantern-sbx", stack_root="/s")
    assert fdown.remove_runner(a, {"via_parent": "lantern"}, 0) == 0
    assert "its parent's runner" in capsys.readouterr().out

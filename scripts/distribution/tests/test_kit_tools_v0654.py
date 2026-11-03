"""V0654 (au) (order gwo_1975d53536c1b6070fa5eb2a): the kit's tools after kit beta.32's runner-removal run on a throwaway frame
(session-devmachine, the sessions' room seq 1119): the paragraph held, four small findings.

1. frame-runner-install.py --remove a second time said it "kept the group deploy: this installer did not create it" about a
   group the first --remove had removed: a group already gone is said to be gone.
2. frame-down --with-runner relayed "--purge-state removes it", which is not a frame-down option: the line names the
   command that has it (frame-runner-install.py --remove [--instance <name>] --purge-state).
3. --remove left /run/theprotocol and its two sockets (the unit preserves its runtime directory over a stop): it removes
   the runner's two sockets and every directory of theirs they leave empty, never one holding anything else.
4. Internal tags (§HELLOFRAME, §TESTBED, ...) in what an operator reads: every kit tool's --help, the runner's unit file.

Every host path and call is a scratch one. BASE (kit beta.32, stack 8073b196): each case below fails there.
"""
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "..")
ROOT = os.path.abspath(os.path.join(DIST, "..", ".."))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DIST, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fri = _load("frame_runner_install_v0654", "frame-runner-install.py")


@pytest.fixture()
def host(tmp_path, monkeypatch):
    etc, units, state = tmp_path / "etc", tmp_path / "units", tmp_path / "state"
    run = tmp_path / "run" / "theprotocol"
    for d in (etc, units, state / "frames", run / "operator"):
        d.mkdir(parents=True)
    paths = {"unit": "theprotocol-frame-runner", "config": str(etc / "frame-runner.json"), "state": str(state),
             "socket": str(run / "frame-runner.sock"), "operator_socket": str(run / "operator" / "frame-runner.sock"),
             "instance": ""}
    (run / "frame-runner.sock").write_text("")
    (run / "operator" / "frame-runner.sock").write_text("")
    monkeypatch.setattr(fri, "runner_paths", lambda root, instance: dict(paths, instance=instance))
    monkeypatch.setattr(fri.os, "geteuid", lambda: 0)
    groups = {"deploy"}
    monkeypatch.setattr(fri, "group_exists", lambda g: g in groups)
    (units / "theprotocol-frame-runner.service").write_text("[Unit]\n")
    (etc / "frame-runner.json").write_text(json.dumps({"socket_group": "deploy", "socket_group_created": True}))
    (etc / "protected-frames.list").write_text("# frames\n")
    calls = []

    def sh(argv):
        calls.append(argv)
        if argv[0] == "groupdel":
            groups.discard(argv[1])
        return subprocess.CompletedProcess(argv, 0, "", "")

    return {"tmp": tmp_path, "etc": etc, "units": units, "state": state, "run": run, "calls": calls, "sh": sh,
            "groups": groups}


def _remove(host, *, dry=False, purge=False, instance=""):
    a = argparse.Namespace(export_root=str(host["tmp"]), instance=instance, dry_run=dry, socket_group="deploy",
                           purge_state=purge)
    return fri.remove(a, sh=host["sh"], exists=lambda name: False, unit_dir=str(host["units"]),
                      protected=str(host["etc"] / "protected-frames.list"))


def test_a_second_remove_says_the_group_is_gone(host, capsys):
    assert _remove(host) == 0 and "deploy" not in host["groups"]
    capsys.readouterr()
    assert _remove(host) == 0                                    # the policy is gone now: nothing records the group
    out = capsys.readouterr().out
    assert "no group deploy on this host: nothing to keep or remove" in out
    assert "kept the group" not in out and "did not create it" not in out


def test_a_group_the_host_still_has_and_the_installer_did_not_create_stays(host, capsys):
    # control: the V0653 sentence where it is true
    (host["etc"] / "frame-runner.json").write_text(json.dumps({"socket_group": "deploy", "socket_group_created": False}))
    assert _remove(host) == 0 and "deploy" in host["groups"]
    assert "kept the group deploy: this installer did not create it" in capsys.readouterr().out


@pytest.mark.parametrize("instance,want", [("", "`frame-runner-install.py --remove --purge-state` removes it"),
                                           ("hello", "`frame-runner-install.py --remove --instance hello --purge-state` "
                                                     "removes it")], ids=["single", "instance"])
def test_the_kept_state_names_the_command_that_removes_it(host, capsys, instance, want):
    assert _remove(host, instance=instance) == 0
    out = capsys.readouterr().out
    assert want in out and "; --purge-state removes it" not in out


def test_the_runners_sockets_and_the_directories_they_leave_empty_go(host, capsys):
    assert _remove(host) == 0
    assert not host["run"].exists()                               # both sockets, operator/, then the runtime directory
    out = capsys.readouterr().out
    assert f"removed {host['run'] / 'operator' / 'frame-runner.sock'}" in out
    assert f"removed the empty directory {host['run']}" in out


def test_a_directory_that_holds_anything_else_stays(host):
    (host["run"] / "hello").mkdir()                               # another instance's runtime directory
    (host["run"] / "hello" / "frame-runner.sock").write_text("")
    assert _remove(host) == 0
    assert not (host["run"] / "frame-runner.sock").exists() and not (host["run"] / "operator").exists()
    assert (host["run"] / "hello" / "frame-runner.sock").exists()


def test_a_dry_run_says_it_and_removes_nothing(host, capsys):
    assert _remove(host, dry=True) == 0
    assert (host["run"] / "frame-runner.sock").exists() and (host["run"] / "operator" / "frame-runner.sock").exists()
    out = capsys.readouterr().out
    assert f"would remove the empty directory {host['run']}" in out


KIT_TOOLS = sorted(glob.glob(os.path.join(DIST, "frame-*.py")))


@pytest.mark.parametrize("tool", KIT_TOOLS, ids=[os.path.basename(t) for t in KIT_TOOLS])
def test_no_internal_tag_in_a_kit_tools_help(tool):
    r = subprocess.run([sys.executable, "-I", tool, "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    assert "§" not in r.stdout, [line for line in r.stdout.splitlines() if "§" in line]


def test_no_internal_tag_in_the_runners_unit_file():
    unit = open(os.path.join(ROOT, "tools", "frame-runner", "theprotocol-frame-runner.service")).read()
    rendered = fri.render_unit(unit, export_root="/opt/export", python="/usr/bin/python3", stack_root="/opt/stack")
    assert "§" not in unit and "§" not in rendered

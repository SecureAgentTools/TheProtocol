"""build_frontend.sh refuses, before it builds anything, every --out that would write into the live dashboard.

The live auditor bind-mounts Agents/TheAuditor/frontend from the stack checkout, so a file written there is a deploy of the
public dashboard. These cases run only the script's argument checks (each one exits 2 before git archive or npm), so they
need bash and git and no network; the frontend/ listing is read before and after each case and must not change.
"""
import os
import subprocess
from pathlib import Path

import pytest

AUDITOR = Path(__file__).resolve().parents[1]
SCRIPT = AUDITOR / "build_frontend.sh"
LIVE = AUDITOR / "frontend"


def _listing():
    return sorted(str(p.relative_to(LIVE)) for p in LIVE.rglob("*")) if LIVE.exists() else []


def _run(*args):
    before = _listing()
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)
    assert _listing() == before, "the script changed the live frontend/"
    return r


def test_the_script_is_there():
    assert SCRIPT.is_file()


def test_out_is_required():
    r = _run("--src", "HEAD")
    assert r.returncode == 2 and "--out" in r.stderr


@pytest.mark.parametrize("sub", ["", "assets", "assets/new-dir"])
def test_refuses_the_live_frontend_and_anything_inside_it(sub):
    target = LIVE / sub if sub else LIVE
    r = _run("--out", str(target))
    assert r.returncode == 2 and "live dashboard" in r.stderr
    assert not (LIVE / "assets" / "new-dir").exists()


def test_refuses_a_link_to_the_live_frontend(tmp_path):
    link = tmp_path / "looks-harmless"
    os.symlink(LIVE, link)
    r = _run("--out", str(link / "sub"))
    assert r.returncode == 2 and "live dashboard" in r.stderr


def test_refuses_an_out_that_is_not_empty(tmp_path):
    (tmp_path / "left-over.txt").write_text("x")
    r = _run("--out", str(tmp_path))
    assert r.returncode == 2 and "not empty" in r.stderr


def test_refuses_a_commit_that_does_not_exist(tmp_path):
    r = _run("--src", "no-such-commit-zz9", "--out", str(tmp_path / "out"))
    assert r.returncode == 2 and "not a commit" in r.stderr


# The running auditor mounts the stack checkout's frontend/, which is not the frontend/ of a worktree or a second clone the
# script may run from. From a second checkout, both the path docker inspect reports and the stack's default path are refused.
LIVE_DEFAULT = Path("/opt/theprotocol/stack/Agentvault2/Agents/TheAuditor/frontend")


def _second_checkout(tmp_path):
    repo = tmp_path / "second-checkout"
    (repo / "Agents" / "TheAuditor").mkdir(parents=True)
    (repo / "Agents" / "TheAuditor" / "build_frontend.sh").write_bytes(SCRIPT.read_bytes())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo / "Agents" / "TheAuditor" / "build_frontend.sh"


def _run_from(script, *args, env=None):
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=60,
                          env={**os.environ, **(env or {})})


def test_from_a_second_checkout_the_default_live_path_is_refused(tmp_path):
    script = _second_checkout(tmp_path)
    target = LIVE_DEFAULT / "assets" / "zz-build-test"
    existed = target.exists()
    r = _run_from(script, "--out", str(target))
    assert r.returncode == 2 and "live dashboard" in r.stderr
    assert target.exists() == existed


def test_from_a_second_checkout_the_mount_docker_reports_is_refused(tmp_path):
    script = _second_checkout(tmp_path)
    mount = tmp_path / "mounted-frontend"
    mount.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!/bin/sh\necho '{mount}'\n")
    docker.chmod(0o755)
    r = _run_from(script, "--out", str(mount / "sub"), env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    assert r.returncode == 2 and "live dashboard" in r.stderr
    assert not (mount / "sub").exists()
    # control: the same second checkout takes an --out outside every live path past the guard (it stops later, at the
    # commit check, because the second checkout has no commits)
    r = _run_from(script, "--out", str(tmp_path / "elsewhere"), env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    assert r.returncode == 2 and "not a commit" in r.stderr

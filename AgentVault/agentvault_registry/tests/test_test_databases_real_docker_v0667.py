"""V0667 follow-up (order gwo_4acc4907e6449b63de57c4de): the whole-suite database helper against a REAL docker daemon: one `up` and one `down` leave no volume behind.

The fake-docker tests (test_test_databases_helper.py) pin the commands; this one measures the thing the commands were for: the count of dangling anonymous volumes on the host
before the run and after it, with the container's own recorded mounts all gone. It starts a real postgres:18.6 (about ten seconds) and removes only what it made.

Skipped, saying why, where the docker CLI or the daemon or the image is not there (the unit-test container has no docker): a skip is not a pass.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import uuid

import pytest

HELPER = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "test_databases.py"


def _docker(*a):
    return subprocess.run(["docker", *a], capture_output=True, text=True, timeout=120)


if not shutil.which("docker"):
    pytest.skip("needs the docker CLI: it is not in this environment. Skipped, never silently passed.", allow_module_level=True)
if _docker("image", "inspect", "postgres:18.6").returncode != 0:
    pytest.skip("needs the daemon and the postgres:18.6 image on this host. Skipped, never silently passed.", allow_module_level=True)


def _dangling() -> set:
    return set(_docker("volume", "ls", "-qf", "dangling=true").stdout.split())


def test_one_real_up_and_down_leave_no_volume_behind(tmp_path):
    spec = importlib.util.spec_from_file_location("test_databases", HELPER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    name = f"tdb-real-{uuid.uuid4().hex[:8]}"
    before = _dangling()
    try:
        out = h.up(sets=1, name=name, outdir=tmp_path)
        assert len(out["volumes"]) >= 1, f"postgres:18.6 declares a VOLUME: the container carries one ({out})"
        assert all(_docker("volume", "inspect", v).returncode == 0 for v in out["volumes"]), "the recorded volumes exist while the container runs"
    finally:
        left = h.down(name)
    assert left == [], f"down had to remove {left} by name: rm -f -v missed them"
    assert all(_docker("volume", "inspect", v).returncode != 0 for v in out["volumes"]), "a volume the container carried still exists after down"
    assert _dangling() - before == set(), "down left a dangling volume on the host"


def test_a_real_container_that_up_did_not_make_is_refused_and_keeps_its_named_volume(tmp_path):
    """A mistyped name must not take a real database: an unlabelled container and its NAMED data volume survive `down` untouched."""
    spec = importlib.util.spec_from_file_location("test_databases", HELPER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    name, vol = f"tdb-real-other-{uuid.uuid4().hex[:8]}", f"tdb-real-data-{uuid.uuid4().hex[:8]}"
    try:
        assert _docker("run", "-d", "--name", name, "-v", f"{vol}:/var/lib/postgresql", "-e", "POSTGRES_PASSWORD=x", "postgres:18.6").returncode == 0
        with pytest.raises(h.NotATestDatabase):
            h.down(name)
        assert _docker("inspect", name).returncode == 0, "the unlabelled container is still there"
        assert _docker("volume", "inspect", vol).returncode == 0, "its named volume is still there"
    finally:
        _docker("rm", "-f", "-v", name)
        _docker("volume", "rm", vol)

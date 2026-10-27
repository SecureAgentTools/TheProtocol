"""A registry whose migration failed does not start (CB-193).

The operator compose ran `alembic upgrade head 2>/dev/null; operator_seed; gunicorn` and the frame template ended its
chain in an ungrouped `operator_seed || true`, which caught a failure anywhere before it: either way gunicorn served a
schema that may lack its columns, and on an operator nothing in the log said why. The registry's own command line is
run here by sh with python, alembic and gunicorn replaced by stubs that record what ran.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
SOURCES = {
    "operator compose": HERE / "nginx-templates" / "docker-compose.operator.yml",
    "frame template": ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl",
}


def _registry_command(path):
    for line in path.read_text().splitlines():
        if line.strip().startswith("command:") and "agentvault_registry.main:app" in line:
            argv = json.loads(line.split("command:", 1)[1].strip())
            assert argv[:2] == ["sh", "-c"]
            return argv[2]
    raise AssertionError(f"no registry command in {path}")


def _run(tmp_path, cmd, failing):
    """Run the chain with stubs; `failing` names the step (alembic, migration_bridge, operator_seed) that exits 1."""
    app, bin_dir, log = tmp_path / "app", tmp_path / "bin", tmp_path / "ran.log"
    app.mkdir(parents=True)
    bin_dir.mkdir()
    ready = tmp_path / "bundle.0.pem"
    ready.write_text("x")
    stub = f'#!/bin/sh\necho "$(basename "$0") $*" >> "{log}"\ncase "$*" in *{failing}*) exit 1;; esac\nexit 0\n'
    for name in ("python", "alembic", "gunicorn"):
        (bin_dir / name).write_text(stub.replace("$(basename \"$0\")", name))
        (bin_dir / name).chmod(0o755)
    cmd = (cmd.replace("/app", str(app)).replace("/tmp/prom_multiproc", str(tmp_path / "prom"))
           .replace("sh /opt/data-tls/tls-client-sync.sh &", "true &")
           .replace("/run/pgtls/client/bundle.0.pem", str(ready)).replace("{{WORKERS_REG}}", "2"))
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run(["sh", "-c", cmd], env=env, capture_output=True, text=True, timeout=30)
    return log.read_text() if log.exists() else ""


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_a_failed_migration_stops_before_gunicorn(tmp_path, source):
    if not SOURCES[source].exists():
        pytest.skip(f"{SOURCES[source]} is not beside this kit")
    cmd = _registry_command(SOURCES[source])
    assert "2>/dev/null" not in cmd.split("gunicorn")[0], "alembic's errors must reach the log"
    for failing in ("upgrade head", "migration_bridge"):
        ran = _run(tmp_path / failing.replace(" ", "_"), cmd, failing)
        assert "gunicorn" not in ran, f"{source}: gunicorn started after {failing} failed:\n{ran}"


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_seed_stays_non_fatal_and_a_clean_chain_starts(tmp_path, source):
    if not SOURCES[source].exists():
        pytest.skip(f"{SOURCES[source]} is not beside this kit")
    cmd = _registry_command(SOURCES[source])
    assert re.search(r"(?m)^gunicorn ", _run(tmp_path / "seed", cmd, "operator_seed"))
    assert re.search(r"(?m)^gunicorn ", _run(tmp_path / "clean", cmd, "nothing-fails"))

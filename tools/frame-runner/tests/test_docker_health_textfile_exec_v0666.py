"""The container-health collector must run, and its silence must alert (V0666, session-code; session-lead room seq 5047).

Measured 2026-11-16 ~23:40Z: docker-health-textfile.service failed every 30 s with 203/EXEC since 2026-11-09 14:46, so every
`docker_container_health` alert judged series frozen on that day. Three causes, each pinned here:
  1. git tracks monitoring/scripts/docker-health-textfile.sh as 100644, so the checkout of V0660 (j) rewrote it without the exec
     bit systemd needs (ExecStart runs the path itself; the older test ran it through `bash`, which cannot see that)
  2. a run that fails under `set -e` exits before its `mv` and leaves docker_health.prom.<pid> behind (100,562 of them, 4.3 GB):
     the temp file must go whatever happens, and the last good file must stay
  3. ContainerHealthMetricsStale asked node_textfile_mtime_seconds{file="docker_health.prom"} while node-exporter labels the full
     path (/host/textfile_collector/docker_health.prom), so its query was always empty and it could never fire; an empty
     selector must fire too (absent), so a wrong label can never hide a dead collector again
RED on 309a772b: the git mode is 100644, the script has no trap, the rule's selector matches nothing.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
REL = "monitoring/scripts/docker-health-textfile.sh"
SCRIPT = ROOT / REL
ALERTS = ROOT / "monitoring" / "prometheus_alerts.yml"
LABEL = "/host/textfile_collector/docker_health.prom"        # node-exporter v1.12.1's label, measured on the host


def _shim(tmp_path, ps_exit=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "ps" ]; then echo eu-registry; exit {ps_exit}; fi\n'
        'if [ "$1" = "inspect" ]; then echo "healthy|0|running|unless-stopped"; exit 0; fi\n'
        "exit 1\n")
    (bin_dir / "docker").chmod(0o755)
    out = tmp_path / "textfile"
    out.mkdir()
    return dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", OUTDIR=str(out)), out


def test_git_tracks_the_collector_as_executable():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", REL], capture_output=True, text=True, check=True)
    assert r.stdout.split()[0] == "100755", r.stdout


def test_the_collector_runs_when_executed_directly_as_systemd_does(tmp_path):
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} is not executable"
    env, out = _shim(tmp_path)
    r = subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert 'docker_container_health{name="eu-registry",state="running"} 1' in (out / "docker_health.prom").read_text()
    assert sorted(p.name for p in out.iterdir()) == ["docker_health.prom"]


def test_a_failed_run_leaves_no_temp_file_and_keeps_the_last_good_file(tmp_path):
    env, out = _shim(tmp_path, ps_exit=1)
    (out / "docker_health.prom").write_text("the last good file\n")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert sorted(p.name for p in out.iterdir()) == ["docker_health.prom"], "a temp file survived the failure"
    assert (out / "docker_health.prom").read_text() == "the last good file\n"


def _stale_rule():
    doc = yaml.safe_load(ALERTS.read_text())
    rules = [r for g in doc["groups"] for r in g["rules"] if r.get("alert") == "ContainerHealthMetricsStale"]
    assert len(rules) == 1
    return rules[0]


def test_the_stale_rule_selects_the_label_node_exporter_sets_and_nothing_else():
    expr = _stale_rule()["expr"]
    sels = re.findall(r'node_textfile_mtime_seconds\{file=~"([^"]+)"\}', expr)
    assert sels and len(set(sels)) == 1, expr
    rx = sels[0]
    assert "\\" not in rx, "a backslash in a YAML-quoted PromQL regex is an escaping trap: use [.]"
    assert re.fullmatch(rx, LABEL), (rx, LABEL)                      # PromQL regexes are anchored: fullmatch
    for other in ("/host/textfile_collector/forgejo_public_verify.prom", "/host/textfile_collector/docker_health.prom.1931314",
                  "docker_health.prom.tmp"):
        assert not re.fullmatch(rx, other), other


def test_a_selector_that_matches_nothing_fires_too():
    expr = _stale_rule()["expr"]
    assert re.search(r'\babsent\(node_textfile_mtime_seconds\{file=~"[^"]+"\}\)', expr), expr
    assert _stale_rule()["labels"]["severity"] == "warning" and _stale_rule()["for"] == "5m"     # only the selector moved

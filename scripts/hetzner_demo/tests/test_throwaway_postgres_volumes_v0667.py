"""V0667 follow-up (order gwo_4acc4907e6449b63de57c4de; the disk census of 2026-11-16 found 92 orphaned anonymous volumes, 68.6 GB, in 19 hours): a script that starts a throwaway
Postgres container removes it WITH its volumes.

postgres:16 and postgres:18.6 declare a VOLUME, so every container made from them carries an anonymous volume, and `docker rm -f NAME` leaves it behind (`--rm` does not save it:
the removal races it). `docker rm -f -v NAME` (or -fv) takes the volume with the container. The rule, over every tracked shell or python script that starts a Postgres container
(`docker run` and `postgres:` on one line): each `docker rm` in that file carries -v. The sharded suite runner calls agentvault_registry/scripts/test_databases.py down, which the
AgentVault branch fixes; the scripts below start their own.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
SKIP_DIRS = ("sessionlogs2026/", "AgentVault/", "node_modules/")
START = re.compile(r"docker\s+run\b[^\n]*\bpostgres:")
RM = re.compile(r"docker\s+rm\s+((?:-[A-Za-z-]+\s+)*)")


def _tracked_scripts():
    out = subprocess.run(["git", "ls-files", "--", "*.sh", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [p for p in out if not p.startswith(SKIP_DIRS) and "/tests/" not in p and not p.startswith("scratchpad/.")]


def _has_v(flags: str) -> bool:
    return any(tok == "--volumes" or (tok.startswith("-") and not tok.startswith("--") and "v" in tok[1:]) for tok in flags.split())


def offenders():
    bad = []
    for rel in _tracked_scripts():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not START.search(text):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in RM.finditer(line):
                if not _has_v(m.group(1)):
                    bad.append(f"{rel}:{n}: {line.strip()[:120]}")
    return bad


def test_every_script_that_starts_a_throwaway_postgres_removes_it_with_its_volumes():
    bad = offenders()
    assert not bad, "docker rm without -v leaves the image's anonymous volume (~2 GB a run):\n" + "\n".join(bad)


def test_the_rule_reads_the_flags_the_way_docker_does():
    assert _has_v("-fv ") and _has_v("-f -v ") and _has_v("-vf ") and _has_v("--force --volumes ")
    assert not _has_v("-f ") and not _has_v("") and not _has_v("--force ")
    assert RM.search('docker rm -f "$PG" >/dev/null').group(1) == "-f "
    assert START.search("docker run -d --rm --name x postgres:16-alpine") and not START.search("docker run --rm python:3.14 pytest")

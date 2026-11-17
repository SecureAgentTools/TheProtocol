#!/usr/bin/env python3
"""The whole-suite database helper (V0666, order gwo_f8c2c213092640ead451a723; found by session-volume, room seq 4959).

Why. Real-Postgres test files skip when their `*_TEST_DB` variable is unset ("Skipped, never silently passed"), so an ordinary
whole-suite run counts them as skipped and nobody sees one fail: the two orgs v2 mirror tests failed on a real Postgres for a long
time for exactly that reason. This helper makes every one of them RUN in a whole-suite line, on production's Postgres, and
`tests/test_test_databases_helper.py` fails when a test reads a `*_TEST_DB` variable this file does not know (KNOWN below), so a
new one cannot hide the same way.

What it does. ONE throwaway Postgres container (postgres:18.6, production's image; `--max-connections 400`) on its own docker
network, a database for EVERY variable in KNOWN for EVERY set (a set is one shard of the sharded suite: the tests DROP SCHEMA
public, so two shards must never share a database), and one env file per set (`<outdir>/set<i>.env`, mode 600, lines of
`VAR=postgresql+asyncpg://...`). The password is generated here, written only into those files and handed to docker as an
environment value: it is in no output of this script.

  python3 scripts/test_databases.py up   [--sets N] [--name NAME] [--outdir DIR]   start, create, write the env files
  python3 scripts/test_databases.py down [--name NAME]                              remove the container and its network
  python3 scripts/test_databases.py check [--tests DIR]                             exit 1 naming any variable not in KNOWN

A shard's container joins the network `<name>-net` and takes `--env-file <outdir>/set<i>.env`
(scratchpad/suites1018/registry_suite_sharded_db.sh does exactly that).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import secrets
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional

IMAGE = "postgres:18.6"                      # production's Postgres
USER = "postgres"
DEFAULT_NAME = "suite-test-databases"
LABEL = "theprotocol.test-databases"          # up puts it on the container and its network (value 1); down touches nothing without it
_ANONYMOUS_VOLUME = re.compile(r"^[0-9a-f]{64}$")   # the name docker gives an anonymous volume: a NAMED volume (real data) is never one


class NotATestDatabase(RuntimeError):
    """down was asked to remove a container that up did not make: nothing was touched."""

# Every `*_TEST_DB` variable a test reads (or an unmerged branch's test reads: FLARE_WEAR_TEST_DB, CODE_CHANGES_TEST_DB), and the
# stem of the database made for it. ORGS_TEST_PEER_DB is the peer half of the orgs mirror test: a second database.
KNOWN: Dict[str, str] = {
    "MEMBERSHIP_TEST_DB": "membership",
    "OWNER_READS_TEST_DB": "owner_reads",
    "ORGS_TEST_DB": "orgs_home",
    "ORGS_TEST_PEER_DB": "orgs_peer",
    "FIRMS_TEST_DB": "firms",
    "DISPUTES_TEST_DB": "disputes",
    "ANCHOR_TEST_DB": "anchor",
    "CODE_DISTRIBUTIONS_TEST_DB": "code_distributions",
    "CODE_CHANGES_TEST_DB": "code_changes",
    "FLARE_WEAR_TEST_DB": "flare_wear",
    "OPA_VERIFIER_TEST_DB": "opa_verifier",
    "REPO_ACCOUNTS_TEST_DB": "repo_accounts",
    "CODE_PASSPORT_TEST_DB": "code_passport",
    "CODE_PASSPORT_HOME_TEST_DB": "code_passport_home",
    "DISTRIBUTION_RELEASES_TEST_DB": "distribution_releases",   # V0667 D6 part 3, the scoped release channel
}

_VAR = re.compile(r"\b([A-Z][A-Z0-9_]*_TEST(?:_PEER)?_DB)\b")


def scan(root: pathlib.Path) -> Dict[str, List[str]]:
    """{variable: [files]} for every `*_TEST_DB` name mentioned in a test file under `root` (a mention counts: a name in a docstring
    is a name someone will set)."""
    found: Dict[str, List[str]] = {}
    for p in sorted(pathlib.Path(root).rglob("*.py")):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for v in set(_VAR.findall(text)):
            found.setdefault(v, []).append(str(p.name))
    return found


def unknown_variables(found: Dict[str, List[str]]) -> List[str]:
    return sorted(v for v in found if v not in KNOWN)


def database_name(var: str, set_index: int) -> str:
    return f"test_{KNOWN[var]}_s{set_index}"          # test_: some tests drop their public schema only on a name that starts so


def env_lines(set_index: int, user: str, password: str, host: str, port: int = 5432) -> List[str]:
    return [f"{v}=postgresql+asyncpg://{user}:{password}@{host}:{port}/{database_name(v, set_index)}" for v in KNOWN]


Docker = Callable[..., "subprocess.CompletedProcess[str]"]


def _docker(args: List[str], **kw) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True, **kw)


def up(sets: int, name: str, outdir: pathlib.Path, docker: Docker = _docker, sleep: Callable[[float], None] = time.sleep,
       attempts: int = 60) -> Dict[str, object]:
    """Start the server, wait for it, create every database of every set, write one private env file per set."""
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    password = secrets.token_hex(16)
    net = f"{name}-net"
    docker(["docker", "network", "create", "--label", f"{LABEL}=1", net])
    r = docker(["docker", "run", "-d", "--name", name, "--label", f"{LABEL}=1", "--network", net, "-e", f"POSTGRES_PASSWORD={password}", IMAGE,
                "-c", "max_connections=400", "-c", "fsync=off", "-c", "synchronous_commit=off"])
    if getattr(r, "returncode", 0) != 0:
        raise RuntimeError(f"could not start {IMAGE} as {name}: {(getattr(r, 'stderr', '') or '')[:200]}")
    for _ in range(attempts):
        if docker(["docker", "exec", name, "pg_isready", "-U", USER]).returncode == 0:
            break
        sleep(1)
    else:
        raise RuntimeError(f"the Postgres in {name} did not answer in {attempts} tries")
    sleep(1)                                   # pg_isready answers during the image's own init restart: let it settle
    stmts: List[str] = []
    for i in range(sets):
        for v in KNOWN:
            stmts += ["-c", f"CREATE DATABASE {database_name(v, i)}"]
    r = docker(["docker", "exec", name, "psql", "-U", USER, "-v", "ON_ERROR_STOP=1", *stmts])
    if getattr(r, "returncode", 0) != 0:
        raise RuntimeError(f"creating the databases failed: {(getattr(r, 'stderr', '') or '')[:300]}")
    for i in range(sets):
        f = outdir / f"set{i}.env"
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(env_lines(i, USER, password, name)) + "\n")
        os.chmod(f, 0o600)
    return {"container": name, "network": net, "sets": sets, "outdir": str(outdir), "variables": len(KNOWN), "image": IMAGE, "volumes": container_volumes(name, docker)}


def container_volumes(name: str, docker: Docker = _docker) -> List[str]:
    """The names of the volumes the container carries (postgres:18.6 declares a VOLUME, so there is one anonymous volume per container)."""
    r = docker(["docker", "inspect", name, "--format", "{{range .Mounts}}{{.Name}} {{end}}"])
    return r.stdout.split() if getattr(r, "returncode", 1) == 0 and isinstance(getattr(r, "stdout", None), str) else []


def _label(kind: str, name: str, docker: Docker) -> Optional[str]:
    """The LABEL value of a container or network, "" when it has none, None when there is no such object."""
    path = ".Config.Labels" if kind == "container" else ".Labels"
    r = docker(["docker", kind, "inspect", name, "--format", f'{{{{index {path} "{LABEL}"}}}}'] if kind == "network" else
               ["docker", "inspect", name, "--format", f'{{{{index {path} "{LABEL}"}}}}'])
    if getattr(r, "returncode", 1) != 0:
        return None
    return (r.stdout or "").strip() if isinstance(getattr(r, "stdout", None), str) else ""


def down(name: str, docker: Docker = _docker) -> List[str]:
    """Remove the container WITH its anonymous volumes (`rm -f -v`), then its network. `docker rm -f NAME` leaves the image's anonymous volume behind: ~2 GB a run,
    92 of them (68.6 GB) in 19 hours (the disk census of 2026-11-16). The volumes the container carried are read first; any ANONYMOUS one (a 64-hex name) that survives is
    removed by name and returned, so the caller can say so; a named volume is never touched. [] means nothing was left.

    Only what `up` made: a container without the label (a real database, a mistyped name) is refused with NotATestDatabase and nothing is touched, and so is a network without it."""
    have = _label("container", name, docker)
    if have is not None and have != "1":
        raise NotATestDatabase(f"{name} is not a test-databases container (it has no {LABEL}=1 label): nothing was removed")
    mounts = [v for v in container_volumes(name, docker) if _ANONYMOUS_VOLUME.match(v)] if have is not None else []
    if have is not None:
        docker(["docker", "rm", "-f", "-v", name])
    if _label("network", f"{name}-net", docker) == "1":
        docker(["docker", "network", "rm", f"{name}-net"])
    left = []
    for v in mounts:
        if getattr(docker(["docker", "volume", "inspect", v]), "returncode", 1) == 0:
            docker(["docker", "volume", "rm", v])
            left.append(v)
    return left


def main(argv: Optional[List[str]] = None, docker: Docker = _docker) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("up")
    u.add_argument("--sets", type=int, default=6)
    u.add_argument("--name", default=DEFAULT_NAME)
    u.add_argument("--outdir", default=os.path.join(os.getcwd(), ".test-databases"))
    d = sub.add_parser("down")
    d.add_argument("--name", default=DEFAULT_NAME)
    c = sub.add_parser("check")
    c.add_argument("--tests", default=str(pathlib.Path(__file__).resolve().parent.parent / "tests"))
    a = ap.parse_args(argv)
    if a.cmd == "up":
        info = up(a.sets, a.name, pathlib.Path(a.outdir))
        print(" ".join(f"{k}={v}" for k, v in info.items()))
        return 0
    if a.cmd == "down":
        try:
            left = down(a.name, docker)
        except NotATestDatabase as e:
            print(str(e), file=sys.stderr)
            return 3
        if left:
            print(f"removed {len(left)} volume(s) the container's removal left behind", file=sys.stderr)
        return 0
    found = scan(pathlib.Path(a.tests))
    bad = unknown_variables(found)
    if bad:
        print("unknown *_TEST_DB variables (add them to KNOWN): " + ", ".join(f"{v} in {found[v][0]}" for v in bad))
        return 1
    print(f"{len(found)} *_TEST_DB variables read by the tests, all known")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shell-out to `docker` and `docker compose`.

The CLI deliberately uses the docker binary rather than the Docker SDK
(per Operator_CLI_Strategy.md §4.10: smaller binary, fewer Python deps).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import OperatorContext


KNOWN_SERVICES = [
    "registry", "teg-layer", "db", "teg-db", "redis", "pgbouncer",
    "nginx-federation", "spire-agent", "cert-writer",
]


def _compose_cmd(ctx: OperatorContext, *args: str) -> List[str]:
    """Build a `docker compose ...` invocation with the right project dir / env."""
    return [
        "docker", "compose",
        "--project-directory", str(ctx.dir),
        "-f", str(ctx.compose_file),
        "--env-file", str(ctx.env_path),
        *args,
    ]


def run(
    cmd: List[str],
    *,
    capture: bool = True,
    timeout: int = 60,
    check: bool = False,
    input: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """`input` is written to the command's stdin (a value that must not appear in the process arguments); env: values
    laid over this process's environment (compose interpolates a shell variable before --env-file)."""
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
        input=input,
        env={**os.environ, **env} if env else None,
    )


def compose_ps_json(ctx: OperatorContext) -> List[Dict[str, str]]:
    """Return list of {Service, Name, State, Health, Status, Image}."""
    r = run(_compose_cmd(ctx, "ps", "--format", "json"), timeout=30)
    if r.returncode != 0:
        return []
    out: List[Dict[str, str]] = []
    # docker compose ps --format json emits one JSON object per line
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def container_details(names: List[str]) -> Dict[str, Dict[str, str]]:
    """{container: {started_at, restart_count}} in ONE `docker inspect` (status --detail); a container docker cannot
    inspect is simply absent."""
    if not names:
        return {}
    r = run(["docker", "inspect", "--format", "{{.Name}}\t{{.State.StartedAt}}\t{{.RestartCount}}", *names], timeout=30)
    out: Dict[str, Dict[str, str]] = {}
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            out[parts[0].lstrip("/")] = {"started_at": parts[1], "restart_count": parts[2]}
    return out


def compose_logs(
    ctx: OperatorContext,
    service: str,
    *,
    tail: int = 100,
    follow: bool = False,
    since: Optional[str] = None,
) -> int:
    cmd = _compose_cmd(ctx, "logs", "--tail", str(tail))
    if since:
        cmd += ["--since", since]
    if follow:
        cmd += ["-f"]
    cmd += [service]
    # logs goes straight to stdout/stderr — no capture
    return subprocess.call(cmd)


def compose_restart(
    ctx: OperatorContext,
    service: Optional[str],
    *,
    force_recreate: bool = False,
) -> Tuple[int, str]:
    if force_recreate and service:
        # apply env changes to ONE service: --no-deps, or compose also recreates everything it depends on (the
        # registry's databases, Redis, pgbouncer: the recreate nobody asked for, CB-226); a recreate never builds
        cmd = _compose_cmd(ctx, "up", "-d", "--no-deps", "--no-build", "--force-recreate")
    elif force_recreate:
        # the whole stack: every service is named anyway, in dependency order
        cmd = _compose_cmd(ctx, "up", "-d", "--force-recreate")
    else:
        cmd = _compose_cmd(ctx, "restart")
    if service:
        cmd += [service]
    r = run(cmd, timeout=120)
    return r.returncode, (r.stdout + r.stderr)[:2000]


def wait_healthy(ctx: OperatorContext, service: Optional[str] = None, *, timeout_s: int = 120,
                 interval_s: float = 3.0) -> bool:
    """Poll `compose ps` until the service (every service when None) is running and healthy, or running with no
    healthcheck. False when the deadline passes first."""
    deadline = time.monotonic() + timeout_s
    while True:
        svcs = [s for s in compose_ps_json(ctx) if service is None or s.get("Service") == service]
        if svcs and all((s.get("State") or "").lower() == "running"
                        and (s.get("Health") or "").lower() in ("healthy", "", "none") for s in svcs):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)


def compose_up(ctx: OperatorContext) -> Tuple[int, str]:
    r = run(_compose_cmd(ctx, "up", "-d"), timeout=180)
    return r.returncode, (r.stdout + r.stderr)[:2000]


def compose_down(ctx: OperatorContext) -> Tuple[int, str]:
    r = run(_compose_cmd(ctx, "down"), timeout=120)
    return r.returncode, (r.stdout + r.stderr)[:2000]


def compose_pull(ctx: OperatorContext, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    r = run(_compose_cmd(ctx, "pull"), timeout=600, env=env)
    return r.returncode, (r.stdout + r.stderr)[:2000]


def docker_info_ok() -> bool:
    """Quick sanity check that `docker` is reachable."""
    r = run(["docker", "info"], timeout=10)
    return r.returncode == 0


def compose_exec(
    ctx: OperatorContext,
    service: str,
    *args: str,
    timeout: int = 120,
    input: Optional[str] = None,
) -> subprocess.CompletedProcess:
    return run(_compose_cmd(ctx, "exec", "-T", service, *args), timeout=timeout, input=input)

"""§OPDIST (2026-09-16) — every host an operator service dials for its database or Redis is a HEALTHY dependency.

Measured on beacon/jelgava's V0391 re-provision: teg-layer's DATABASE_URL is pgbouncer:6432/teg_layer, and its
depends_on named only teg-db. With the db-TLS override the registry database waits for its certificate, pgbouncer (which
waits for that database) starts later, and the TEG crash-looped on "could not translate host name pgbouncer" until
compose gave up. The race was always in the base; a slower dependency only exposed it.

A dial a dependency cannot express is a CYCLE and is named, never silently skipped: the TEG dials the registry, which
depends on the TEG.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = ROOT / "scripts" / "distribution" / "nginx-templates" / "docker-compose.operator.yml"
DIAL_KEYS = ("DATABASE_URL", "DATABASE_URL_SYNC", "REDIS_URL")
CYCLES = {("teg-layer", "registry")}   # registry depends on teg-layer healthy


def _env(svc):
    env = svc.get("environment") or {}
    return env.items() if isinstance(env, dict) else [tuple(str(e).split("=", 1)) for e in env]


def test_every_database_or_redis_host_a_service_dials_is_a_healthy_dependency():
    d = yaml.safe_load(BASE.read_text())
    services = d["services"]
    checked, missing = 0, []
    for name, svc in services.items():
        deps = svc.get("depends_on") or {}
        deps = deps if isinstance(deps, dict) else {k: {} for k in deps}
        for key, value in _env(svc):
            if key not in DIAL_KEYS:
                continue
            m = re.search(r"://(?:[^@/]*@)?([a-z][a-z0-9-]*)", str(value))
            host = m.group(1) if m else None
            if host not in services or host == name or (name, host) in CYCLES:
                continue
            checked += 1
            if (deps.get(host) or {}).get("condition") != "service_healthy":
                missing.append(f"{name}.{key} dials {host} without depends_on {host}: service_healthy")
    assert checked >= 4, f"only {checked} dials were checked; the parser is not reading this compose"
    assert not missing, missing

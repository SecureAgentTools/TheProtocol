"""§FRAMEKIT P3.1 (2026-09-12) — ONE reader for where this registry reads Prometheus.

Twelve routers each read PROMETHEUS_URL with their own literal default — eleven `agentvault-prometheus:9090`
(the container name) and the public status page `prometheus:9090` (the compose alias), which resolves on
Frame A's network and nowhere else. The flagship's status page showed 0 of 90 days on every component
partly for that reason. An EMPTY value is treated as unset (an env_file line `PROMETHEUS_URL=` must never
become a dial of ""); the standup driver writes the real value from sidecars/sidecars.json.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

DEFAULT_PROMETHEUS_URL = "http://agentvault-prometheus:9090"


def prometheus_url() -> str:
    return (os.getenv("PROMETHEUS_URL", "") or "").strip().rstrip("/") or DEFAULT_PROMETHEUS_URL


DEFAULT_GRAFANA_URL = "http://grafana:3000"


def grafana_url() -> str:
    """§DOCSFIX D6-251 (2026-10-16): the same rule for Grafana (GRAFANA_URL; empty is unset), for adminGrafanaQuery,
    which read an undeclared setting through getattr and so always dialed its default."""
    return (os.getenv("GRAFANA_URL", "") or "").strip().rstrip("/") or DEFAULT_GRAFANA_URL


# V0664 (gwo_94d297dfb0fc293483ad1632): a frame's Grafana listens only on a unix socket. GRAFANA_URL may name one,
# unix:///run/grafana/grafana.sock or unix:/run/grafana/grafana.sock; the request then goes through that socket to
# this fixed base (Grafana reads the path, the host is only a name).
GRAFANA_SOCKET_BASE = "http://grafana"


def grafana_target(value: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Where adminGrafanaQuery sends a request: (base URL, unix socket path or None). A `unix:` value gives the socket
    path ("" when it names none, which the tool says) and GRAFANA_SOCKET_BASE; anything else is grafana_url()'s rule."""
    raw = (os.getenv("GRAFANA_URL", "") if value is None else value) or ""
    raw = raw.strip()
    if raw.lower().startswith("unix:"):
        path = raw[len("unix:"):]
        if path.startswith("//"):
            path = path[2:]
        return GRAFANA_SOCKET_BASE, path
    return (raw.rstrip("/") or DEFAULT_GRAFANA_URL), None

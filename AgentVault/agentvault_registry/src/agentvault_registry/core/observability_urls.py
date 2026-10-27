"""§FRAMEKIT P3.1 (2026-09-12) — ONE reader for where this registry reads Prometheus.

Twelve routers each read PROMETHEUS_URL with their own literal default — eleven `agentvault-prometheus:9090`
(the container name) and the public status page `prometheus:9090` (the compose alias), which resolves on
Frame A's network and nowhere else. The flagship's status page showed 0 of 90 days on every component
partly for that reason. An EMPTY value is treated as unset (an env_file line `PROMETHEUS_URL=` must never
become a dial of ""); the standup driver writes the real value from sidecars/sidecars.json.
"""
from __future__ import annotations

import os

DEFAULT_PROMETHEUS_URL = "http://agentvault-prometheus:9090"


def prometheus_url() -> str:
    return (os.getenv("PROMETHEUS_URL", "") or "").strip().rstrip("/") or DEFAULT_PROMETHEUS_URL


DEFAULT_GRAFANA_URL = "http://grafana:3000"


def grafana_url() -> str:
    """§DOCSFIX D6-251 (2026-10-16): the same rule for Grafana (GRAFANA_URL; empty is unset), for adminGrafanaQuery,
    which read an undeclared setting through getattr and so always dialed its default."""
    return (os.getenv("GRAFANA_URL", "") or "").strip().rstrip("/") or DEFAULT_GRAFANA_URL

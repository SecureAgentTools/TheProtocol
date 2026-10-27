"""Gunicorn config for the AgentVault registry.

Replaces uvicorn's self-supervisor -- which SIGKILLs any worker that misses a
HARDCODED 5s liveness ping, false-killing healthy-but-CPU-starved workers under
load -> cold-respawn storm = the 2026-06-09 registry-a crash (CPU 782%, /health
000) -- with gunicorn's arbiter: a worker is killed only if a SINGLE request
exceeds the CONFIGURABLE `timeout` (default 60s), and the Uvicorn worker
heartbeats via an event-loop callback (not a daemon thread that needs OS
scheduling). Net effect: a busy box degrades to "slow" instead of crash-looping.

Worker COUNT stays on the CLI (`--workers N`) per deployment -- unchanged
(registry-a 38 / frame-b,c 32 / cloud-ops 8). Everything here is env-overridable
so it can be retuned live without an image rebuild. NOTHING financial is touched.

Launch: PYTHONPATH=/app/src gunicorn agentvault_registry.main:app --workers N -c /app/gunicorn_conf.py
"""
import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── bind / worker model ──────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
worker_class = "agentvault_registry.gunicorn_worker.RegistryWorker"

# ── the fix: kill a worker only if ONE request exceeds this (vs uvicorn's 5s) ──
timeout = _int_env("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GUNICORN_KEEPALIVE", 10)

# ── optional worker recycling (gunicorn JITTERS it -> no synchronized restart).
#    Off by default; set GUNICORN_MAX_REQUESTS > 0 to enable. ───────────────────
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 0)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 0)

# ── proxy headers (replaces uvicorn --proxy-headers --forwarded-allow-ips '*').
#    Also forced in RegistryWorker.CONFIG_KWARGS; set here too for gunicorn-level
#    access logging / belt-and-suspenders. ─────────────────────────────────────
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")
proxy_allow_ips = os.getenv("PROXY_ALLOW_IPS", "*")

# ── CRITICAL: never preload. The app builds asyncpg pools / SSL contexts / the
#    event loop PER WORKER at startup; preload_app=True would fork those from the
#    master and corrupt them (the same fork-safety reason uvicorn used spawn). ──
preload_app = False

loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")

# Access logging -> stdout (parity with the prior uvicorn setup, which emitted access
# lines). Under UvicornWorker the "uvicorn.access" logger inherits gunicorn's access-log
# handlers, so setting `accesslog` is what makes access lines appear -- with the
# proxy-corrected client IP from X-Forwarded-For. "-" = stdout; GUNICORN_ACCESSLOG="" mutes.
accesslog = os.getenv("GUNICORN_ACCESSLOG", "-") or None


def post_fork(server, worker):
    """§RELEASEHARDEN D2 (2026-09-14) — mask query-string credentials in every access line this worker
    writes. The uvicorn worker replaces the `uvicorn.access` / `uvicorn.error` loggers' HANDLERS with
    gunicorn's, so the mask lives on the LOGGER (a filter), which survives that swap; main.py installs the
    same filter at app import, and the install is idempotent, so a bare uvicorn launch is covered too."""
    try:
        from agentvault_registry.core.access_log_mask import install_access_log_mask
        install_access_log_mask()
    except Exception as exc:  # noqa: BLE001 — a missing mask must not stop a worker from serving
        server.log.warning("access-log mask not installed in worker %s: %s", worker.pid, exc)


def child_exit(server, worker):
    """Clean up a dead worker's Prometheus multiprocess metric files so /metrics
    stays correct across recycles. (uvicorn's supervisor never did this either,
    but gunicorn recycling/timeouts make dead-worker cleanup matter.)"""
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:
        pass

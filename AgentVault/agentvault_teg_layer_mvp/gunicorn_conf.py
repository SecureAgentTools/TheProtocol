"""Gunicorn config for the TEG Layer (token exchange gateway).

Replaces uvicorn's self-supervisor -- which SIGKILLs any worker that misses a
HARDCODED 5s liveness ping, false-killing healthy-but-CPU-starved workers under
load -> cold-respawn storm (the same mechanism that crash-looped registry-a on
2026-06-09, fixed there in V0041) -- with gunicorn's arbiter: a worker is killed
only if a SINGLE request exceeds the CONFIGURABLE `timeout` (default 60s), and the
Uvicorn worker heartbeats via an event-loop callback (not an OS-scheduled daemon
thread). On the MONEY layer this matters more than on the registry: a SIGKILL at
5s can land mid-2PC, orphaning a prepared cross-TEG leg or leaving a lock; the
`graceful_timeout` below instead lets an in-flight settlement drain.

Worker COUNT stays on the CLI (`--workers N`) per deployment -- unchanged
(teg-layer-a 9 / frame-b,c + cloud-ops 8). Everything here is env-overridable so it
can be retuned live without an image rebuild. NOTHING financial is touched -- this
only swaps the process supervisor; the ASGI app, transfer logic, 2PC coordination
and emission gating are byte-identical.

Unlike the registry (which subclasses UvicornWorker to FORCE proxy_headers for
slowapi/admission per-client-IP keying), the TEG is reached server-to-server behind
its nginx-teg mTLS sidecar and keys on no forwarded headers -- so we use the STOCK
`uvicorn_worker.UvicornWorker`, leaving proxy-header handling identical to the prior
`uvicorn ...` (no --proxy-headers) invocation.

Launch: cd /app && gunicorn src.teg_core_service.main:app --workers N -c /app/gunicorn_conf.py
"""
import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── bind / worker model ──────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8080")
worker_class = "uvicorn_worker.UvicornWorker"

# ── the fix: kill a worker only if ONE request exceeds this (vs uvicorn's 5s) ──
timeout = _int_env("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GUNICORN_KEEPALIVE", 10)

# ── optional worker recycling (gunicorn JITTERS it -> no synchronized restart).
#    Off by default; set GUNICORN_MAX_REQUESTS > 0 to enable. ───────────────────
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 0)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 0)

# ── CRITICAL: never preload. Each worker builds its own asyncpg pools / SSL
#    contexts / event loop at startup; preload_app=True would fork those from the
#    master and corrupt them (the same fork-safety reason uvicorn used spawn). ──
preload_app = False

loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")

# Access logging -> stdout (parity with the prior uvicorn setup). Under
# UvicornWorker the "uvicorn.access" logger inherits gunicorn's access-log
# handlers, so setting `accesslog` is what makes access lines appear. "-" = stdout;
# GUNICORN_ACCESSLOG="" mutes.
accesslog = os.getenv("GUNICORN_ACCESSLOG", "-") or None


def child_exit(server, worker):
    """Clean up a dead worker's Prometheus multiprocess metric files so /metrics
    stays correct across recycles. No-op (guarded) if multiprocess mode is off."""
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:
        pass

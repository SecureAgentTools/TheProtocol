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


def _metrics_multiproc():
    """V0657 (c): the TEG's copy of the registry's metrics module (src/teg_core_service/core/metrics_multiproc.py,
    byte for byte), loaded by its path: this file runs in the arbiter whether the app is imported as
    src.teg_core_service (the composes) or as teg_core_service (PYTHONPATH=/app/src). Registered in sys.modules
    before it runs, as a module with a dataclass must be."""
    import importlib.util
    import sys
    name = "teg_gunicorn_metrics_multiproc"
    mod = sys.modules.get(name)
    if mod is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "src", "teg_core_service", "core", "metrics_multiproc.py")
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return mod


def on_starting(server):
    """V0657 (c): the metrics directory starts empty. prometheus_client requires it to be wiped between runs, and a
    directory that outlives a run (anything but a fresh tmpfs) would hand the new workers the old values of whatever
    pids they are given. A re-exec'd master (USR2, GUNICORN_PID set) skips it: the old master's workers still write
    there."""
    if getattr(server, "master_pid", 0):
        return
    try:
        mm = _metrics_multiproc()
        path = mm.multiproc_dir()
        n = mm.wipe(path)
        if n:
            server.log.info("metrics: %d value files an earlier run left in %s removed", n, path)
    except Exception as exc:  # noqa: BLE001 - a directory not wiped must not stop the TEG from starting
        server.log.warning("metrics: the metrics directory was not wiped at start: %s", exc)


def child_exit(server, worker):
    """A dead worker's Prometheus files. mark_process_dead removes its live gauges; V0657 (c) folds the rest (counters,
    histograms, summaries, the other gauges) into one archive per kind and removes them, so a worker's death no longer
    leaves a worker's worth of files in the 16 MB tmpfs (the registry's twin wedged sbx-alpha for 11 h, 2026-11-06).
    No-op if multiprocess mode is off."""
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:
        pass
    try:
        mm = _metrics_multiproc()
        rep = mm.fold_dead_workers(mm.multiproc_dir(), live_pids=list(server.WORKERS))
        if rep.lost or rep.busy:
            server.log.warning("metrics: worker %s exited; its value files: %s", worker.pid, rep.line())
        elif rep:
            server.log.info("metrics: worker %s exited; its value files: %s", worker.pid, rep.line())
    except Exception as exc:  # noqa: BLE001 - the arbiter goes on; the next worker exit folds what this one did not
        server.log.warning("metrics: worker %s exited; its value files were not folded: %s", worker.pid, exc)

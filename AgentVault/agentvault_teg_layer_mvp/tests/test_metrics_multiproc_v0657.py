"""V0657 (c), session-code, 2026-11-06: the TEG's twin of the registry's metrics fix.

The TEG runs the registry's arbiter hook (child_exit -> mark_process_dead, which removes only a dead worker's live
gauges) on the same 16 MB tmpfs, so a worker's death left its counter and histogram files there for good; sbx-alpha's
registry was wedged 11 hours by exactly that (session-watch, room seq 1407 and 1493). The module is the registry's file,
byte for byte (the registry's tests/test_metrics_multiproc_v0657.py refuses a copy that differs); these tests run the
TEG's own hooks (gunicorn_conf.py, which loads that copy by its path) and the TEG app's /metrics.
RED on origin/v0656/cut (9715878984): child_exit leaves the dead worker's files, on_starting does not exist, and
/metrics has no fill gauge.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve()
_WORKER = r"""
import os, sys
os.environ["PROMETHEUS_MULTIPROC_DIR"] = sys.argv[1]
from prometheus_client import Counter, Gauge, Histogram
Counter("t_moves", "moves", ["kind"], registry=None).labels(kind="transfer").inc(int(sys.argv[2]))
Histogram("t_move_seconds", "move latency", buckets=(0.1, 1.0), registry=None).observe(0.5)
Gauge("t_backlog", "backlog", multiprocess_mode="max", registry=None).set(int(sys.argv[2]))
Gauge("t_alive", "alive", multiprocess_mode="livesum", registry=None).set(1)
"""


def _conf():
    spec = importlib.util.spec_from_file_location("teg_gunicorn_conf_v0657", _HERE.parents[1] / "gunicorn_conf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a)

    def warning(self, msg, *a):
        self.lines.append(msg % a)


def _dead_worker(d, n):
    p = subprocess.run([sys.executable, "-c", _WORKER, str(d), str(n)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr


def _db(d):
    return sorted(f for f in os.listdir(d) if f.endswith(".db"))


def test_dead_workers_leave_one_archive_per_kind(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
    conf = _conf()
    for n in range(1, 7):
        _dead_worker(d, n)
        pid = next(int(f[8:-3]) for f in _db(d) if f.startswith("counter_") and f[8:-3].isdigit())
        conf.child_exit(types.SimpleNamespace(WORKERS={}, log=_Log()), types.SimpleNamespace(pid=pid))
    assert _db(d) == ["counter_archive.db", "gauge_max_archive.db", "histogram_archive.db"]
    from prometheus_client.multiprocess import MultiProcessCollector
    got = {(s.name, tuple(sorted(s.labels.items()))): s.value
           for m in MultiProcessCollector.merge([os.path.join(d, f) for f in _db(d)]) for s in m.samples}
    assert got[("t_moves_total", (("kind", "transfer"),))] == 21.0          # 1 + ... + 6: nothing lost, nothing twice
    assert got[("t_backlog", ())] == 6.0 and got[("t_move_seconds_count", ())] == 6.0


def test_the_arbiters_start_wipes_an_earlier_run(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
    _dead_worker(d, 1)
    conf = _conf()
    conf.on_starting(types.SimpleNamespace(master_pid=99, log=_Log()))     # a USR2 re-exec leaves the directory alone
    assert len(_db(d)) == 4
    conf.on_starting(types.SimpleNamespace(master_pid=0, log=_Log()))
    assert _db(d) == []


async def test_metrics_reads_every_workers_files_and_says_how_full_the_directory_is(tmp_path, monkeypatch):
    from teg_core_service.main import app
    d, warm = str(tmp_path / "dir"), str(tmp_path / "warm")
    os.makedirs(d)
    os.makedirs(warm)
    _dead_worker(d, 3)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teg-layer") as c:
        # the app's own metrics open their files on first use, in whatever directory is set then: not the one measured
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", warm)
        await c.get("/metrics")
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
        files = len(_db(d))
        r = await c.get("/metrics")
    assert r.status_code == 200, r.text
    assert 't_moves_total{kind="transfer"} 3.0' in r.text
    assert f"prometheus_multiproc_dir_files {float(files)}" in r.text, "the directory's fill is reported"

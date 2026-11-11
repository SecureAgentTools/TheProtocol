"""V0657 (c), session-code, 2026-11-06: a worker's death no longer leaves its metrics files in PROMETHEUS_MULTIPROC_DIR.

sbx-alpha's registry was wedged for 11 hours: its 16 MB metrics tmpfs held 212,109 counter files against 36 gauge_all
and 18 gauge_max (session-watch, room seq 1407 and 1493), because child_exit's mark_process_dead removes only a dead
worker's live gauges. Full, every new worker died of SIGBUS at its first write, about 230 times a minute.

The workers here are real processes (prometheus_client in a subprocess, its files named for its pid, then it exits), and
the hooks are the arbiter's own (gunicorn_conf.child_exit / on_starting) and the real app's /metrics.
RED on origin/v0656/cut (9715878984): child_exit leaves every dead worker's counter and histogram files (the fold, the
twelve deaths and the full directory fail on that), on_starting does not exist, and /metrics has no fill gauge.
"""
from __future__ import annotations

import errno
import glob
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve()
_CORE = _HERE.parents[1] / "src" / "agentvault_registry" / "core" / "metrics_multiproc.py"
# the TEG's copy, where an AgentVault checkout keeps it (CI links the TEG source there, beside the registry tree)
_TEG_COPY = _HERE.parents[2] / "agentvault_teg_layer_mvp" / "src" / "teg_core_service" / "core" / "metrics_multiproc.py"

_WORKER = r"""
import os, sys
os.environ["PROMETHEUS_MULTIPROC_DIR"] = sys.argv[1]
from prometheus_client import Counter, Gauge, Histogram, Summary
n = int(sys.argv[2])
Counter("t_requests", "requests", ["route"], registry=None).labels(route="/a").inc(n)
Counter("t_requests", "requests", ["route"], registry=None).labels(route="/only%d" % n).inc(1)
h = Histogram("t_latency_seconds", "latency", buckets=(0.1, 1.0), registry=None)
h.observe(0.05 * n); h.observe(2)
Summary("t_size_bytes", "size", registry=None).observe(10 * n)
Gauge("t_peak", "peak", multiprocess_mode="max", registry=None).set(n)
Gauge("t_floor", "floor", multiprocess_mode="min", registry=None).set(n)
Gauge("t_open", "open", multiprocess_mode="sum", registry=None).set(n)
Gauge("t_last", "last", multiprocess_mode="mostrecent", registry=None).set(n)
Gauge("t_each", "each", registry=None).set(n)
Gauge("t_alive", "alive", multiprocess_mode="livesum", registry=None).set(1)
if len(sys.argv) > 3:
    print("ready", flush=True)
    sys.stdin.readline()
"""
_ARCHIVES = {"counter_archive.db", "histogram_archive.db", "summary_archive.db", "gauge_max_archive.db",
             "gauge_min_archive.db", "gauge_sum_archive.db", "gauge_mostrecent_archive.db"}


def _conf():
    """The arbiter's config file: beside tests/ in a checkout, /app/gunicorn_conf.py in the image (CI stages no copy)."""
    for p in (_HERE.parents[1] / "gunicorn_conf.py", Path("/app/gunicorn_conf.py")):
        if p.is_file():
            spec = importlib.util.spec_from_file_location("registry_gunicorn_conf_v0657", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("gunicorn_conf.py: neither beside tests/ nor at /app")


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(("info", msg % a))

    def warning(self, msg, *a):
        self.lines.append(("warning", msg % a))


def _server(live=(), master_pid=0):
    return types.SimpleNamespace(WORKERS={p: object() for p in live}, log=_Log(), master_pid=master_pid)


def _dead_worker(d, n):
    """A worker that writes every kind of value, then exits (and is reaped): its pid no longer exists."""
    p = subprocess.run([sys.executable, "-c", _WORKER, str(d), str(n)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    pids = {int(f.rsplit("_", 1)[1][:-3]) for f in os.listdir(d) if f.startswith("counter_") and f[8:-3].isdigit()}
    return pids


def _live_worker(d, n):
    p = subprocess.Popen([sys.executable, "-c", _WORKER, str(d), str(n), "stay"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ready"
    return p


def _samples(d):
    """What /metrics would report from the directory: (sample name, labels) -> value, prometheus_client's own merge."""
    from prometheus_client.multiprocess import MultiProcessCollector
    out = {}
    for m in MultiProcessCollector.merge(glob.glob(os.path.join(d, "*.db")), accumulate=True):
        for s in m.samples:
            out[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return out


def _pid_files(d):
    return {f for f in os.listdir(d) if f.endswith(".db") and f.rsplit("_", 1)[1][:-3].isdigit()}


def test_a_dead_workers_files_fold_into_one_archive_and_metrics_reads_the_same(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
    dead = set()
    for n in (1, 2, 3):
        dead |= _dead_worker(d, n) - dead
    live = _live_worker(d, 4)
    try:
        live_files = {f: open(os.path.join(d, f), "rb").read() for f in _pid_files(d) if f.endswith(f"_{live.pid}.db")}
        before = _samples(d)
        _conf().child_exit(_server(live=[live.pid]), types.SimpleNamespace(pid=max(dead)))
        after = _samples(d)
        names = set(os.listdir(d))
        assert not [f for f in names if f.endswith(".db") and any(f.endswith(f"_{p}.db") for p in dead)], \
            f"a dead worker's file is still there: {sorted(names)}"
        assert {f: open(os.path.join(d, f), "rb").read() for f in live_files} == live_files, "a live file was touched"
        assert _ARCHIVES <= names, f"one archive per kind: {sorted(names)}"
        # what /metrics reports is unchanged, except what ends with a process: its pid-labelled series (gauge 'all')
        # and the live gauges, which count live workers only
        ends = {k for k in before if k[0] == "t_each" and ("pid", str(live.pid)) not in k[1]} | {("t_alive", ())}
        assert {k: v for k, v in before.items() if k not in ends} == {k: v for k, v in after.items() if k not in ends}
        assert after[("t_alive", ())] == 1.0 and before[("t_alive", ())] == 4.0
        assert [k for k in after if k[0] == "t_each"] == [("t_each", (("pid", str(live.pid)),))]
        assert after[("t_requests_total", (("route", "/a"),))] == 10.0             # 1 + 2 + 3 dead, 4 live
        assert after[("t_peak", ())] == 4.0 and after[("t_floor", ())] == 1.0 and after[("t_open", ())] == 10.0
        assert after[("t_last", ())] == 4.0                                        # the latest write wins
        assert after[("t_latency_seconds_count", ())] == 8.0 and after[("t_size_bytes_sum", ())] == 100.0
    finally:
        live.communicate("\n", timeout=30)


def test_twelve_deaths_leave_no_more_files_than_one(tmp_path, monkeypatch):
    """The wedge's own shape: deaths in a row. Each one's files go into the archives, so the directory does not grow."""
    d = str(tmp_path)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
    conf, seen, counts = _conf(), set(), []
    for n in range(1, 13):
        pid = (_dead_worker(d, n) - seen).pop()
        seen.add(pid)
        conf.child_exit(_server(), types.SimpleNamespace(pid=pid))
        counts.append(len([f for f in os.listdir(d) if f.endswith(".db")]))
    assert counts == [len(_ARCHIVES)] * 12, counts
    assert not _pid_files(d)
    assert _samples(d)[("t_requests_total", (("route", "/a"),))] == float(sum(range(1, 13)))


def test_a_full_directory_costs_values_never_the_arbiter(tmp_path, monkeypatch):
    """No room for the archive (ENOSPC from write(), where a write into an mmap is a SIGBUS): the dead files go anyway,
    so the directory has its room back; with room after the old archive is given up, nothing is lost."""
    from agentvault_registry.core import metrics_multiproc as mm
    d = str(tmp_path)
    _dead_worker(d, 1)
    mm.fold_dead_workers(d)                                    # an archive exists
    _dead_worker(d, 2)
    real = mm._write_file
    calls = []

    def full_once(path, data):
        calls.append(path)
        if len(calls) == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(path, data)
    monkeypatch.setattr(mm, "_write_file", full_once)
    rep = mm.fold_dead_workers(d)
    assert rep.lost == 0 and rep.folded and not _pid_files(d)
    assert _samples(d)[("t_requests_total", (("route", "/a"),))] == 3.0, "the old archive's values were kept"

    _dead_worker(d, 5)

    def always_full(path, data):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(mm, "_write_file", always_full)
    rep = mm.fold_dead_workers(d)
    assert rep.lost and not _pid_files(d), "the dead files go even when their values cannot be kept"
    assert not [f for f in os.listdir(d) if f.endswith(".tmp")], "no half-written archive is left"


def test_a_live_process_or_another_users_file_is_never_folded(tmp_path, monkeypatch):
    from agentvault_registry.core import metrics_multiproc as mm
    d = str(tmp_path)
    mine = os.path.join(d, f"counter_{os.getpid()}.db")        # this test's own pid: alive, though no worker
    with open(mine, "wb") as f:
        f.write(mm.encode({'["x", "x_total", {}, "x"]': (5.0, 0.0)}))
    dead = (_dead_worker(d, 1) - {os.getpid()}).pop()
    theirs = os.path.join(d, f"counter_{dead}.db")
    real_lstat = os.lstat

    def owners(path, *a, **k):                                 # this run is user 4242; one dead file is user 4243's
        st = real_lstat(path, *a, **k)
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, 4243 if path == theirs else 4242)
                              + tuple(st)[5:10])
    monkeypatch.setattr(mm.os, "lstat", owners)
    monkeypatch.setattr(mm.os, "geteuid", lambda: 4242)
    rep = mm.fold_dead_workers(d)
    assert os.path.exists(mine) and os.path.exists(theirs)
    assert rep.kept == 1 and "counter_archive.db" not in os.listdir(d), rep
    assert "histogram_archive.db" in os.listdir(d), "the dead worker's own other files were folded (the control)"


def test_the_arbiters_start_wipes_an_earlier_run_but_a_reexec_does_not(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
    for name in ("counter_7.db", "gauge_livesum_7.db", "counter_archive.db", ".counter_archive.tmp", ".fold.lock",
                 "unrelated.txt"):
        Path(d, name).write_bytes(b"x")
    conf = _conf()
    conf.on_starting(_server(master_pid=123))                  # USR2: the old master's workers still write here
    assert len(os.listdir(d)) == 6
    srv = _server()
    conf.on_starting(srv)
    assert sorted(os.listdir(d)) == [".fold.lock", "unrelated.txt"]
    assert srv.log.lines and "4 value files" in srv.log.lines[0][1]


async def test_metrics_reports_the_fill_and_reads_every_workers_files(tmp_path, monkeypatch):
    from agentvault_registry import main
    d, warm = str(tmp_path / "dir"), str(tmp_path / "warm")
    os.makedirs(d)
    os.makedirs(warm)
    for n in (1, 2):
        _dead_worker(d, n)
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    # the app's own metrics open their files on first use, in whatever directory is set then: not the one measured
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", warm)
    app = main.create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.get("/metrics")
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", d)
        real_ismount = os.path.ismount                         # the directory as its own 16 MiB mount
        monkeypatch.setattr(os.path, "ismount", lambda p: True if p == d else real_ismount(p))
        # f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, f_files, f_ffree, f_favail, f_flag, f_namemax
        monkeypatch.setattr(os, "statvfs", lambda p: os.statvfs_result((4096, 4096, 4096, 1024, 1024, 4000, 3904,
                                                                          3904, 0, 255)))
        files = len([f for f in os.listdir(d) if f.endswith(".db")])
        r = await c.get("/metrics")
    assert r.status_code == 200, r.text
    assert "prometheus_multiproc_dir_fill_ratio 0.75" in r.text                # 3072 of 4096 blocks used
    assert "prometheus_multiproc_dir_size_bytes 1.6777216e+07" in r.text
    assert "prometheus_multiproc_dir_inodes_fill_ratio 0.024" in r.text        # 96 of 4000 inodes
    assert files >= 16 and f"prometheus_multiproc_dir_files {float(files)}" in r.text
    assert 't_requests_total{route="/a"} 3.0' in r.text, "the workers' files are read as before"


def test_a_directory_that_is_not_its_own_mount_reports_no_fill(tmp_path):
    """The operators' directory sits in the container's layer until their compose gives it a tmpfs: its statvfs would be
    the host disk's, and that fill must not page as this directory's."""
    from prometheus_client import CollectorRegistry, generate_latest
    from agentvault_registry.core import metrics_multiproc as mm
    reg = CollectorRegistry()
    reg.register(mm.MetricsDirCollector(str(tmp_path)))
    text = generate_latest(reg).decode()
    assert "prometheus_multiproc_dir_files 0.0" in text and "fill_ratio" not in text and "size_bytes" not in text


def test_the_tegs_copy_is_this_file():
    """The TEG's image cannot import the registry's package, so it carries the module byte for byte."""
    assert _TEG_COPY.is_file(), f"the TEG's copy is missing: {_TEG_COPY}"
    assert _TEG_COPY.read_bytes() == _CORE.read_bytes(), "the TEG's metrics_multiproc.py differs from the registry's"

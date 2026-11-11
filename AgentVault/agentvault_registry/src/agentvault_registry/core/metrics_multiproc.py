"""V0657 (c), session-code, 2026-11-06: a worker's death can no longer fill the metrics directory.

THE WEDGE (sbx-alpha's registry, 2026-11-06 04:20Z to 15:14Z; session-watch's measurements, room seq 1407 and 1493).
PROMETHEUS_MULTIPROC_DIR was a 16 MB tmpfs. prometheus_client keeps each process's values in files named for its pid
(counter_<pid>.db, histogram_<pid>.db, gauge_<mode>_<pid>.db). The arbiter's child_exit hook called mark_process_dead,
which removes only a dead worker's LIVE gauges, so its counters and histograms stayed for the life of the container:
212,109 counter files against 36 gauge_all and 18 gauge_max. Workers are never recycled (GUNICORN_MAX_REQUESTS=0), so
only crashes left files, a worker's worth each. Once the tmpfs was full, a new worker's first write into its mmap took
SIGBUS; the arbiter started another under a new pid, which made a new file and died the same way, about 230 times a
minute for 11 hours. Only a restart cleared it (the tmpfs is made anew), and nothing measured the fill, so the first
signal was eight alerts downstream.

WHAT THIS MODULE DOES
  * fold_dead_workers(): a dead process's counter, histogram and summary values are added into one archive file per
    kind (counter_archive.db, ...), its max, min, sum and mostrecent gauges are kept by their mode's own rule
    (gauge_max_archive.db, ...), and its files are removed. What /metrics reports does not change, so no counter seems
    to reset; the directory holds the live workers' files and at most one archive per kind, however many workers
    died. A dead process's gauge_all series (labelled with its pid) and its live gauges end with it, as
    mark_process_dead already does for the live ones. The arbiter calls it from child_exit (gunicorn_conf.py).
    It writes with plain write() calls, never through an mmap, so a full directory answers ENOSPC rather than SIGBUS:
    the arbiter cannot die of the condition it repairs. The dead files are removed first, because on a full directory
    their pages are the room the archive needs; if even then there is none, their values are given up (Prometheus
    reads that as one counter reset) and the directory has its room back.
  * wipe(): at the arbiter's start (on_starting), every value file an earlier run left goes. prometheus_client requires
    the directory to be wiped between runs; until now only the operators' compose did it, in its command line.
  * MetricsDirCollector: /metrics carries the directory's fill, read with statvfs at each scrape, so an alert fires
    while it is still cheap. It writes nothing into the directory, so it still answers when the directory is full.
  * metrics_exposition() / metrics_endpoint(): /metrics reads the files under a SHARED lock that the fold takes
    EXCLUSIVELY, so a scrape never counts a dead worker's values twice or not at all (either reads as a counter reset).

ONE FILE, TWO COPIES. The TEG carries this file byte for byte as teg_core_service/core/metrics_multiproc.py (its image
cannot import the registry's package); the registry's tests/test_metrics_multiproc_v0657.py refuses a copy that
differs. So it imports nothing from either package, and only the standard library at import time: the arbiter loads it.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import struct
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

ARCHIVE = "archive"          # where a pid would stand in an archive's name: counter_archive.db, gauge_max_archive.db
LOCK_FILE = ".fold.lock"     # no .db suffix: the collector's glob (*.db) never reads it
FOLD_LOCK_WAIT = 2.0         # seconds the arbiter waits for scrapes in flight before it leaves the fold to the next death
READ_LOCK_WAIT = 5.0         # seconds a scrape waits for a fold before it reads without the lock (as before V0657)

# prometheus_client names a process's value file <kind>_<pid>.db; a gauge's kind carries its mode.
_FILE = re.compile(r"^(?P<kind>counter|histogram|summary|gauge_(?P<mode>[a-z]+))_(?P<pid>[0-9]+|" + ARCHIVE + r")\.db$")
# What a dead process's values become, by kind: added up, the larger, the smaller, the latest, or dropped. A gauge
# mode this table does not know (a later prometheus_client) is left where it is: never fold what is not understood.
_RULES = {"counter": "sum", "histogram": "sum", "summary": "sum", "gauge_sum": "sum", "gauge_max": "max",
          "gauge_min": "min", "gauge_mostrecent": "latest", "gauge_all": "drop", "gauge_liveall": "drop",
          "gauge_livesum": "drop", "gauge_livemax": "drop", "gauge_livemin": "drop", "gauge_livemostrecent": "drop"}


def multiproc_dir() -> Optional[str]:
    """The directory prometheus_client writes to in this process, or None (single-process metrics)."""
    return os.environ.get("PROMETHEUS_MULTIPROC_DIR") or os.environ.get("prometheus_multiproc_dir") or None


@dataclass
class FoldReport:
    folded: int = 0      # dead files whose values now live in an archive
    removed: int = 0     # dead files that carried nothing to keep (live gauges, gauge_all, empty or unreadable)
    lost: int = 0        # dead files removed although their values could not be kept (no room for the archive)
    kept: int = 0        # dead files left in place (another user's file, or a kind this module does not know)
    busy: bool = False   # a scrape held the lock past FOLD_LOCK_WAIT: nothing was done, the next death retries

    def __bool__(self) -> bool:
        return bool(self.folded or self.removed or self.lost or self.kept or self.busy)

    def line(self) -> str:
        if self.busy:
            return "a scrape held the directory; the next worker exit folds it"
        return f"{self.folded} folded, {self.removed} removed, {self.lost} lost, {self.kept} left in place"


def _alive(pid: int) -> bool:
    """Whether a process with this pid exists. Only ProcessLookupError means no; anything else (EPERM: someone else's
    process) means yes, so a doubtful file is never folded under a process still writing it."""
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


@contextlib.contextmanager
def _dir_lock(path: str, mode: int, wait: float) -> Iterator[Optional[bool]]:
    """flock on the directory's lock file: yields True when held, False when `wait` ran out, None when there is no lock
    file to take (no inode left, a read-only directory): the caller decides whether to go on without it."""
    try:
        fd = os.open(os.path.join(path, LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        yield None
        return
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.02)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _entries(path: str) -> List[Tuple[str, float, float]]:
    """A value file's (key, value, timestamp) entries; [] for a missing, empty or unreadable one (a worker that died
    creating its file leaves 64 KiB of hole and no header)."""
    try:
        from prometheus_client.mmap_dict import MmapedDict
        return [(k, v, ts) for k, v, ts, _ in MmapedDict.read_all_values_from_file(path)]
    except Exception:  # noqa: BLE001 - a file that cannot be read has nothing to keep
        return []


def _merge(into: Dict[str, Tuple[float, float]], entries: Iterable[Tuple[str, float, float]], rule: str) -> None:
    """Fold entries into `into` by the kind's rule, key by key. The key is the file's own (metric, sample, labels, help),
    so merging by it gives /metrics the same totals it read from the separate files."""
    for key, value, ts in entries:
        if key not in into:
            into[key] = (value, ts)
            continue
        v0, t0 = into[key]
        if rule == "sum":
            into[key] = (v0 + value, max(t0, ts))
        elif rule == "max" and value > v0:
            into[key] = (value, ts)
        elif rule == "min" and value < v0:
            into[key] = (value, ts)
        elif rule == "latest" and ts > t0:
            into[key] = (value, ts)


def encode(entries: Dict[str, Tuple[float, float]]) -> bytes:
    """A value file holding `entries`, in prometheus_client's MmapedDict layout: a 4-byte used length and 4 bytes of
    padding, then per key its length, the key padded to 8 bytes (1 to 8 spaces, as MmapedDict pads), value, timestamp.
    The tests read it back with prometheus_client's own reader, so a change of layout in the library fails them."""
    out = [b""]
    used = 8
    for key, (value, ts) in entries.items():
        enc = key.encode("utf-8")
        padded = enc + b" " * (8 - (len(enc) + 4) % 8)
        rec = struct.pack(f"i{len(padded)}sdd".encode(), len(enc), padded, value, ts)
        out.append(rec)
        used += len(rec)
    out[0] = struct.pack(b"i", used) + b"\0" * 4
    return b"".join(out)


def _write_file(path: str, data: bytes) -> None:
    """Plain write() calls: on a full directory they raise OSError (ENOSPC), where a write into an mmap is a SIGBUS."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


def _unlink(path: str) -> bool:
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False


def _fold_kind(path: str, kind: str, rule: str, files: List[str], rep: FoldReport) -> None:
    archive = os.path.join(path, f"{kind}_{ARCHIVE}.db")
    tmp = os.path.join(path, f".{kind}_{ARCHIVE}.tmp")
    dead: Dict[str, Tuple[float, float]] = {}
    for f in files:
        _merge(dead, _entries(f), rule)
    if not dead:                                   # nothing in them to keep: they only go
        rep.removed += sum(_unlink(f) for f in files)
        return
    merged: Dict[str, Tuple[float, float]] = {}    # in memory before anything is removed, the old archive included
    _merge(merged, _entries(archive), rule)
    _merge(merged, ((k, v, ts) for k, (v, ts) in dead.items()), rule)
    data = encode(merged)
    gone = sum(_unlink(f) for f in files)          # first: on a full directory their pages are the archive's room
    try:
        _write_file(tmp, data)
    except OSError:
        _unlink(tmp)
        had_archive = _unlink(archive)             # still no room: the old archive's pages too (merged holds its
        try:                                       # values), and once more
            _write_file(tmp, data)
        except OSError:
            _unlink(tmp)
            rep.lost += gone + int(had_archive)
            return
    os.replace(tmp, archive)
    rep.folded += gone


def fold_dead_workers(path: Optional[str], live_pids: Iterable[int] = (), *,
                      lock_wait: float = FOLD_LOCK_WAIT) -> FoldReport:
    """Fold the value files of every process that no longer exists into the archives (see the module's text).

    A pid counts as dead only when it is not in `live_pids` (the arbiter's workers) AND the kernel has no such process,
    so the files of a worker just forked, or of a process someone runs with `docker exec`, are never touched. A file
    owned by another user stays: the directory is sticky (1777), so only its owner may remove it, and a file that was
    folded but not removed would be counted twice."""
    rep = FoldReport()
    if not path or not os.path.isdir(path):
        return rep
    live = {int(p) for p in live_pids}
    with _dir_lock(path, fcntl.LOCK_EX, lock_wait) as held:
        if held is False:
            rep.busy = True
            return rep
        me = os.geteuid()
        groups: Dict[str, List[str]] = {}
        for name in sorted(os.listdir(path)):
            m = _FILE.match(name)
            if not m or m.group("pid") == ARCHIVE:
                continue
            pid = int(m.group("pid"))
            if pid in live or _alive(pid):
                continue
            full = os.path.join(path, name)
            try:
                st = os.lstat(full)
            except FileNotFoundError:
                continue
            if me != 0 and st.st_uid != me:
                rep.kept += 1
                continue
            groups.setdefault(m.group("kind"), []).append(full)
        for kind, files in groups.items():
            rule = _RULES.get(kind)
            if rule is None:
                rep.kept += len(files)
            elif rule == "drop":
                rep.removed += sum(_unlink(f) for f in files)
            else:
                _fold_kind(path, kind, rule, files, rep)
    return rep


def wipe(path: Optional[str]) -> int:
    """At the arbiter's start: every value file (*.db, the archives too) and the fold's leftovers an earlier run left.
    The lock file stays (an empty file; removing it while anyone held it would split the lock in two)."""
    if not path or not os.path.isdir(path):
        return 0
    n = 0
    for name in os.listdir(path):
        if name.endswith(".db") or (name.startswith(".") and name.endswith(f"_{ARCHIVE}.tmp")):
            try:
                n += _unlink(os.path.join(path, name))
            except OSError:
                pass   # another user's file in the sticky directory: not ours to remove
    return n


class MetricsDirCollector:
    """The directory's fill, read at each scrape (statvfs): the alert's input. It allocates nothing in the directory.

    prometheus_multiproc_dir_files is always there. The size, the bytes used and the two fill ratios only when the
    directory is a mount of its own (the tmpfs every compose gives it): a directory inside a larger file system has no
    size of its own, and the host disk's fill under this name would page about the wrong thing."""

    def __init__(self, path: str):
        self._path = path

    def describe(self):
        return []

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        def g(name, doc, value):
            return GaugeMetricFamily(name, doc, value=value)
        try:
            files = sum(1 for n in os.listdir(self._path) if n.endswith(".db"))
        except OSError:
            return
        yield g("prometheus_multiproc_dir_files", "Value files in PROMETHEUS_MULTIPROC_DIR (live workers' and archives)",
                files)
        if not os.path.ismount(self._path):
            return
        try:
            st = os.statvfs(self._path)
        except OSError:
            return
        size = st.f_blocks * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        yield g("prometheus_multiproc_dir_size_bytes", "Size of the PROMETHEUS_MULTIPROC_DIR mount", size)
        yield g("prometheus_multiproc_dir_used_bytes", "Bytes used in the PROMETHEUS_MULTIPROC_DIR mount", used)
        if size > 0:
            yield g("prometheus_multiproc_dir_fill_ratio",
                    "Fill of the PROMETHEUS_MULTIPROC_DIR mount, 0 to 1 (full: every new worker dies of SIGBUS)",
                    used / size)
        if st.f_files > 0:
            yield g("prometheus_multiproc_dir_inodes_fill_ratio",
                    "Inodes used in the PROMETHEUS_MULTIPROC_DIR mount, 0 to 1", (st.f_files - st.f_ffree) / st.f_files)


def metrics_exposition() -> Tuple[bytes, str]:
    """The /metrics body and its content type. With a multiprocess directory: every process's files merged, under the
    shared lock the fold takes exclusively, and the directory's fill; without one, this process's registry."""
    from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, generate_latest
    from prometheus_client.multiprocess import MultiProcessCollector
    path = multiproc_dir()
    if not path:
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    registry = CollectorRegistry()
    MultiProcessCollector(registry, path=path)
    registry.register(MetricsDirCollector(path))
    with _dir_lock(path, fcntl.LOCK_SH, READ_LOCK_WAIT):
        return generate_latest(registry), CONTENT_TYPE_LATEST


def metrics_endpoint():
    """GET /metrics. A plain def: FastAPI runs it in the thread pool, so a wait for the lock never holds the event loop.
    No parameters and no return annotation, so FastAPI infers no request or response model."""
    from starlette.responses import Response
    body, content_type = metrics_exposition()
    return Response(content=body, headers={"Content-Type": content_type})

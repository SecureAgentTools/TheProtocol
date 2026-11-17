"""A migrate command fails fast with its reason and never hangs in silence (V0664 M12, session-tester's find, seq 3838).

Before a load, a dry run against the real source and a reconcile, `preflight` reaches every source the way plan does
(read only: a sqlpoll source connects and asks for none of its table's rows; a file drop's folder must be there) and
every writer without writing (a sql_upsert target connects read only and asks its table for no rows; a file_out folder,
or the folder it will be made in, must be there; a rest target is first reached by its first call). Each one that
cannot be reached is named with the error's CLASS, never a message that could carry a value.

During a run, `Watch` ends the command when a mapping's breaker stops it (a writer refusing row after row) or a source
fails SOURCE_FAILURES times in a row, and reports progress every PROGRESS_S seconds to a callback (the CLI's terminal
line; none with --json).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..spec import Spec

SOURCE_FAILURES = 5          # a source that fails this many times in a row ends the command
PROGRESS_S = 10.0            # the progress line's interval


def _sql_reach(spec: Spec, cfg: Mapping[str, Any], table: str) -> Optional[str]:
    """None when the database answers and the table is there (no row read), else why not (an error class)."""
    from ..sources.sqlpoll import _DIALECTS, _name
    from .reconcile import _resolved
    engine = str(cfg.get("engine") or "")
    d = _DIALECTS.get(engine)
    if d is None:
        return f"no engine {engine!r}"
    d = d()
    try:
        importlib.import_module(d.module)
    except ImportError:
        return f"its driver {d.module} is not installed"
    if engine == "sqlite" and not os.path.isfile(str(cfg.get("path") or "")):
        return f"the database file {cfg.get('path')} does not exist"
    try:
        c = {f: _resolved(spec, cfg.get(f)) for f in ("host", "database", "user", "password")}
        c["args"] = _resolved(spec, dict(cfg.get("connect_args") or {}))
    except Exception as e:  # noqa: BLE001 - a reference that does not resolve: its value is never in the message
        return f"a reference in its connection does not resolve ({type(e).__name__})"
    c["path"], c["port"] = cfg.get("path"), cfg.get("port")
    c["timeout"] = float(cfg.get("timeout_seconds") or 30)
    try:
        tbl = ".".join(d.quote(_name(p, "the table name part")) for p in str(table).split("."))
    except Exception as e:  # noqa: BLE001
        return f"the table name is not one ({type(e).__name__})"
    try:
        conn = d.connect(c)
    except Exception as e:  # noqa: BLE001 - the driver's error class says enough; its message may name a host or a user
        return f"could not connect ({type(e).__name__})"
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {tbl} WHERE 1 = 0")
        cur.fetchall()
        return None
    except Exception as e:  # noqa: BLE001
        return f"the table {table} could not be read ({type(e).__name__})"
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def preflight(spec: Spec, *, sources: bool = True, writers: bool = True) -> List[str]:
    """Every source and writer that cannot be reached, named, with why (empty when all can be)."""
    out: List[str] = []
    if sources:
        for n, ps in spec.sources.items():
            why = None
            if ps.type == "sqlpoll":
                why = _sql_reach(spec, ps.config, str(ps.config.get("table")))
            elif ps.type == "filedrop":
                p = str(ps.config.get("path") or "")
                why = None if os.path.isdir(p) else f"the folder {p} does not exist"
            if why:
                out.append(f"source {n} ({ps.type}) cannot be read: {why}")
    if writers:
        for n, ps in spec.sinks.items():
            why = None
            if ps.type == "sql_upsert":
                why = _sql_reach(spec, ps.config, str(ps.config.get("table")))
            elif ps.type == "file_out":
                p = str(ps.config.get("path") or "")
                parent = os.path.dirname(os.path.abspath(p))
                if not os.path.isdir(p) and not os.path.isdir(parent):
                    why = f"neither the folder {p} nor the folder it would be made in exists"
            if why:
                out.append(f"writer {n} ({ps.type}) cannot be reached: {why}")
    return out


class Watch:
    """Watches one proxy run: ends it when it should not wait on, and tells progress."""

    def __init__(self, proxy: Any, mappings: List[str], stats: Dict[str, Dict[str, Any]],
                 progress: Optional[Callable[[str], None]] = None, clock: Callable[[], float] = time.monotonic):
        self.proxy, self.mappings, self.stats, self.progress, self.clock = proxy, mappings, stats, progress, clock
        self.failures: Dict[str, int] = {}
        self.last_error: Dict[str, str] = {}
        self.stopped: Optional[Dict[str, Any]] = None
        self.stop = asyncio.Event()

    def wrap_sources(self) -> None:
        """Count each source's failures in a row (a record read resets them)."""
        for name, src in self.proxy.sources.items():
            src.records = self._counted(name, src.records)

    def _counted(self, name: str, records: Any) -> Any:
        async def gen():
            try:
                async for r in records():
                    self.failures[name] = 0
                    yield r
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - counted here, then the runtime's own restart takes it
                self.failures[name] = self.failures.get(name, 0) + 1
                self.last_error[name] = type(e).__name__
                raise
        return gen

    def line(self) -> str:
        o = self.proxy.outbox
        read = sum(int(s.get("rows", 0)) for s in self.stats.values())
        c = dict(o._x("SELECT status, count(*) FROM outbox GROUP BY status").fetchall())
        rejected = o._x("SELECT count(*) FROM outbox WHERE status = 'dead' AND mapped IS NULL").fetchone()[0]
        failed = int(c.get("dead", 0)) - int(rejected)
        return (f"read {read}, written {int(c.get('done', 0))}, rejected {int(rejected)}, failed {failed}, "
                f"pending {int(c.get('pending', 0))}")

    def check(self) -> bool:
        """True when the run must end now (self.stopped says why)."""
        for name, n in self.failures.items():
            if n >= SOURCE_FAILURES:
                self.stopped = {"kind": "source", "name": name,
                                "why": f"the source {name} failed {n} times in a row ({self.last_error.get(name)})"}
                return True
        sw = self.proxy.outbox.switches()
        for m in self.mappings:
            b = sw.get(f"breaker:{m}")
            if isinstance(b, Mapping) and b.get("state") == "stopped":
                self.stopped = {"kind": "breaker", "name": m,
                                "why": f"the writer refused {b.get('refusals')} rows of the mapping {m} in a row, "
                                       f"the last: {b.get('why')}"}
                return True
        return False

    async def run(self) -> None:
        """Until the proxy is idle, or check() says to end it; the progress line every PROGRESS_S."""
        task = asyncio.ensure_future(self.proxy.run(stop=self.stop))
        last = self.clock()
        try:
            while not task.done():
                # why it would end first: a stopped breaker also makes the proxy idle (its rows are held)
                if self.proxy._started and (self.check() or self.proxy.idle()):
                    self.stop.set()
                    break
                if self.progress is not None and self.clock() - last >= PROGRESS_S:
                    last = self.clock()
                    try:
                        self.progress(self.line())
                    except Exception:  # noqa: BLE001 - a progress line never stops a load
                        pass
                await asyncio.sleep(0.05)
        finally:
            self.stop.set()
            await task
        if self.stopped is None:
            self.check()                    # a stop that came in the last turn still says why

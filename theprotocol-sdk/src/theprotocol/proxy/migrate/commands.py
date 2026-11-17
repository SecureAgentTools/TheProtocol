"""The commands of `tp-proxy migrate` (section C of the contract). Each returns (exit code, answer); cli.py prints the
answer as text or, with --json, as JSON.

Exit codes: 0 pass or done, 1 a check failed or was refused, 2 a usage or spec error, 3 not measured (reconcile could
not compare: the answer says what was missing).
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import httpx

from ..outbox import Outbox, PluginState
from ..plugins import PluginError, Refused, Retry
from ..spec import TP_SOURCES, Spec, SpecError, parse
from . import params as P
from . import reconcile as R
from . import reports
from .sample import STANDS_IN_FOR, read_rows
from .schema import STATE_DIR, TEMPLATE_COPY, Kit, KitError, canonical, kit_from_files, load_kit, sha256_hex

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_MEASURED = 0, 1, 2, 3
WRITERS = ("sql_upsert", "file_out", "rest")
ATTESTATION_PATH = "/api/v1/teg/attestations/submit"
LIBRARY = "/api/v1/workflow-templates"
HINT = "Moving off a system instead of bridging it? tp-proxy migrate --help"

Answer = Tuple[int, Dict[str, Any]]


class Stop(Exception):
    """A command ends here: its exit code and its answer's problems."""

    def __init__(self, code: int, problems: List[str], **extra: Any):
        self.code, self.problems, self.extra = code, list(problems), extra
        super().__init__("; ".join(self.problems))


def _verdict_code(v: str) -> int:
    return {"pass": EXIT_OK, "not_measured": EXIT_NOT_MEASURED}.get(v, EXIT_FAILED)


# ── the kit, its parameters and its spec ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Prepared:
    kit: Kit
    doc: Dict[str, Any]           # proxy.yaml with the parameters filled, only the load's mappings
    spec: Spec
    values: Dict[str, Any]
    manifest: Dict[str, Any] = dataclasses.field(default_factory=dict)   # the kit's, its reconcile entries filled
    raw: Dict[str, Any] = dataclasses.field(default_factory=dict)        # proxy.yaml as written (the load's part)
    user: Set[str] = dataclasses.field(default_factory=set)              # the parameters YOU set (--set, --params)

    def destinations(self) -> List[Dict[str, Any]]:
        from .destinations import follow_the_value, listing, template_wheres
        dests = listing(self.doc, self.raw, self.user)
        shipped = self.shipped_files()
        return follow_the_value(dests, template_wheres(shipped)) if shipped is not None else dests

    def shipped_files(self) -> Optional[Dict[str, str]]:
        """The files the kit came with from a library (.migrate/template/, written by get and fork), else None."""
        d = self.kit.state_dir / TEMPLATE_COPY
        if not (d / "proxy.yaml").is_file() or not (d / "migration.yaml").is_file():
            return None
        return {n: (d / n).read_text(encoding="utf-8") for n in ("proxy.yaml", "migration.yaml")}

    @property
    def library(self) -> bool:
        """A kit that came from a library (get, fork): .migrate/template/ holds the files it came with. A kit its own
        author published is not one (publish writes no copy)."""
        return self.shipped_files() is not None

    def mapping(self, name: str):
        return next(m for m in self.spec.mappings if m.name == name)


def _kit(path: Optional[str]) -> Kit:
    try:
        return load_kit(path or ".")
    except KitError as e:
        raise Stop(EXIT_USAGE, e.problems)


def kit_rules(manifest: Mapping[str, Any], doc: Any) -> List[str]:
    """What a migration kit's proxy.yaml must be, beyond a valid spec."""
    if not isinstance(doc, dict):
        return ["proxy.yaml: the spec is not a mapping"]
    out = []
    for n, a in (doc.get("actions") or {}).items():
        out.append(f"proxy.yaml actions.{n}: a migration kit moves data from system A to system B and calls nothing "
                   f"on TheProtocol (an action belongs in a proxy, not a kit)")
    sources = doc.get("sources") or {}
    for n, s in sources.items():
        if (s or {}).get("type") in TP_SOURCES:
            out.append(f"proxy.yaml sources.{n}: a migration kit reads system A, not TheProtocol")
    sinks = doc.get("sinks") or {}
    for n, s in sinks.items():
        if (s or {}).get("type") not in WRITERS:
            out.append(f"proxy.yaml sinks.{n}: a migration kit writes with {', '.join(WRITERS)}, not "
                       f"{(s or {}).get('type')!r}")
    maps = {m.get("name"): m for m in doc.get("mappings") or [] if isinstance(m, dict)}
    load = manifest["load"]["mappings"]
    for m in load:
        if m not in maps:
            out.append(f"migration.load.mappings: proxy.yaml has no mapping {m!r}")
    for i, r in enumerate(manifest.get("reconcile") or []):
        if r["mapping"] not in load:
            out.append(f"migration.reconcile[{i}].mapping: {r['mapping']!r} is not one of the load's mappings")
    for name in manifest.get("sample") or {}:
        if name not in sources:
            out.append(f"migration.sample.{name}: proxy.yaml has no source {name!r}")
    if manifest.get("rollback") == "auto":
        for m in load:
            to = (maps.get(m) or {}).get("to")
            t = (sinks.get(to) or {}).get("type")
            if to in sinks and t != "sql_upsert":
                out.append(f"migration.rollback: auto restores SQL targets only; the mapping {m} writes with {t} "
                           f"(say rollback: manual and name the way back in README.md)")
    return out


def prepare(path: Optional[str], *, sets: Sequence[str] = (), params_file: Optional[str] = None,
            sample: bool = False, check_plugins: bool = True) -> Prepared:
    kit = _kit(path)
    doc = R_yaml(kit.files["proxy.yaml"])
    try:
        given_sets = P.parse_sets(sets)
        given_file = P.read_params_file(params_file) if params_file else {}
        values = P.resolve_values(kit.manifest, sets=given_sets, file_values=given_file,
                                  needed=P.placeholders([doc, kit.manifest.get("reconcile") or []]),
                                  allow_unset_secrets=sample)
    except P.ParamError as e:
        raise Stop(EXIT_USAGE, e.problems)
    filled = P.fill(doc, values)
    problems = kit_rules(kit.manifest, filled)
    if problems:
        raise Stop(EXIT_USAGE, problems)
    filled = only_load(filled, kit.manifest["load"]["mappings"])
    try:
        spec = parse(filled, base=kit.root, check_plugins=check_plugins)
    except SpecError as e:
        raise Stop(EXIT_USAGE, [f"proxy.yaml {p}" for p in e.problems])
    # a reconcile entry takes the same parameters (a REST target's read-back address and its headers)
    manifest = {**kit.manifest, "reconcile": P.fill(kit.manifest.get("reconcile") or [], values)}
    raw = only_load(doc, kit.manifest["load"]["mappings"])
    return Prepared(kit, filled, spec, values, manifest, raw, set(given_sets) | set(given_file))


def R_yaml(text: str) -> Any:
    import yaml
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise Stop(EXIT_USAGE, [f"proxy.yaml: not YAML ({e.__class__.__name__})"])


def only_load(doc: Dict[str, Any], load: Sequence[str]) -> Dict[str, Any]:
    """The spec with only the load's mappings, and only the sources and sinks they use."""
    d = copy.deepcopy(doc)
    maps = [m for m in d.get("mappings") or [] if m.get("name") in load]
    maps.sort(key=lambda m: list(load).index(m["name"]))
    d["mappings"] = maps
    used_src = {m["from"] for m in maps}
    used_sink = {m["to"] for m in maps}
    d["sources"] = {k: v for k, v in (d.get("sources") or {}).items() if k in used_src}
    d["sinks"] = {k: v for k, v in (d.get("sinks") or {}).items() if k in used_sink}
    return d


def _finishing(doc: Dict[str, Any], *, settle: bool) -> None:
    """Every source finishes after one pass (a webhook receiver cannot: refused)."""
    for n, s in (doc.get("sources") or {}).items():
        t, cfg = s.get("type"), s.setdefault("config", {})
        if t == "webhook":
            raise Stop(EXIT_USAGE, [f"proxy.yaml sources.{n}: a webhook receiver never finishes; a migration reads a "
                                    f"system it can read again (sqlpoll, filedrop, sftp), or --sample stands in"])
        if t in ("sqlpoll", "sftp", "filedrop"):
            cfg["poll_seconds"] = 0          # one pass, then finished (a watching drop never ends)
        if t == "sqlpoll" and not settle:
            cfg["settle_seconds"] = 0


# ── running the engine ───────────────────────────────────────────────────────────────────────────────────────────────

def _row_fields(stype: str, cfg: Mapping[str, Any], rec: Any) -> List[str]:
    row = R._row_of(stype, cfg, rec)
    return [str(k) for k in row] if isinstance(row, Mapping) else []


async def _run(spec: Spec, order: Sequence[str], *, limit: Optional[int] = None,
               progress: Optional[Callable[[str], None]] = None) -> Tuple[Dict[str, Dict[str, Any]],
                                                                           Optional[Dict[str, Any]]]:
    """The proxy over `spec`, the load's mappings delivered in `order` (each one's rows after the one before it is
    idle), until every source finished and nothing is due, or until guard.Watch ends it (a breaker that stopped a
    mapping, a source failing again and again). Answers (per source: rows read this run and field names, why it ended
    early or None)."""
    from ..runtime import Proxy
    from .guard import Watch
    stats: Dict[str, Dict[str, Any]] = {n: {"rows": 0, "fields": set()} for n in spec.sources}
    o = Outbox(spec.state_path)
    try:
        for m in order:
            o.set_switch(f"pause:{m}", None)
    finally:
        o.close()
    for i, current in enumerate(order):
        o = Outbox(spec.state_path)
        try:
            for later in order[i + 1:]:
                o.set_switch(f"pause:{later}", {"why": "tp-proxy migrate: the load's order"})
        finally:
            o.close()
        proxy = Proxy(spec, service=False, poll_s=0.05)
        orig = proxy.ingest
        counts: Dict[str, int] = {}

        async def ingest(source: str, rec: Any, _orig=orig, _counts=counts) -> List[str]:
            st = stats[source]
            st["rows"] += 1
            ps = spec.sources[source]
            st["fields"].update(_row_fields(ps.type, ps.config, rec))
            return await _orig(source, rec)
        proxy.ingest = ingest                       # the runtime calls self.ingest: the instance's wins
        if limit is not None:
            for name, src in proxy.sources.items():
                src.records = _limited(src.records, limit)
        watch = Watch(proxy, list(order), stats, progress)
        watch.wrap_sources()
        try:
            await watch.run()
        finally:
            proxy.close()
        if watch.stopped is not None:
            stopped = watch.stopped
            break
    else:
        stopped = None
    o = Outbox(spec.state_path)
    try:
        for m in order:
            o.set_switch(f"pause:{m}", None)
    finally:
        o.close()
    return {n: {"rows": s["rows"], "fields": sorted(s["fields"])} for n, s in stats.items()}, stopped


def _halted(rep: Dict[str, Any], stopped: Optional[Dict[str, Any]]) -> List[str]:
    """The report of a run that ended early says so (by kind and name; the reason, which may quote the other side's
    answer, goes only to the command's own answer) and fails."""
    if stopped is None:
        return []
    rep["stopped"] = {"kind": stopped["kind"], "name": stopped["name"]}
    rep["verdict"] = "fail"
    return [f"ended early: {stopped['why']}"]


def _preflight(spec: Spec, *, sources: bool = True, writers: bool = True) -> None:
    from .guard import preflight
    problems = preflight(spec, sources=sources, writers=writers)
    if problems:
        raise Stop(EXIT_FAILED, problems)


def _resume(spec: Spec, order: Sequence[str]) -> None:
    """A load again is a resume: a breaker a refusing writer stopped is cleared, and the rows the writer refused (not
    the rows the mapping rejected, which would be rejected again) get another chance, under the same keys."""
    if not Path(spec.state_path).exists():
        return
    o = Outbox(spec.state_path)
    try:
        for m in order:
            o.set_switch(f"breaker:{m}", None)
        keys = [k for (k,) in o._x("SELECT key FROM outbox WHERE status = 'dead' AND mapped IS NOT NULL").fetchall()]
        if keys:
            o.replay(keys=keys)
    finally:
        o.close()


def _limited(records: Any, n: int) -> Any:
    async def gen():
        k = 0
        async for r in records():
            if k >= n:
                return
            k += 1
            yield r
    return gen


def _counts_into(report: Dict[str, Any], spec: Spec, *, scratch: bool) -> None:
    o = Outbox(spec.state_path)
    try:
        report["mappings"] = reports.mapping_counts(o, [m.name for m in spec.mappings])
        report["targets"] = reports.target_counts(o, list(spec.sinks), scratch=scratch)
    finally:
        o.close()


# ── reconcile ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _target_rows(spec: Spec, sink: str, entry: Mapping[str, Any], *, scratch_dir: Optional[Path]):
    ps = spec.sinks[sink]
    keys, fields = list(entry["target"]["key"]), list(entry["pairs"].values())
    if ps.type == "sql_upsert":
        return R.sql_rows(spec, ps.config, keys, fields)
    if ps.type == "file_out":
        return R.file_rows(ps.config)
    if ps.type == R_SCRATCH_REST():
        return R.requests_rows(Path(ps.config["requests_file"]))
    if ps.type == "rest":
        read = entry["target"].get("read")
        if not read:
            raise R.NotMeasured(f"the target {sink} is a REST API and the manifest names no way to read it back "
                                f"(reconcile.target.read)")
        return R.rest_rows(spec, read)
    raise R.NotMeasured(f"the target {sink} ({ps.type}) cannot be read back")


def R_SCRATCH_REST() -> str:
    from .scratch import SCRATCH_REST
    return SCRATCH_REST


async def _reconcile(prep: Prepared, spec: Spec, report: Dict[str, Any], *, workdir: Path,
                     scratch_dir: Optional[Path] = None, limit: Optional[int] = None) -> None:
    batch_rows = int(prep.manifest["load"].get("batch_rows") or 1000)
    report["batches"] = []
    entries = prep.manifest.get("reconcile") or []
    if not entries:
        report["reconcile"]["*"] = R.not_measured("the manifest names nothing to reconcile")
        return
    for entry in entries:
        name = entry["mapping"]
        sink = prep.mapping(name).action
        try:
            rows = _target_rows(spec, sink, entry, scratch_dir=scratch_dir)
            res, batches = await R.compare(spec, entry, rows, batch_rows=batch_rows, workdir=workdir,
                                             limit=limit)
        except R.NotMeasured as e:
            res, batches = R.not_measured(str(e)), []
        except PluginError as e:
            res, batches = R.not_measured(f"a side could not be read: {e}"), []
        except Exception as e:  # noqa: BLE001 - a driver's error: its class, never its message (it may carry a value)
            res, batches = R.not_measured(f"a side could not be read ({type(e).__name__})"), []
        report["reconcile"][name] = res
        report["batches"].extend({"mapping": name, **b} for b in batches)


# ── new ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

PAIRS = {("sql", "sql"), ("file", "sql"), ("sql", "rest")}


def _put(p: Path, text: str) -> None:
    """A kit file's text written as the UTF-8 bytes it is. `write_text` turns each line feed into a carriage return and a line feed on
    Windows, and a kit's content hash reads the raw bytes: a kit written there would not carry the hash it was published with."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _folder_or_stop(d: Path, force: bool) -> None:
    """The folder a kit is written to: new or empty, or (with --force) anything that is a folder; a FILE there is a sentence, not a traceback."""
    if d.exists() and not d.is_dir():
        raise Stop(EXIT_FAILED, [f"{d} is a file, not a folder"])
    if d.exists() and any(d.iterdir()) and not force:
        raise Stop(EXIT_FAILED, [f"{d} is not empty (--force writes over it)"])


def cmd_new(name: str, from_kind: str, to_kind: str, out: Optional[str] = None, force: bool = False) -> Answer:
    from .skeletons import skeleton
    import re
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", name or ""):
        raise Stop(EXIT_USAGE, [f"{name!r}: a kit's name is lower-case letters, digits and '-' (at most 63)"])
    if (from_kind, to_kind) not in PAIRS:
        raise Stop(EXIT_USAGE, [f"--from {from_kind} --to {to_kind}: a skeleton exists for "
                                f"{', '.join(f'{a} to {b}' for a, b in sorted(PAIRS))}"])
    d = Path(out or name).resolve()
    _folder_or_stop(d, force)
    files = skeleton(name, from_kind, to_kind)
    for rel, text in files.items():
        _put(d / rel, text)
    try:
        kit = load_kit(d)
    except KitError as e:  # pragma: no cover - a skeleton that does not load is this module's bug
        raise Stop(EXIT_FAILED, e.problems)
    return EXIT_OK, {"kit": str(d), "files": sorted(files), "content_hash": kit.content_hash,
                     "next": [f"tp-proxy migrate check {d}", f"tp-proxy migrate dry-run {d} --sample"]}


def cmd_list_starters() -> Answer:
    """The three starter kits that ship inside the package, one line each (the name and what it moves)."""
    from .starters import listing
    try:
        return EXIT_OK, {"starters": listing()}
    except KitError as e:
        raise Stop(EXIT_FAILED, e.problems)


def cmd_new_starter(name: str, out: Optional[str] = None, force: bool = False) -> Answer:
    """Write a starter kit (the same files proxy/migrations/NAME has) to a folder, ./NAME by default, never over a non-empty one."""
    from .starters import STARTERS, starter_kit
    if name not in STARTERS:
        raise Stop(EXIT_USAGE, [f"{name!r} is not a starter kit: the starters are {', '.join(STARTERS)} "
                                f"(tp-proxy migrate new --list-starters)"])
    d = Path(out or name).resolve()
    _folder_or_stop(d, force)
    try:
        kit = starter_kit(name)
    except KitError as e:
        raise Stop(EXIT_FAILED, e.problems)
    for rel, text in kit.files.items():
        _put(d / rel, text)
    return EXIT_OK, {"kit": str(d), "starter": name, "files": sorted(kit.files), "content_hash": kit.content_hash,
                     "next": [f"tp-proxy migrate check {d}", f"tp-proxy migrate dry-run {d} --sample"]}


# ── check and plan ───────────────────────────────────────────────────────────────────────────────────────────────────

def cmd_check(path: Optional[str], *, sets: Sequence[str] = (), params_file: Optional[str] = None) -> Answer:
    try:
        kit = load_kit(path or ".")
    except KitError as e:
        return EXIT_FAILED, {"valid": False, "problems": e.problems}
    try:
        prep = prepare(path, sets=sets, params_file=params_file, sample=True)
    except Stop as e:
        return (EXIT_USAGE if any(p.startswith("parameter") or p.startswith("--") for p in e.problems) and
                not any(p.startswith("proxy.yaml") or p.startswith("migration") for p in e.problems) else EXIT_FAILED,
                {"valid": False, "problems": e.problems})
    files = kit.files
    declared = kit.manifest.get("parameters") or {}
    status = {}
    for n, p in declared.items():
        v = prep.values.get(n)
        status[n] = ("not given (a secret: a --sample run needs none)" if isinstance(v, str) and
                     v.startswith(P.UNSET_PREFIX) else "given" if n in set(P.parse_sets(sets)) else
                     "default" if "default" in p else "given")
    missing_samples = [n for n in prep.spec.sources if n not in (kit.manifest.get("sample") or {})]
    return EXIT_OK, {
        "valid": True, "kit": kit.name, "content_hash": kit.content_hash, "template": kit.template_ref(),
        "files": len(files), "bytes": sum(len(t.encode("utf-8")) for t in files.values()),
        "parameters": status, "from": kit.manifest["from"], "to": kit.manifest["to"],
        "sources": {n: p.type for n, p in prep.spec.sources.items()},
        "sinks": {n: p.type for n, p in prep.spec.sinks.items()},
        "load": list(kit.manifest["load"]["mappings"]), "rollback": kit.manifest["rollback"],
        "destinations": prep.destinations(),
        "notes": [f"source {n} has no sample: --sample cannot stand in for it" for n in missing_samples]}


def _paths_read(node: Any, out: set) -> None:
    if isinstance(node, str) and node.startswith("$"):
        parts = node[2:].split(".") if node.startswith("$.") else []
        if parts[:2] == ["payload", "data"] and len(parts) > 2:
            out.add(parts[2])
        elif parts[:1] == ["payload"] and len(parts) > 1:
            out.add(parts[1])
    elif isinstance(node, Mapping):
        for v in node.values():
            _paths_read(v, out)
    elif isinstance(node, list):
        for v in node:
            _paths_read(v, out)


def _is_pathlike(node: Any) -> bool:
    found: set = set()
    _paths_read(node, found)
    return bool(found) or (isinstance(node, str) and node.startswith("$"))


def _inventory(prep: Prepared, name: str, *, sample: bool) -> Dict[str, Any]:
    ps = prep.spec.sources[name]
    if sample:
        s = (prep.manifest.get("sample") or {}).get(name)
        if not s:
            return {"rows": None, "fields": [], "why": "the manifest has no sample for it"}
        fmt = s.get("format") or ("jsonl" if ps.type in ("sqlpoll", "webhook") else ps.config.get("format") or "csv")
        rows = read_rows(str(prep.kit.root / s["file"]), fmt)
        fields: List[str] = []
        for r in rows:
            for k in (r if isinstance(r, Mapping) else {}):
                if str(k) not in fields:
                    fields.append(str(k))
        return {"rows": len(rows), "fields": fields}
    if ps.type == "sqlpoll":
        return _sql_inventory(prep.spec, ps.config)
    if ps.type == "filedrop":
        from ..sources.filedrop import _READERS
        d = Path(str(ps.config["path"]))
        if not d.is_dir():
            return {"rows": None, "fields": [], "why": f"the folder {d} does not exist"}
        n, fields = 0, []
        for p in sorted(d.iterdir()):
            sfx = ps.config.get("suffix") or ""
            if not p.is_file() or (sfx and not p.name.endswith(sfx)) or p.name.startswith("."):
                continue
            try:
                rows = _READERS[ps.config.get("format") or "csv"](p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n += len(rows)
            for r in rows:
                for k in (r if isinstance(r, Mapping) else {}):
                    if str(k) not in fields:
                        fields.append(str(k))
        return {"rows": n, "fields": fields}
    return {"rows": None, "fields": [], "why": f"a {ps.type} source is not counted before it is read (plan --sample "
                                               f"reads its sample)"}


def _sql_inventory(spec: Spec, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    from ..sources.sqlpoll import SqlPollSource
    import importlib
    src = SqlPollSource(cfg, R._Ctx(spec, "plan"))
    try:
        importlib.import_module(src._d.module)
    except ImportError:
        return {"rows": None, "fields": [], "why": f"the {src._d.engine} driver ({src._d.module}) is not installed"}
    try:
        conn = src._d.connect(src._connect_config())
    except Exception as e:  # noqa: BLE001 - the driver's own error class names the problem; never a value
        return {"rows": None, "fields": [], "why": f"could not connect ({type(e).__name__})"}
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {src._sql.table_sql}")
        n = int(cur.fetchone()[0])
        cur.execute(f"SELECT {src._sql.columns_sql} FROM {src._sql.table_sql} WHERE 1 = 0")
        fields = [str(c[0]) for c in cur.description or []]
        return {"rows": n, "fields": fields}
    except Exception as e:  # noqa: BLE001
        return {"rows": None, "fields": [], "why": f"the table could not be read ({type(e).__name__})"}
    finally:
        conn.close()


def cmd_plan(path: Optional[str], *, sample: bool = False, sets: Sequence[str] = (),
             params_file: Optional[str] = None) -> Answer:
    prep = prepare(path, sets=sets, params_file=params_file, sample=sample)
    rep = reports.new("inventory", prep.kit, sample=sample)
    for name in prep.spec.sources:
        rep["sources"][name] = _inventory(prep, name, sample=sample)
    for m in prep.spec.mappings:
        sink = prep.spec.sinks[m.action]
        cols = list(sink.config.get("columns") or [])
        read: set = set()
        _paths_read(m.fields, read)
        no_source = [c for c in cols if c not in m.fields] + [f for f, v in m.fields.items() if not _is_pathlike(v)]
        have = rep["sources"][m.source].get("fields") or []
        rep["mappings"][m.name] = {"from": m.source, "to": m.action, "fields": sorted(m.fields),
                                   "no_source": no_source, "unused": [f for f in have if f not in read]}
    rep["verdict"] = "not_measured" if any(s.get("rows") is None for s in rep["sources"].values()) else "pass"
    p = reports.write(prep.kit, rep)
    return _verdict_code(rep["verdict"]), {**rep, "written": str(p), "destinations": prep.destinations()}


# ── dry-run and load ─────────────────────────────────────────────────────────────────────────────────────────────────

def _scratch_doc(prep: Prepared, *, sample: bool, scratch: Path) -> Dict[str, Any]:
    from .scratch import twin
    doc = copy.deepcopy(prep.doc)
    doc.pop("identity", None)
    doc.pop("registry", None)
    doc["state"] = str(scratch / "state.db")
    doc.setdefault("service", {})["enabled"] = False
    if sample:
        samples = prep.manifest.get("sample") or {}
        for n, s in list((doc.get("sources") or {}).items()):
            if n not in samples:
                raise Stop(EXIT_USAGE, [f"--sample: the manifest has no sample for the source {n}"])
            if s["type"] not in STANDS_IN_FOR:
                raise Stop(EXIT_USAGE, [f"--sample: a sample stands in for {', '.join(STANDS_IN_FOR)}, not {s['type']}"])
            cfg = {"file": str(prep.kit.root / samples[n]["file"]), "stands_in_for": s["type"],
                   "config": s.get("config") or {}}
            if samples[n].get("format"):
                cfg["format"] = samples[n]["format"]
            doc["sources"][n] = {"type": "migrate_sample", "config": cfg}
    else:
        _finishing(doc, settle=False)
    for n, s in list((doc.get("sinks") or {}).items()):
        cols: List[str] = []
        for m in doc.get("mappings") or []:
            if m.get("to") == n:
                cols += [c for c in m.get("fields") or {} if c not in cols]
        doc["sinks"][n] = {**{k: v for k, v in s.items() if k == "limits"}, **twin(s["type"], n, s.get("config") or {},
                                                                              scratch, cols)}
    return doc


def cmd_dry_run(path: Optional[str], *, sample: bool = False, limit: Optional[int] = None, sets: Sequence[str] = (),
                params_file: Optional[str] = None, progress: Optional[Callable[[str], None]] = None) -> Answer:
    from .scratch import registered
    prep = prepare(path, sets=sets, params_file=params_file, sample=sample)
    scratch = prep.kit.state_dir / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)                       # the scratch is the dry run's own: each run starts empty
    scratch.mkdir(parents=True)
    rep = reports.new("dry_run", prep.kit, sample=sample)
    with registered():
        doc = _scratch_doc(prep, sample=sample, scratch=scratch)
        try:
            spec = parse(doc, base=prep.kit.root)
        except SpecError as e:
            raise Stop(EXIT_USAGE, [f"the scratch spec: {p}" for p in e.problems])
        if not sample:
            _preflight(spec, writers=False)          # the writers are the scratch twins; the source is the real one
        rep["sources"], stopped = asyncio.run(_run(spec, list(prep.manifest["load"]["mappings"]), limit=limit,
                                                   progress=progress))
        _counts_into(rep, spec, scratch=True)
        if stopped is None:
            asyncio.run(_reconcile(prep, spec, rep, workdir=scratch, scratch_dir=scratch, limit=limit))
    rep["verdict"] = reports.verdict(rep)
    why = _halted(rep, stopped)
    p = reports.write(prep.kit, rep)
    return _verdict_code(rep["verdict"]), {**rep, "written": str(p), **({"problems": why} if why else {})}


def _real_spec(prep: Prepared, *, settle: bool = True) -> Spec:
    doc = copy.deepcopy(prep.doc)
    doc["state"] = str(prep.kit.state_dir / "state.db")
    doc.setdefault("service", {})["enabled"] = False
    _finishing(doc, settle=settle)
    try:
        return parse(doc, base=prep.kit.root)
    except SpecError as e:
        raise Stop(EXIT_USAGE, [f"proxy.yaml {p}" for p in e.problems])


def cmd_load(path: Optional[str], *, sets: Sequence[str] = (), params_file: Optional[str] = None,
             confirm_destinations: bool = False, ask: Optional[Callable[[List[str]], bool]] = None,
             progress: Optional[Callable[[str], None]] = None) -> Answer:
    """The real load. It starts only once the destinations are confirmed (confirm_destinations, or `ask` answering yes
    to the list), and for a library kit never while a writer's destination is one the template named."""
    from . import destinations as D
    prep = prepare(path, sets=sets, params_file=params_file)
    dests = prep.destinations()
    refused = D.refusals(dests, library=prep.library)
    if refused:
        raise Stop(EXIT_FAILED, refused, destinations=dests)
    if not confirm_destinations and not (ask is not None and ask(D.lines(dests))):
        raise Stop(EXIT_FAILED, ["load sends your rows to the destinations below: read them, then load again with "
                                 "--confirm-destinations", *D.lines(dests)], destinations=dests)
    prep.kit.state_dir.mkdir(parents=True, exist_ok=True)
    spec = _real_spec(prep)
    _preflight(spec)
    order = list(prep.manifest["load"]["mappings"])
    _resume(spec, order)
    rep = reports.new("load", prep.kit)
    rep["sources"], stopped = asyncio.run(_run(spec, order, progress=progress))
    _counts_into(rep, spec, scratch=False)
    rep["verdict"] = reports.verdict(rep)
    why = _halted(rep, stopped)
    p = reports.write(prep.kit, rep)
    return _verdict_code(rep["verdict"]), {**rep, "written": str(p), "destinations": dests,
                                           **({"problems": why} if why else {})}


def cmd_reconcile(path: Optional[str], *, sets: Sequence[str] = (), params_file: Optional[str] = None) -> Answer:
    prep = prepare(path, sets=sets, params_file=params_file)
    prep.kit.state_dir.mkdir(parents=True, exist_ok=True)
    spec = _real_spec(prep, settle=False)
    _preflight(spec)
    rep = reports.new("reconcile", prep.kit)
    asyncio.run(_reconcile(prep, spec, rep, workdir=prep.kit.state_dir))
    rep["verdict"] = reports.verdict(rep)
    p = reports.write(prep.kit, rep)
    return _verdict_code(rep["verdict"]), {**rep, "written": str(p)}


# ── rollback ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def cmd_rollback(path: Optional[str], *, yes: bool = False, sets: Sequence[str] = (),
                 params_file: Optional[str] = None) -> Answer:
    prep = prepare(path, sets=sets, params_file=params_file)
    if prep.manifest["rollback"] == "manual":
        raise Stop(EXIT_FAILED, ["this kit's rollback is manual: README.md names the way back"])
    if not yes:
        raise Stop(EXIT_USAGE, ["rollback puts the target's rows back as they were before the load: give --yes"])
    state = prep.kit.state_dir / "state.db"
    if not state.is_file():
        raise Stop(EXIT_FAILED, [f"nothing to roll back: no load has run ({state} does not exist)"])
    from ..sinks.sql_upsert import restore_preimages
    spec = _real_spec(prep)
    rep = reports.new("rollback", prep.kit)
    restored: Dict[str, int] = {}

    stopped: Dict[str, Any] = {}

    async def go() -> None:
        o = Outbox(str(state))
        try:
            for name, ps in spec.sinks.items():
                if ps.type != "sql_upsert":
                    continue
                try:
                    restored[name] = await restore_preimages(PluginState(o, f"sink:{name}"), ps.config,
                                                             secret=spec.secret, newest_first=True)
                except Exception as e:  # noqa: BLE001 - every error ends the rollback with its report, never a traceback
                    stopped.update(name=name, kind=type(e).__name__,
                                   why=str(e) if isinstance(e, (PluginError, Refused, Retry)) else "")
                    return
        finally:
            o.close()
    try:
        asyncio.run(go())
    except Exception as e:  # noqa: BLE001 - the state file itself could not be read
        stopped.update(name="state", kind=type(e).__name__, why="")
    if stopped:
        # what was put back stays put back; the state stays where it is, so a rollback again takes the rest
        rep["targets"] = {n: {"restored": c} for n, c in restored.items()}
        rep["targets"][stopped["name"]] = {"restored": None}
        rep["restored"] = sum(restored.values())
        rep["stopped"] = {"kind": "rollback", "name": stopped["name"]}
        rep["verdict"] = "fail"
        p = reports.write(prep.kit, rep)
        why = f"the rollback of {stopped['name']} stopped ({stopped['kind']}" + (f": {stopped['why']}" if stopped['why']
                                                                                else "") + ")"
        return EXIT_FAILED, {**rep, "written": str(p),
                             "problems": [why, f"restored before it: {rep['restored']} rows; the load's state is kept, "
                                                f"so tp-proxy migrate rollback --yes again takes the rest"]}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kept = state.with_name(f"state.rolled-back-{stamp}.db")
    state.rename(kept)                               # a load after this one starts again from the start
    rep["targets"] = {n: {"restored": c} for n, c in restored.items()}
    rep["restored"] = sum(restored.values())
    rep["verdict"] = "pass"
    p = reports.write(prep.kit, rep)
    return EXIT_OK, {**rep, "written": str(p), "state_kept_as": str(kept)}


# ── the registry: identity, certify, get, publish, fork ──────────────────────────────────────────────────────────────

def _identity_spec(path: Optional[str], kit: Optional[Kit] = None) -> Spec:
    from ..spec import read
    cand = path
    if not cand and kit is not None:
        try:
            doc = R_yaml(kit.files["proxy.yaml"])
        except Stop:
            doc = None
        if isinstance(doc, dict) and doc.get("identity") and doc.get("registry"):
            cand = str(kit.root / "proxy.yaml")
    if not cand:
        raise Stop(EXIT_USAGE, ["this command acts as an agent: --identity names a proxy.yaml whose registry and "
                                "identity it uses (tp-proxy init writes one)"])
    try:
        spec = read(cand, check_plugins=False)
    except SpecError as e:
        raise Stop(EXIT_USAGE, [f"--identity {cand}: {p}" for p in e.problems])
    if not spec.identity or not spec.registry:
        raise Stop(EXIT_USAGE, [f"--identity {cand}: the spec names no registry and identity"])
    return spec


def _client(spec: Spec, transport: Optional[httpx.AsyncBaseTransport]):
    from ..identity import Identity
    from ..registry import RegistryClient
    i = spec.identity
    ident = Identity(spec.registry, spec.value(i["agent_did"]), spec.value(i["client_id"]),
                     spec.value(i["client_secret"]), transport=transport)
    return RegistryClient(ident, transport=transport), ident


def _json_of(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _detail(r: httpx.Response) -> str:
    body = _json_of(r)
    if isinstance(body, Mapping):
        d = body.get("detail") or body.get("title") or body.get("message")
        if isinstance(d, (str, int)):
            return f"HTTP {r.status_code}: {d}"
    return f"HTTP {r.status_code}"


def cmd_certify(path: Optional[str], *, identity: Optional[str] = None,
                transport: Optional[httpx.AsyncBaseTransport] = None) -> Answer:
    kit = _kit(path)
    newest: Dict[str, Optional[Dict[str, Any]]] = {}
    for step in reports.STEPS:
        newest[step], why = reports.newest(kit, step)
        if why and "report_sha256 does not hold" in why:
            raise Stop(EXIT_FAILED, [why])
    load, rec = newest["load"], newest["reconcile"]
    problems = []
    if load is None:
        problems.append("no load report: certify follows a load and its reconcile")
    if rec is None:
        problems.append("no reconcile report: run tp-proxy migrate reconcile after the load")
    elif rec.get("verdict") != "pass":
        problems.append(f"the newest reconcile did not pass (verdict {rec.get('verdict')})")
    elif load is not None and str(rec.get("finished_at")) < str(load.get("finished_at")):
        problems.append("the newest reconcile is older than the newest load: reconcile again")
    for step, r in newest.items():
        if r is not None and r.get("template") != kit.template_ref():
            problems.append(f"the newest {step} report is for another version of the kit (its template hash differs)")
    if problems:
        raise Stop(EXIT_FAILED, problems)
    spec = _identity_spec(identity, kit)
    claim = {"template": kit.template_ref(),
             "reports": {s: (r or {}).get("report_sha256") for s, r in newest.items()},
             "verdict": "pass",
             "moved": sum(int(t.get("written", 0)) + int(t.get("unchanged", 0))
                          for t in (load.get("targets") or {}).values()),
             "rejected": sum(int(m.get("rejected", 0)) for m in (load.get("mappings") or {}).values()),
             "finished_at": rec["finished_at"]}
    key = "tpm-" + sha256_hex(canonical(claim))[:40]

    async def go() -> Tuple[int, Dict[str, Any]]:
        client, ident = _client(spec, transport)
        try:
            body = {"target_agent_did": ident.agent_did, "attestation_type": "migration.certificate",
                    "attestation_data": {"claim": claim, "record": key},
                    "metadata": {"proxy": spec.name, "record": key}}
            r = await client.call("POST", ATTESTATION_PATH, json=body, idempotency_key=key)
            ans = _json_of(r)
            if r.status_code not in (200, 201):
                return EXIT_FAILED, {"problems": [f"the attestation was refused: {_detail(r)}"], "claim": claim}
            att = str((ans or {}).get("attestation_id") or "") if isinstance(ans, Mapping) else ""
            # the TEG keeps an attestation as the sha256 of its attestation_data and serves it only to this agent: the
            # exact data is kept beside the id, so the library (and anyone the agent shows it to) can check the hash
            cert = {"attestation_id": att, "attestation_type": body["attestation_type"],
                    "target_agent_did": body["target_agent_did"], "attestation_data": body["attestation_data"],
                    "registry": spec.registry}
            kit.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = kit.state_dir / "certificate.json.tmp"
            tmp.write_text(json.dumps(cert, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(kit.state_dir / "certificate.json")
            out: Dict[str, Any] = {"attestation_id": att, "claim": claim, "claim_sha256": sha256_hex(canonical(claim)),
                                   "certificate": str(kit.state_dir / "certificate.json")}
            got = kit.template or {}
            tid = got.get("id") if "id" in kit.template_ref() else None
            if tid:
                r2 = await client.call("POST", f"{LIBRARY}/{tid}/certified",
                                       json={"attestation_id": att, "attestation_data": body["attestation_data"]},
                                       idempotency_key=f"{key}-certified")
                out["library"] = "counted" if r2.status_code in (200, 201) else _detail(r2)
            elif got.get("id"):
                # the kit came from the library and its files changed since: the certificate is this kit's, not the
                # library version's, so the library's count is not asked (session-tester, seq 4099)
                out["library"] = f"not counted: the kit files differ from version {got.get('version')}"
            else:
                out["library"] = "not counted: a local kit, not a library template (publish it, or get one)"
            return EXIT_OK, out
        finally:
            await client.aclose()
    return asyncio.run(go())


def _registry_url(registry: Optional[str], identity_spec: Optional[Spec]) -> str:
    if registry:
        return registry.rstrip("/")
    if identity_spec is not None:
        return identity_spec.registry
    import os
    return (os.environ.get("TP_PROXY_REGISTRY") or "https://api.theprotocol.cloud").rstrip("/")


def _write_kit(kit_files: Mapping[str, str], out: Path, template: Dict[str, Any], force: bool) -> Kit:
    kit = kit_from_files(kit_files, root=out)
    if out.exists() and any(p for p in out.iterdir() if p.name != STATE_DIR) and not force:
        raise Stop(EXIT_FAILED, [f"{out} is not empty (--force writes over it)"])
    for rel, txt in kit_files.items():
        _put(out / rel, txt)
    (out / STATE_DIR).mkdir(parents=True, exist_ok=True)
    (out / STATE_DIR / "template.json").write_text(json.dumps(template, indent=1) + "\n", encoding="utf-8")
    # the files as they came: what the template itself names stays known whatever the user edits later (M11)
    copy = out / STATE_DIR / TEMPLATE_COPY
    for rel, txt in kit_files.items():
        _put(copy / rel, txt)
    kit.template = template
    return kit


async def _get_kit(tid: str, version: Optional[int], base: str, spec: Optional[Spec],
                   transport: Optional[httpx.AsyncBaseTransport]) -> Dict[str, Any]:
    if spec is not None:
        client, _ = _client(spec, transport)
        call = lambda p: client.call("GET", p)  # noqa: E731
    else:
        client = httpx.AsyncClient(base_url=base, transport=transport, timeout=60.0)
        call = lambda p: client.get(p)  # noqa: E731
    try:
        n = version
        if n is None:
            r = await call(f"{LIBRARY}/{tid}")
            if r.status_code != 200:
                raise Stop(EXIT_FAILED, [f"the template {tid}: {_detail(r)}"])
            listing = _json_of(r) or {}
            listing = listing.get("template", listing) if isinstance(listing, Mapping) else {}
            n = listing.get("current_version")
            if isinstance(n, Mapping):
                n = n.get("version")
            if n is None:
                vs = [v.get("version") for v in listing.get("versions") or [] if isinstance(v, Mapping)]
                n = max([v for v in vs if isinstance(v, int)], default=None)
            if n is None:
                raise Stop(EXIT_FAILED, [f"the template {tid} has no published version"])
        r = await call(f"{LIBRARY}/{tid}/versions/{int(n)}/kit")
        if r.status_code == 402:
            raise Stop(EXIT_FAILED, [f"the template {tid} is paid: buy it first (as the agent --identity names)"
                                     if spec is None else f"the template {tid} is paid and this agent has not bought "
                                                          f"it: {_detail(r)}"])
        if r.status_code != 200:
            raise Stop(EXIT_FAILED, [f"the template {tid} version {n}: {_detail(r)}"])
        doc = _json_of(r)
        if not isinstance(doc, Mapping) or not isinstance(doc.get("files"), Mapping):
            raise Stop(EXIT_FAILED, [f"the template {tid} version {n}: the answer carries no files"])
        return {"files": {str(k): str(v) for k, v in doc["files"].items()}, "content_hash": doc.get("content_hash"),
                "version": int(doc.get("version") or n), "id": str(doc.get("template_id") or tid)}
    finally:
        await client.aclose()


def cmd_get(template: str, *, registry: Optional[str] = None, version: Optional[int] = None,
            out: Optional[str] = None, identity: Optional[str] = None, force: bool = False,
            transport: Optional[httpx.AsyncBaseTransport] = None) -> Answer:
    spec = _identity_spec(identity) if identity else None
    base = _registry_url(registry, spec)
    got = asyncio.run(_get_kit(template, version, base, spec, transport))
    try:
        check = kit_from_files(got["files"])
    except KitError as e:
        raise Stop(EXIT_FAILED, [f"the downloaded kit: {p}" for p in e.problems])
    if not got.get("content_hash") or check.content_hash != got["content_hash"]:
        raise Stop(EXIT_FAILED, [f"the downloaded kit's content hash is {check.content_hash}, the registry says "
                                 f"{got.get('content_hash')}: refused (nothing written)"])
    d = Path(out or check.name or template).resolve()
    tpl = {"id": got["id"], "version": got["version"], "content_hash": check.content_hash, "registry": base}
    kit = _write_kit(got["files"], d, tpl, force)
    return EXIT_OK, {"kit": str(d), "template": kit.template_ref(), "files": sorted(got["files"]),
                     "next": [f"tp-proxy migrate dry-run {d} --sample"]}


def cmd_publish(path: Optional[str], *, identity: Optional[str] = None, visibility: Optional[str] = None,
                price: Optional[float] = None, fork_share_bps: Optional[int] = None, changelog: str = "",
                transport: Optional[httpx.AsyncBaseTransport] = None) -> Answer:
    kit = _kit(path)
    spec = _identity_spec(identity, kit)
    m = kit.manifest
    tid = (kit.template or {}).get("id")

    async def go() -> Answer:
        client, _ = _client(spec, transport)
        try:
            content = {"manifest": m, "files": kit.files}
            if not tid:
                body = {"slug": m["name"], "title": m["title"], "summary": m.get("summary") or "", "kind": "migration",
                        "from_kind": m["from"]["kind"], "to_kind": m["to"]["kind"],
                        "visibility": visibility or "public",
                        "pricing_model": "purchase" if price else "free", "price": price or 0,
                        **({"fork_share_bps": fork_share_bps} if fork_share_bps is not None else {}), **content}
                r = await client.call("POST", LIBRARY, json=body, idempotency_key=f"tpm-create-{kit.content_hash[:40]}")
            else:
                r = await client.call("POST", f"{LIBRARY}/{tid}/versions", json={**content, "changelog": changelog},
                                      idempotency_key=f"tpm-version-{kit.content_hash[:40]}")
            if r.status_code not in (200, 201):
                return EXIT_FAILED, {"problems": [f"the library refused the kit: {_detail(r)}"]}
            ans = _json_of(r) or {}
            new_tid = str(ans.get("template_id") or ans.get("id") or tid or "")
            n = ans.get("version")
            if isinstance(n, Mapping):
                n = n.get("version")
            if not new_tid or n is None:
                return EXIT_FAILED, {"problems": ["the library's answer names no template id and version"]}
            r = await client.call("POST", f"{LIBRARY}/{new_tid}/versions/{int(n)}/publish", json={},
                                  idempotency_key=f"tpm-publish-{new_tid}-{int(n)}")
            if r.status_code not in (200, 201):
                return EXIT_FAILED, {"problems": [f"version {n} was not published: {_detail(r)}"],
                                     "template_id": new_tid}
            if tid and (visibility or price is not None or fork_share_bps is not None):
                patch = {k: v for k, v in (("visibility", visibility), ("price", price),
                                           ("fork_share_bps", fork_share_bps)) if v is not None}
                if price is not None:
                    patch["pricing_model"] = "purchase" if price else "free"
                r = await client.call("PATCH", f"{LIBRARY}/{tid}", json=patch, idempotency_key=f"tpm-patch-{tid}-"
                                      + sha256_hex(canonical(patch))[:16])
                if r.status_code not in (200, 201):
                    return EXIT_FAILED, {"problems": [f"published, but the listing was not changed: {_detail(r)}"]}
            tpl = {"id": new_tid, "version": int(n), "content_hash": kit.content_hash, "registry": spec.registry}
            kit.state_dir.mkdir(parents=True, exist_ok=True)
            (kit.state_dir / "template.json").write_text(json.dumps(tpl, indent=1) + "\n", encoding="utf-8")
            return EXIT_OK, {"template_id": new_tid, "version": int(n), "content_hash": kit.content_hash,
                             "created": not tid}
        finally:
            await client.aclose()
    return asyncio.run(go())


FORK_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,118}$")   # the library's slug rule (section D)


def fork_slug(parent_slug: str) -> str:
    """The default slug of a fork: the parent's with "-fork", cut to the library's 119 characters. The same parent gives
    the same slug every time, so a retry (the same idempotency key) lands on the fork already made."""
    base = (parent_slug or "template").strip("-")[: 119 - len("-fork")].rstrip("-")
    return f"{base}-fork"


def cmd_fork(template: str, *, identity: Optional[str] = None, out: Optional[str] = None, force: bool = False,
             slug: Optional[str] = None, transport: Optional[httpx.AsyncBaseTransport] = None) -> Answer:
    spec = _identity_spec(identity)
    if slug is not None and not FORK_SLUG.match(slug):
        raise Stop(EXIT_FAILED, [f"--slug {slug!r}: a slug is 2 to 119 lowercase letters, digits and '-', starting "
                                 f"with a letter or a digit"])

    async def go() -> str:
        client, _ = _client(spec, transport)
        try:
            want = slug
            if want is None:
                r0 = await client.call("GET", f"{LIBRARY}/{template}")
                if r0.status_code != 200:
                    raise Stop(EXIT_FAILED, [f"the template to fork could not be read: {_detail(r0)}"])
                parent = _json_of(r0) or {}
                want = fork_slug(str(parent.get("slug") or "") if isinstance(parent, Mapping) else "")
            me = spec.value(spec.identity["agent_did"])
            r = await client.call("POST", f"{LIBRARY}/{template}/fork", json={"slug": want},
                                  idempotency_key=f"tpm-fork-{template}-{want}-{me}"[:120])
            if r.status_code == 409 and "slug_taken" in r.text:
                raise Stop(EXIT_FAILED, [f"this agent already has a template with the slug {want!r}: pass --slug "
                                         f"to name the fork"])
            if r.status_code not in (200, 201):
                raise Stop(EXIT_FAILED, [f"the fork was refused: {_detail(r)}"])
            ans = _json_of(r) or {}
            fid = ans.get("template_id") or ans.get("id")
            if not fid:
                raise Stop(EXIT_FAILED, ["the library's answer names no template id for the fork"])
            return str(fid)
        finally:
            await client.aclose()
    fid = asyncio.run(go())
    code, ans = cmd_get(fid, identity=identity, out=out, force=force, transport=transport)
    return code, {"forked_from": template, "template_id": fid, **ans}

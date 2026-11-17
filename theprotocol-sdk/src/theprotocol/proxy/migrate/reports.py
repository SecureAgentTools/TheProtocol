"""The reports (schema theprotocol.migration.report/v1): counts, names and hashes only.

Built from what the runtime keeps (the outbox's rows per mapping and per target, the dead letters' reasons, which name
paths and rules and never a value) plus per-field fill counts read from the mapped rows (filled or null, never what).
Never Outcome.data, never a record value. report_sha256 is the sha256 of the canonical JSON of the report without that
field; a report is written to KIT/.migrate/reports/<step>-<UTC>.json and read back only when its hash holds.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .schema import REPORT_SCHEMA_ID, Kit, canonical, sha256_hex

STEPS = ("inventory", "dry_run", "load", "reconcile")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new(step: str, kit: Kit, *, sample: bool = False) -> Dict[str, Any]:
    return {"schema": REPORT_SCHEMA_ID, "step": step, "sample": bool(sample), "template": kit.template_ref(),
            "started_at": now_iso(), "finished_at": None, "sources": {}, "mappings": {}, "targets": {},
            "batches": [], "reconcile": {}, "verdict": "not_measured"}


def seal(report: Dict[str, Any]) -> Dict[str, Any]:
    report.pop("report_sha256", None)
    if not report.get("finished_at"):
        report["finished_at"] = now_iso()
    report["report_sha256"] = sha256_hex(canonical(report))
    return report


def hash_holds(report: Mapping[str, Any]) -> bool:
    body = {k: v for k, v in report.items() if k != "report_sha256"}
    return report.get("report_sha256") == sha256_hex(canonical(body))


def write(kit: Kit, report: Dict[str, Any]) -> Path:
    seal(report)
    d = kit.state_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    stamp = report["finished_at"].replace(":", "").replace("-", "").replace(".", "")
    p = d / f"{report['step']}-{stamp}.json"
    n = 1
    while p.exists():
        p = d / f"{report['step']}-{stamp}-{n}.json"
        n += 1
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def newest(kit: Kit, step: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(the newest report of `step`, None) or (None, why there is none usable). A report whose hash does not hold is
    named, never used."""
    d = kit.state_dir / "reports"
    best: Optional[Tuple[str, Path]] = None
    for p in d.glob(f"{step}-*.json") if d.is_dir() else ():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, f"{p.name} is not a report (unreadable)"
        if doc.get("step") != step:
            continue
        key = str(doc.get("finished_at") or "")
        if best is None or key > best[0]:
            best = (key, p)
    if best is None:
        return None, f"no {step} report in {d}"
    doc = json.loads(best[1].read_text(encoding="utf-8"))
    if not hash_holds(doc):
        return None, f"{best[1].name}: its report_sha256 does not hold (changed after it was written)"
    return doc, None


# ── counts from the outbox ───────────────────────────────────────────────────────────────────────────────────────────

def mapping_counts(outbox: Any, mappings: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Per mapping: taken, mapped, rejected (a record the mapping could not map: its reason, a path or a rule), the
    reasons counted, and per target field how many rows filled it and how many left it null."""
    out: Dict[str, Dict[str, Any]] = {}
    names = list(mappings)
    for m in names:
        out[m] = {"taken": 0, "mapped": 0, "rejected": 0, "rejected_by_reason": {}, "fields": {}}
    for m, n in outbox._x("SELECT mapping, count(*) FROM outbox GROUP BY mapping").fetchall():
        if m in out:
            out[m]["taken"] = int(n)
    for m, why, n in outbox._x("SELECT mapping, last_error, count(*) FROM outbox WHERE status = 'dead' AND mapped IS "
                               "NULL GROUP BY mapping, last_error").fetchall():
        if m in out:
            out[m]["rejected"] += int(n)
            reason = str(why or "unknown")[:300]
            out[m]["rejected_by_reason"][reason] = out[m]["rejected_by_reason"].get(reason, 0) + int(n)
    for m in names:
        out[m]["mapped"] = out[m]["taken"] - out[m]["rejected"]
    for m, mapped in outbox._x("SELECT mapping, mapped FROM outbox WHERE mapped IS NOT NULL"):
        if m not in out:
            continue
        try:
            doc = json.loads(mapped)
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        fields = out[m]["fields"]
        for f, v in doc.items():
            c = fields.setdefault(str(f), {"filled": 0, "null": 0})
            c["null" if v is None or v == "" else "filled"] += 1
    return out


def target_counts(outbox: Any, targets: Iterable[str], *, scratch: bool) -> Dict[str, Dict[str, Any]]:
    """Per target: rows written, rows the writer found already written (its outcome's detail says so: the writers answer "already written"), rows it refused or gave
    up on, rows still waiting (a retry in its backoff)."""
    out = {t: {"written": 0, "unchanged": 0, "failed": 0, "pending": 0, "scratch": bool(scratch)} for t in targets}
    q = ("SELECT action, status, (mapped IS NULL), "
         "CASE WHEN status = 'done' AND (lower(coalesce(json_extract(outcome, '$.detail'), '')) LIKE 'unchanged%' "
         "OR lower(coalesce(json_extract(outcome, '$.detail'), '')) LIKE 'already written%') "
         "THEN 1 ELSE 0 END, count(*) FROM outbox GROUP BY 1, 2, 3, 4")
    for t, status, unmapped, unchanged, n in outbox._x(q).fetchall():
        if t not in out:
            continue
        n = int(n)
        if status == "done":
            out[t]["unchanged" if unchanged else "written"] += n
        elif status == "dead" and not unmapped:
            out[t]["failed"] += n
        elif status == "pending":
            out[t]["pending"] += n
    return out


def verdict(report: Mapping[str, Any]) -> str:
    """pass: nothing failed or waits, at least one row mapped where rows were taken, and every reconcile passed;
    not_measured when a reconcile could not compare; else fail. Rejected rows are reported, not failed."""
    for t in (report.get("targets") or {}).values():
        if t.get("failed") or t.get("pending"):
            return "fail"
    for m in (report.get("mappings") or {}).values():
        if m.get("taken") and not m.get("mapped"):
            return "fail"
    rec = list((report.get("reconcile") or {}).values())
    if any(r.get("verdict") == "fail" for r in rec):
        return "fail"
    if any(r.get("verdict") == "not_measured" for r in rec):
        return "not_measured"
    return "pass"


def text_lines(report: Mapping[str, Any]) -> List[str]:
    """The report as a person reads it (counts only)."""
    out = [f"{report['step']}{' (sample)' if report.get('sample') else ''}: {report.get('verdict')}"]
    for name, s in (report.get("sources") or {}).items():
        rows = s.get("rows")
        out.append(f"  source {name}: {'not measured' if rows is None else str(rows) + ' rows'}"
                   + (f", fields {', '.join(s.get('fields') or [])}" if s.get("fields") else "")
                   + (f" ({s['why']})" if s.get("why") else ""))
    for name, m in (report.get("mappings") or {}).items():
        out.append(f"  mapping {name}: taken {m.get('taken', 0)}, mapped {m.get('mapped', 0)}, rejected "
                   f"{m.get('rejected', 0)}")
        for why, n in sorted((m.get("rejected_by_reason") or {}).items(), key=lambda kv: -kv[1]):
            out.append(f"    {n} x {why}")
        if m.get("no_source"):
            out.append(f"    target fields no source fills: {', '.join(m['no_source'])}")
        if m.get("unused"):
            out.append(f"    source fields no mapping reads: {', '.join(m['unused'])}")
    for name, t in (report.get("targets") or {}).items():
        out.append(f"  target {name}{' (scratch)' if t.get('scratch') else ''}: written {t.get('written', 0)}, "
                   f"unchanged {t.get('unchanged', 0)}, failed {t.get('failed', 0)}, waiting {t.get('pending', 0)}")
    for name, r in (report.get("reconcile") or {}).items():
        out.append(f"  reconcile {name}: {r.get('verdict')}: source {r.get('source')}, target {r.get('target')}, "
                   f"missing {r.get('missing')}, extra {r.get('extra')}, mismatched {r.get('mismatched')}"
                   + (f" ({r['why']})" if r.get("why") else ""))
    if report.get("restored") is not None:
        out.append(f"  restored {report['restored']} rows")
    return out

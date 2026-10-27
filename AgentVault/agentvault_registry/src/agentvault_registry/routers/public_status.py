"""§STATUSPAGE (2026-09-02) — the public status page's ONE rail.

    GET  /api/v1/public/status              no auth — components + up to 90 days of availability + incidents
    GET  /api/v1/admin/status/incidents     admin_platform — the curated list
    PUT  /api/v1/admin/status/incidents     admin_platform — whole-list replace (validated)

What it is made of, and what it is not:
  * Components come from the registry's OWN `/api/v1/stack-health` probe set (the same snapshot the
    landing page's health wall used to render as a bracket of tiles). The sandbox replicas are internal
    detail and stay off the public page, exactly as the landing page hid them.
  * Availability is Prometheus' `up` metric per scrape job, averaged per UTC day
    (`avg_over_time(up{job=~…}[1d])`). Prometheus keeps 30 days; complete days are appended to
    `status_uptime_days.json` on the durable data volume so the horizon grows past the retention from
    the day this shipped. A component that no job scrapes shows NO history rather than a green bar it
    did not earn. The four renamed operators (§RENAMEFIX) are probed under their ORIGINAL slugs and
    scraped under their NEW ones — the map below is the seam.
  * Incidents are a curated JSON list on the same volume (no migration; one file per registry), written
    only through the admin rail. "Measured dips" — days a component averaged below 99.9% — are derived
    from the metrics and carry no narrative; they are listed separately and say so.
  * Everything is cached in-process (30 s snapshot, 5 min history) so a popular status page costs the
    probes nothing extra.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from agentvault_registry import security
from agentvault_registry.es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Status"])

DATA_DIR = Path(os.getenv("STATUS_DATA_DIR", "/app/data"))
INCIDENTS_FILE = DATA_DIR / "status_incidents.json"
ROLLUP_FILE = DATA_DIR / "status_uptime_days.json"
from ..core.operator_names import scrape_job  # noqa: E402
from ..core.observability_urls import prometheus_url  # noqa: E402
from ..core.frame_slug import frame_slug, slugify  # noqa: E402
from ..core.peer_group import FRAME_ROW_GROUP, fresh_entry_groups, group_rank  # noqa: E402  (E11)
PROM_URL = prometheus_url()   # §FRAMEKIT P3.1: one reader; the old literal (prometheus:9090) resolved on Frame A only
SELF_URL = os.getenv("REGISTRY_SELF_URL", "http://localhost:8000").rstrip("/")
SNAPSHOT_TTL_S = 30
HISTORY_TTL_S = 300
HISTORY_DAYS = 90          # what the page shows at most; Prometheus supplies ≤30, the rollup the rest
DIP_THRESHOLD = 0.999      # a day below this is a "measured dip"

# §SLUGCONVERGE — Prometheus jobs are named after the CONTAINER (op-singapore) while the peer list names the
# IDENTITY (op-losangeles); the ONE map lives in core/operator_names.py and this rail only asks it for the job.

# stack-health name → Prometheus job. Names differ per frame (a frame names its own stack "Registry A" /
# "Frame-C Registry" and its peers "Frame-B" / "Registry-A"); match by shape, case-insensitive.
_NAME_TO_JOB: List[tuple] = [
    (re.compile(r"^registry[ -]?a$", re.I), "registry-a"),
    (re.compile(r"^teg layer a$", re.I), "teg-layer-a"),
    (re.compile(r"^event store$", re.I), "event-store"),
    (re.compile(r"^opa engine$", re.I), "opa"),
    (re.compile(r"^frame-b( registry)?$", re.I), "frame-b-registry"),
    (re.compile(r"^frame-b teg$", re.I), "frame-b-teg"),
    (re.compile(r"^frame-b event store$", re.I), "frame-b-event-store"),
    (re.compile(r"^frame-c( registry)?$", re.I), "frame-c-registry"),
    # §STATUSCOVERAGE (2026-09-02) — these had NO scrape job at all (the page showed grey); Prometheus now
    # scrapes them on their host ports (monitoring/prometheus.yml), so their history starts that day.
    (re.compile(r"^frame-c teg$", re.I), "frame-c-teg"),
    (re.compile(r"^frame-c event store$", re.I), "frame-c-event-store"),
    (re.compile(r"^qatest16$", re.I), "qatest16"),
]


_OWN_COMPONENTS = (("registry", "registry"), ("teg", "teg"), ("event store", "event-store"), ("opa", "opa"))


def job_for_name(name: str, own_label: str = "", own_slug: str = "") -> Optional[str]:
    """The Prometheus job that scrapes this stack-health component, or None (no history).

    §FRAMEKIT P3.1 (2026-09-12): the table above knew the retiring nodes only, so the flagship's public
    status page showed 0 of 90 days on every component (`job: null` on all eight). Two rules that hold for
    every frame the provisioner builds: this frame's OWN components ("<display> Registry" / "<display> TEG"
    / "<display> Event Store" / "<display> OPA") are scraped as `<slug>-registry` / `<slug>-teg` /
    `<slug>-event-store` / `<slug>-opa` (the container prefix, core/frame_slug.py); and a peer or operator
    that arrives under a bare identity ("ASIA", "amsterdam") is scraped as `<identity>-registry`, the job
    sidecars.py writes for every frame and operator registry. A name with spaces that is not our own
    component stays None: an honest "no history" beats a guessed job."""
    n = (name or "").strip()
    for pat, job in _NAME_TO_JOB:
        if pat.match(n):
            return job
    m = re.match(r"^(op-[a-z0-9]+)$", n, re.I)
    if m:
        return scrape_job(m.group(1))
    if own_label and own_slug:
        for word, comp in _OWN_COMPONENTS:
            if n.lower() == f"{own_label.lower()} {word}":
                return f"{own_slug}-{comp}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", n):
        return f"{slugify(n)}-registry"
    return None


def own_identity() -> tuple:
    """(display label, container slug) of this frame — what the stack-health rail names its own tiles by."""
    return ((os.getenv("REGISTRY_NAME") or "").strip(), frame_slug())


def component_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "component"


def is_public_component(svc: Dict[str, Any]) -> bool:
    """Frame A's OLD sandbox replicas ("Sandbox Reg A/B/C", the shared-container tier) were internal detail.
    §FRAMEKIT P3.1: the filter matched `^sandbox` and so dropped a frame NAMED "Sandbox Alpha" from its OWN
    public status page (measured 2026-09-12: three components listed, none of them its own). Match the
    replica names, not the word."""
    return not re.match(r"^sandbox (reg|teg|event store)\b", str(svc.get("name") or ""), re.I)


def overall_state(components: List[Dict[str, Any]]) -> str:
    if not components:
        return "unknown"
    core_down = any(c["group"] == "core" and c["status"] == "down" for c in components)
    any_down = any(c["status"] == "down" for c in components)
    if core_down:
        return "outage"
    if any_down:
        return "degraded"
    return "operational"


def merge_rollup(stored: Dict[str, Dict[str, float]], fresh: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Prometheus is the truth for the days it still holds; the file keeps the days it no longer does."""
    out: Dict[str, Dict[str, float]] = {j: dict(d) for j, d in stored.items()}
    for job, days in fresh.items():
        out.setdefault(job, {}).update(days)
    return out


def measured_dips(components: List[Dict[str, Any]], threshold: float = DIP_THRESHOLD) -> List[Dict[str, Any]]:
    dips = []
    for c in components:
        for d in c.get("days") or []:
            up = d.get("up")
            if up is not None and up < threshold:
                dips.append({"date": d["date"], "component_key": c["key"], "name": c["name"], "up": round(up, 5)})
    dips.sort(key=lambda x: (x["date"], x["name"]), reverse=True)
    return dips[:60]


# ────────────────────────────── incidents (curated, on the durable volume) ──────────────────────────────
class IncidentUpdate(BaseModel):
    at: datetime
    status: str = Field(pattern=r"^(investigating|identified|monitoring|resolved|scheduled|completed)$")
    text: str = Field(min_length=1, max_length=2000)


class Incident(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1, max_length=200)
    impact: str = Field(pattern=r"^(minor|major|critical|maintenance)$")
    status: str = Field(pattern=r"^(investigating|identified|monitoring|resolved|scheduled|completed)$")
    components: List[str] = Field(default_factory=list, max_length=40)
    started_at: datetime
    resolved_at: Optional[datetime] = None
    updates: List[IncidentUpdate] = Field(default_factory=list, max_length=100)

    @field_validator("resolved_at")
    @classmethod
    def _resolved_after_start(cls, v, info):
        st = info.data.get("started_at")
        if v is not None and st is not None and v < st:
            raise ValueError("resolved_at precedes started_at")
        return v


class IncidentList(BaseModel):
    incidents: List[Incident] = Field(default_factory=list, max_length=500)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except Exception as e:  # a corrupt file is a defect worth a log line, never a 500 on the public page
        logger.warning("status: could not read %s: %s", path, e)
        return default


def _write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, default=str, indent=1))
    os.replace(tmp, path)


def load_incidents() -> List[Dict[str, Any]]:
    raw = _read_json(INCIDENTS_FILE, [])
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            out.append(json.loads(Incident.model_validate(item).model_dump_json()))
        except Exception as e:
            logger.warning("status: skipping malformed incident %r: %s", (item or {}).get("id") if isinstance(item, dict) else item, e)
    out.sort(key=lambda i: i["started_at"], reverse=True)
    return out


# ────────────────────────────── live snapshot + history ──────────────────────────────
_cache: Dict[str, Any] = {"snapshot": None, "snapshot_at": 0.0, "history": None, "history_at": 0.0}
_lock = asyncio.Lock()


async def _stack_health() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.get(f"{SELF_URL}/api/v1/stack-health")
        r.raise_for_status()
        return r.json()


def _day_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


async def _prom_days(jobs: List[str]) -> Dict[str, Dict[str, float]]:
    """{job: {"YYYY-MM-DD": mean up}} for every COMPLETE UTC day Prometheus still holds, plus today so far."""
    if not jobs:
        return {}
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=HISTORY_DAYS)
    # PromQL regexes are RE2: `re.escape` writes `op\-berlin`, which Prometheus answers with 400. Job names
    # are plain slugs; keep only the characters a job name can carry and quote nothing.
    sel = "|".join(j for j in sorted(set(jobs)) if re.fullmatch(r"[A-Za-z0-9_.-]+", j))
    out: Dict[str, Dict[str, float]] = {}
    async with httpx.AsyncClient(timeout=20.0, verify=get_httpx_verify()) as client:
        # complete days: evaluated at each midnight, each point averages the 24 h that ended there
        r = await client.get(f"{PROM_URL}/api/v1/query_range", params={
            "query": f'avg_over_time(up{{job=~"{sel}"}}[1d])',
            "start": (start + timedelta(days=1)).timestamp(), "end": midnight.timestamp(), "step": 86400})
        r.raise_for_status()
        for series in r.json().get("data", {}).get("result", []):
            job = series.get("metric", {}).get("job")
            if not job:
                continue
            days = out.setdefault(job, {})
            for ts, val in series.get("values", []):
                day = _day_str(float(ts) - 1)  # the point at midnight describes the day that ENDED there
                try:
                    v = float(val)
                except ValueError:
                    continue
                days[day] = max(days.get(day, 0.0), v) if day in days else v
        # today so far
        secs = max(60, int((now - midnight).total_seconds()))
        r2 = await client.get(f"{PROM_URL}/api/v1/query", params={"query": f'avg_over_time(up{{job=~"{sel}"}}[{secs}s])'})
        r2.raise_for_status()
        for series in r2.json().get("data", {}).get("result", []):
            job = series.get("metric", {}).get("job")
            try:
                v = float(series["value"][1])
            except Exception:
                continue
            if job:
                out.setdefault(job, {})[_day_str(now.timestamp())] = v
    return out


async def _history(jobs: List[str]) -> Dict[str, Any]:
    now = time.time()
    if _cache["history"] is not None and now - _cache["history_at"] < HISTORY_TTL_S:
        return _cache["history"]
    stored = _read_json(ROLLUP_FILE, {})
    if not isinstance(stored, dict):
        stored = {}
    source = "prometheus:up"
    try:
        fresh = await _prom_days(jobs)
    except Exception as e:
        logger.info("status: prometheus unavailable (%s) — history from the rollup file only", str(e)[:120])
        fresh, source = {}, "rollup-file"
    merged = merge_rollup(stored, fresh)
    if fresh:
        today = _day_str(now)
        complete = {j: {d: v for d, v in days.items() if d != today} for j, days in fresh.items()}
        if any(complete.values()) and merge_rollup(stored, complete) != stored:
            try:
                _write_json_atomic(ROLLUP_FILE, merge_rollup(stored, complete))
            except Exception as e:
                logger.warning("status: could not persist the uptime rollup: %s", e)
    hist = {"days": merged, "source": source}
    _cache["history"], _cache["history_at"] = hist, now
    return hist


def _shape_component(svc: Dict[str, Any], hist_days: Dict[str, Dict[str, float]], day_list: List[str]) -> Dict[str, Any]:
    name = str(svc.get("name") or "")
    job = str(svc.get("job") or "") or job_for_name(name, *own_identity())  # §BATCH7: synthetic components carry their job
    series = hist_days.get(job or "", {})
    days = [{"date": d, "up": (round(series[d], 5) if d in series else None)} for d in day_list]
    known = [d["up"] for d in days if d["up"] is not None]
    avail = round(sum(known) / len(known), 5) if known else None
    return {
        "key": component_key(name), "name": name, "group": str(svc.get("group") or "core"),
        "status": "up" if svc.get("status") == "healthy" else ("down" if svc.get("status") else "unknown"),
        "latency_ms": svc.get("ms"), "public_url": svc.get("publicUrl"), "job": job,
        "infra_label": svc.get("infra_label"),
        "availability": avail, "days_known": len(known), "days": days,
    }


def dedupe_by_job(services: List[Dict[str, Any]], own_label: str = "", own_slug: str = "") -> List[Dict[str, Any]]:
    """§FRAMEKIT P3.1 (2026-09-12): a frame whose FRESH_NETWORK_JSON names ITSELF (the driver writes the frame's own
    tile beside its peers, findings row 178) lists every own component TWICE on its status page — "EU Registry"
    from stack-health and "EU registry" from the synthetic list — and, once both resolve to the job `eu-registry`,
    twice with the same history (measured on the flagship: 8 + 10 rows for 8 components). One row per job: the
    first wins, and stack-health rows come first (they carry the live probe latency)."""
    # E11 (2026-09-13): the first row per job wins ONLY among rows of the same rank; a row with a known group (core,
    # frame, operator) displaces one that carries a label (sandbox, peer, none), whichever came first.
    best: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for svc in services:
        job = str(svc.get("job") or "") or job_for_name(str(svc.get("name") or ""), own_label, own_slug)
        if not job:
            out.append(svc)
            continue
        rank = group_rank(svc.get("group"))
        if job in best:
            if rank < best[job]:
                out[best[job + ":idx"]] = svc  # type: ignore[index]
                best[job] = rank
            continue
        best[job] = rank
        best[job + ":idx"] = len(out)
        out.append(svc)
    return out


# §RESIDUES C1 (2026-09-13): a FRESH_NETWORK_JSON entry that names no group is a PEER frame's components, not
# "sandbox" — the flagship rendered ASIA's TEG and Event Store under a `sandbox` heading (the 09-07 standup's
# env label bled into a public page). E11 (the same day, measured after the V0359 roll): the flagship's env
# DECLARES "sandbox" on every frame entry, so a default was not enough; the entry's ROLE decides (core/peer_group.py).
FRESH_DEFAULT_GROUP = FRAME_ROW_GROUP


def _fresh_network_components() -> List[Dict[str, Any]]:
    """[{name, job, publicUrl, group}] from FRESH_NETWORK_JSON — the frames' registry/ES/TEG and their operators."""
    raw = (os.getenv("FRESH_NETWORK_JSON", "") or "").strip()
    if not raw:
        return []
    try:
        frames = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    for f in frames if isinstance(frames, list) else []:
        name = str(f.get("name") or ""); slug = str(f.get("slug") or name.lower())
        if not name:
            continue
        # §AGORASIM-2: an entry filed under the sandbox ledger strip is a window onto the test frames' ledger on the
        # landing page, not a component of this frame's network; the public status page keeps its 0 sandbox rows.
        if str(f.get("strip") or "").strip().lower() == "sandbox":
            continue
        console = f.get("console") or f.get("registry_url")
        frame_group, operator_group = fresh_entry_groups(f)
        for label, job in ((f"{name} registry", f"{slug}-registry"), (f"{name} EventStore", f"{slug}-event-store"), (f"{name} TEG", f"{slug}-teg")):
            out.append({"name": label, "job": job, "publicUrl": console, "group": frame_group})
        for op in f.get("operators") or []:
            out.append({"name": f"{name} operator {op}", "job": f"{op}-registry", "publicUrl": f"https://{op}.op.theprotocol.cloud", "group": operator_group})
    return out


async def _fresh_network_services() -> List[Dict[str, Any]]:
    comps = _fresh_network_components()
    if not comps:
        return []
    jobs = [c["job"] for c in comps]
    sel = "|".join(j for j in sorted(set(jobs)) if re.fullmatch(r"[A-Za-z0-9_.-]+", j))
    up_now: Dict[str, float] = {}
    async with httpx.AsyncClient(timeout=6.0, verify=get_httpx_verify()) as client:
        r = await client.get(f"{PROM_URL}/api/v1/query", params={"query": f'up{{job=~"{sel}"}}'})
        if r.status_code == 200:
            for series in (r.json().get("data") or {}).get("result") or []:
                job = (series.get("metric") or {}).get("job")
                try:
                    up_now[job] = float((series.get("value") or [0, "0"])[1])
                except Exception:  # noqa: BLE001
                    pass
    for c in comps:
        v = up_now.get(c["job"])
        c["status"] = "healthy" if v == 1.0 else ("unhealthy" if v is not None else None)
    return comps


async def build_status() -> Dict[str, Any]:
    now = time.time()
    async with _lock:
        if _cache["snapshot"] is not None and now - _cache["snapshot_at"] < SNAPSHOT_TTL_S:
            return _cache["snapshot"]
        checked_at = datetime.now(timezone.utc)
        try:
            sh = await _stack_health()
            services = [s for s in (sh.get("services") or []) if is_public_component(s)]
        except Exception as e:
            logger.warning("status: stack-health unavailable: %s", str(e)[:120])
            services = []
        # §BATCH7 — the fresh network on the status page: one component per frame service + operator, from
        # FRESH_NETWORK_JSON (name, jobs); live status = the latest Prometheus `up` sample of the job, history = the
        # same per-job days as every other component. Nothing here probes the fresh frames from this process.
        try:
            fresh_services = await _fresh_network_services()
        except Exception as e:  # noqa: BLE001
            logger.warning("status: fresh-network components unavailable: %s", str(e)[:120])
            fresh_services = []
        _own = own_identity()
        services = dedupe_by_job(services + fresh_services, *_own)
        jobs = [j for j in ((str(s.get("job") or "") or job_for_name(str(s.get("name") or ""), *_own)) for s in services) if j]
        hist = await _history(jobs)
        today = checked_at.replace(hour=0, minute=0, second=0, microsecond=0)
        day_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(HISTORY_DAYS - 1, -1, -1)]
        components = [_shape_component(s, hist["days"], day_list) for s in services]
        all_known = sorted({d for j in hist["days"].values() for d in j.keys()})
        snap = {
            "generated_at": checked_at.isoformat(), "checked_at": checked_at.isoformat(),
            "registry": os.getenv("REGISTRY_NAME") or os.getenv("REGISTRY_DISPLAY_NAME") or "",
            "overall": overall_state(components), "components": components,
            "history": {"window_days": HISTORY_DAYS, "since": (all_known[0] if all_known else None),
                        "source": hist["source"], "dip_threshold": DIP_THRESHOLD},
            "measured_dips": measured_dips(components),
            "incidents": load_incidents(),
        }
        _cache["snapshot"], _cache["snapshot_at"] = snap, now
        return snap


@router.get("/public/status", summary="Public status page data (components, daily availability for up to 90 days, incidents)")
async def public_status():
    return await build_status()


@router.get("/admin/status/incidents", summary="The curated incident list (admin)")
async def admin_incidents(_admin=Depends(security.require_admin_flag("admin_platform"))):
    return {"incidents": load_incidents(), "file": str(INCIDENTS_FILE)}


@router.put("/admin/status/incidents", summary="Replace the curated incident list (admin, validated)")
async def admin_put_incidents(body: IncidentList, _admin=Depends(security.require_admin_flag("admin_platform"))):
    ids = [i.id for i in body.incidents]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate incident ids")
    try:
        _write_json_atomic(INCIDENTS_FILE, [json.loads(i.model_dump_json()) for i in body.incidents])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"could not write the incident list: {e}")
    _cache["snapshot"] = None
    return {"incidents": load_incidents(), "written": len(ids)}

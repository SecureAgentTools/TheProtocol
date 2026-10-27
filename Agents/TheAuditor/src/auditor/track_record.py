"""§MEMBERSHIP phase D1 (2026-10-02, agentvault2-33): the registry track record, measured from outside and signed here.

A daily 0-100 score per registry (a frame or a cloud operator) over the trailing 30 days. Design:
sessionlogs2026/DESIGN_2026-10-02_STAKING_REPLACEMENT.md section 4.2; contract: PLAN_2026-10-02_MEMBERSHIP_COMMONS.md 2.6.

Four components, each from something public or observed by this auditor itself:
  integrity     this auditor's own audit rows for the ledger the registry writes to (an operator: its parent's), by the
                one rule in database.py (OK_SQL / BREACH_SQL); unreadable cycles are counted apart, never as a breach;
                capped at 0.5 when only public readings exist or a breach stayed open more than 24 hours
  availability  this auditor's probes of the registry's public /health and card: both answered, and the card parsed
  promises      the card's own commitments against those probes (uptime, card freshness, signing-key age)
  conduct       days the registry's licence was listed active by its issuer AND its network-locked parameters equalled
                the network root's (a frame may amend its own policy; the locked parameters are the network's)
Never an input: Units held, locked or paid; AGORA points; peer verdicts; anything a registry can buy. Never an input TO
anything that pays: a score that pays stops being a measurement.

OFF unless the carrier file exists and names registries (AUDITOR_TRACK_RECORD_FILE, default frames/track_record.json,
read-only on the frames mount). It is re-read every cycle, so an edit takes effect without a recreate. Each record is
signed into its OWN chain, `track_record:<registry>`, never into a frame's audit chain. The loop never raises into the
audit loop: a failed cycle is logged and the next one runs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
import httpx

from . import attest
from . import database as db

logger = logging.getLogger(__name__)

FORMULA_VERSION = "tr-1"
WEIGHTS = {"integrity": 40, "availability": 30, "promises": 20, "conduct": 10}
WINDOW_DAYS = 30
PROVISIONAL_DAYS = 14
CARD_FRESH_SHARE = 0.99          # card_refresh_max_minutes holds when at least this share of card reads was fresh
BREACH_OPEN_CAP_HOURS = 24
CAP_PUBLIC_ONLY = 0.5
CAP_LONG_BREACH = 0.5
PROBE_KEEP_DAYS = 90
NOT_MEASURABLE = ("support_response_hours", "incident_disclosure_sla_hours", "deprecation_notice_days",
                  "data_residency", "gdpr_compliant", "breach_disclosure_policy")
CHAIN_PREFIX = "track_record:"


def carrier_path() -> Path:
    return Path(os.getenv("AUDITOR_TRACK_RECORD_FILE", "/app/frames/track_record.json"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v or not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load_carrier(path: Optional[Path] = None) -> Dict[str, Any]:
    """{"registries": [...], "network_base": str, "probe_seconds": int, "compute_after": "HH:MM"}, or {} (off).

    An unparsable carrier applies nothing (and says so), exactly like the extra-frames carrier."""
    path = path or carrier_path()
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("[TRACK] carrier %s unreadable (%s): nothing applied", path, e)
        return {}
    network = str(d.get("network_base") or "").rstrip("/")
    regs: List[Dict[str, Any]] = []
    seen = set()
    for e in d.get("registries") or []:
        if not isinstance(e, dict):
            continue
        name, base = str(e.get("name") or "").strip(), str(e.get("base") or "").rstrip("/")
        if not name or not base.startswith("https://") or name in seen:
            logger.warning("[TRACK] carrier entry skipped (a name, a unique one, and an https base are required): %r", e)
            continue
        seen.add(name)
        # §MEMBERSHIP (2026-10-03, production joined the sandbox in one carrier): each entry may name its OWN network
        # root, so a registry's locked parameters are compared with ITS network's, never another's; the file's
        # network_base is the default.
        regs.append({"name": name, "kind": "operator" if e.get("kind") == "operator" else "frame", "base": base,
                     "frame": str(e.get("frame") or "") or None,
                     "issuer_base": str(e.get("issuer_base") or network or base).rstrip("/"),
                     "network_base": str(e.get("network_base") or network or "").rstrip("/") or None})
    try:
        probe_seconds = max(60, int(d.get("probe_seconds") or 300))
    except (TypeError, ValueError):
        probe_seconds = 300
    return {"registries": regs, "network_base": network or None, "probe_seconds": probe_seconds,
            "compute_after": str(d.get("compute_after") or "00:30")}


# ── storage ─────────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS tr_probes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, registry TEXT NOT NULL, ts TEXT NOT NULL,
                health_status INTEGER, card_status INTEGER, card_ok INTEGER NOT NULL DEFAULT 0,
                signed_at TEXT, kid TEXT, commitments TEXT,
                licence_ok INTEGER, locked_ok INTEGER, licence_detail TEXT, ms INTEGER, error TEXT)""")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_tr_probes_reg_ts ON tr_probes (registry, ts)")
        await c.execute("""
            CREATE TABLE IF NOT EXISTS tr_kids (
                registry TEXT NOT NULL, kid TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                PRIMARY KEY (registry, kid))""")
        await c.execute("""
            CREATE TABLE IF NOT EXISTS tr_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT, registry TEXT NOT NULL, day TEXT NOT NULL,
                computed_at TEXT NOT NULL, score REAL, provisional INTEGER NOT NULL, observed_days INTEGER NOT NULL,
                formula_version TEXT NOT NULL, record TEXT NOT NULL, attestation_id INTEGER)""")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_tr_records_reg ON tr_records (registry, id)")
        await c.commit()


async def _store_probe(row: Dict[str, Any]) -> None:
    cols = ("registry", "ts", "health_status", "card_status", "card_ok", "signed_at", "kid", "commitments",
            "licence_ok", "locked_ok", "licence_detail", "ms", "error")
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        await c.execute(f"INSERT INTO tr_probes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        tuple(row.get(k) for k in cols))
        if row.get("kid"):
            await c.execute(
                "INSERT INTO tr_kids (registry, kid, first_seen, last_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(registry, kid) DO UPDATE SET last_seen = excluded.last_seen",
                (row["registry"], row["kid"], row["ts"], row["ts"]))
        await c.commit()


# ── observation ─────────────────────────────────────────────────────────────

async def _get_json(client: httpx.AsyncClient, url: str):
    """(status, the JSON document or None, an error or None)."""
    try:
        r = await client.get(url)
    except Exception as e:  # noqa: BLE001 — a transport failure is a state of this read
        return None, None, f"{type(e).__name__}: {str(e)[:100]}"
    try:
        return r.status_code, r.json(), None
    except ValueError:
        return r.status_code, None, None


def _licence_entry(listing: Optional[dict], lic_hash: Optional[str]) -> Optional[dict]:
    if not lic_hash or not isinstance(listing, dict):
        return None
    for e in ((listing.get("payload") or {}).get("licences") or []):
        h = str(e.get("hash") or "")
        if h and (h == lic_hash or (len(h) >= 16 and lic_hash.startswith(h))):
            return e
    return None


def licence_verdict(kind: str, own_doc: Optional[dict], issuer_list: Optional[dict], now: datetime):
    """(ok True/False/None, detail). The registry's OWN licence: a frame's is the document's; an operator's is the
    document's `operator` block (the top level of an operator's document is its frame's licence). None = not readable."""
    if not isinstance(own_doc, dict) or not isinstance(issuer_list, dict):
        return None, "unreadable"
    block = own_doc.get("operator") if kind == "operator" else own_doc
    if not isinstance(block, dict) or not block.get("hash"):
        return False, "no licence published"
    entry = _licence_entry(issuer_list, str(block["hash"]))
    if entry is None:
        return False, "not listed by its issuer"
    state = str(entry.get("state") or "")
    exp = entry.get("exp")
    expired = False
    if exp not in (None, "", "None"):
        try:
            expired = int(float(exp)) <= int(now.timestamp())
        except (TypeError, ValueError):
            expired = False
    if state != "active":
        return False, f"listed {state or 'without a state'}"
    if expired:
        return False, "expired"
    return True, "listed active"


async def probe_registry(client: httpx.AsyncClient, reg: Dict[str, Any], issuer_lists: Dict[str, Any],
                         network_locked: Optional[str]) -> Dict[str, Any]:
    t0 = time.monotonic()
    row: Dict[str, Any] = {"registry": reg["name"], "ts": _now().isoformat(), "card_ok": 0}
    errors = []
    st, _body, err = await _get_json(client, f"{reg['base']}/health")
    row["health_status"] = st
    if err:
        errors.append(f"health {err}")
    st, card, err = await _get_json(client, f"{reg['base']}/.well-known/registry-card.json")
    row["card_status"] = st
    if err:
        errors.append(f"card {err}")
    locked = None
    if st == 200 and isinstance(card, dict) and isinstance(card.get("signature"), dict) and isinstance(card.get("identity"), dict):
        row["card_ok"] = 1
        row["signed_at"] = card["signature"].get("signed_at")
        row["kid"] = card["signature"].get("kid")
        row["commitments"] = json.dumps(card.get("commitments") or {}, sort_keys=True)
        locked = (card.get("policy") or {}).get("locked_params_hash") if isinstance(card.get("policy"), dict) else None
    st, own, err = await _get_json(client, f"{reg['base']}/.well-known/federation-licence.json")
    ok, detail = licence_verdict(reg["kind"], own if st == 200 else None, issuer_lists.get(reg["issuer_base"]), _now())
    row["licence_ok"] = None if ok is None else int(ok)
    row["licence_detail"] = detail
    row["locked_ok"] = None if (not locked or not network_locked) else int(locked == network_locked)
    row["ms"] = int((time.monotonic() - t0) * 1000)
    row["error"] = "; ".join(errors)[:500] or None
    return row


async def probe_all(cfg: Dict[str, Any], client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    regs = cfg.get("registries") or []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=10.0, follow_redirects=False,
                                   headers={"User-Agent": "theprotocol-auditor/track-record"})
    try:
        issuer_lists: Dict[str, Any] = {}
        for base in sorted({r["issuer_base"] for r in regs}):
            st, doc, _ = await _get_json(client, f"{base}/.well-known/federation-licences.json")
            issuer_lists[base] = doc if st == 200 else None
        # one read per network root; each registry is compared with its own root (an entry without one takes the file's)
        roots = {(r.get("network_base") or cfg.get("network_base") or "").rstrip("/") for r in regs} - {""}
        network_locked_by_root: Dict[str, Optional[str]] = {}
        for root in sorted(roots):
            st, card, _ = await _get_json(client, f"{root}/.well-known/registry-card.json")
            network_locked_by_root[root] = (card["policy"].get("locked_params_hash")
                                            if st == 200 and isinstance(card, dict) and isinstance(card.get("policy"), dict)
                                            else None)
        rows = []
        for reg in regs:
            root = (reg.get("network_base") or cfg.get("network_base") or "").rstrip("/")
            row = await probe_registry(client, reg, issuer_lists, network_locked_by_root.get(root))
            await _store_probe(row)
            rows.append(row)
        return rows
    finally:
        if own:
            await client.aclose()


# ── the score (pure) ────────────────────────────────────────────────────────

def _r(v: Optional[float], n: int = 4) -> Optional[float]:
    return None if v is None else round(float(v), n)


def integrity_component(counts: Optional[Dict[str, Any]], long_breach: bool) -> Dict[str, Any]:
    """counts: {ok, breach, total, public_only} for the ledger in the window, or None (no ledger known)."""
    if not counts:
        return {"value": None, "reason": "no ledger audited by this auditor for this registry"}
    ok, breach, total = int(counts.get("ok") or 0), int(counts.get("breach") or 0), int(counts.get("total") or 0)
    out: Dict[str, Any] = {"ok_cycles": ok, "breach_cycles": breach, "unread_cycles": max(0, total - ok - breach),
                           "source": "public" if counts.get("public_only") else "audit"}
    if ok + breach == 0:
        out.update(value=None, reason="no readable audit cycle in the window")
        return out
    value, caps = ok / (ok + breach), []
    if counts.get("public_only"):
        caps.append(("public readings only", CAP_PUBLIC_ONLY))
    if long_breach:
        caps.append((f"a breach stayed open more than {BREACH_OPEN_CAP_HOURS} hours", CAP_LONG_BREACH))
    for why, cap in caps:
        if value > cap:
            value = cap
            out["cap_reason"] = why
    out["value"] = _r(value)
    return out


def availability_component(probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(probes)
    answered = sum(1 for p in probes if p.get("health_status") == 200 and p.get("card_status") == 200 and p.get("card_ok"))
    return {"value": _r(answered / n) if n else None, "probes": n, "answered": answered}


def promises_component(probes: List[Dict[str, Any]], kids: Dict[str, str], availability: Optional[float],
                       now: datetime) -> Dict[str, Any]:
    latest = next((p for p in sorted(probes, key=lambda p: p.get("ts") or "", reverse=True) if p.get("card_ok")), None)
    if latest is None:
        return {"value": None, "reason": "no card read in the window", "measured": [], "not_measured": []}
    try:
        commitments = json.loads(latest.get("commitments") or "{}")
    except ValueError:
        commitments = {}
    measured, not_measured = [], sorted(k for k in commitments if k in NOT_MEASURABLE)
    sla = commitments.get("uptime_sla_pct")
    if isinstance(sla, (int, float)) and availability is not None:
        measured.append({"commitment": "uptime_sla_pct", "declared": sla, "observed": _r(availability * 100, 3),
                         "held": availability * 100 >= float(sla)})
    fresh = commitments.get("card_refresh_max_minutes")
    if isinstance(fresh, (int, float)):
        ages = []
        for p in probes:
            if p.get("card_ok"):
                t, s = _parse_ts(p.get("ts")), _parse_ts(p.get("signed_at"))
                if t and s:
                    ages.append((t - s).total_seconds() / 60.0)
        if ages:
            share = sum(1 for a in ages if a <= float(fresh)) / len(ages)
            measured.append({"commitment": "card_refresh_max_minutes", "declared": fresh,
                             "observed": {"fresh_share": _r(share), "reads": len(ages)}, "held": share >= CARD_FRESH_SHARE})
    rot = commitments.get("key_rotation_max_days")
    kid = latest.get("kid")
    first = _parse_ts(kids.get(kid)) if kid else None
    if isinstance(rot, (int, float)) and first is not None:
        age_days = (now - first).total_seconds() / 86400.0
        measured.append({"commitment": "key_rotation_max_days", "declared": rot,
                         "observed": {"kid": kid, "seen_for_days": _r(age_days, 2)}, "held": age_days <= float(rot)})
    held = sum(1 for m in measured if m["held"])
    return {"value": _r(held / len(measured)) if measured else None, "measured": measured, "not_measured": not_measured}


def conduct_component(probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A day counts when it has at least one readable observation; it is good when every readable one held."""
    days: Dict[str, List[bool]] = {}
    licence_bad, drift = set(), set()
    for p in probes:
        lo, ko = p.get("licence_ok"), p.get("locked_ok")
        if lo is None and ko is None:
            continue
        day = (p.get("ts") or "")[:10]
        good = (lo is None or bool(lo)) and (ko is None or bool(ko))
        days.setdefault(day, []).append(good)
        if lo is not None and not lo:
            licence_bad.add(day)
        if ko is not None and not ko:
            drift.add(day)
    counted = len(days)
    good_days = sum(1 for v in days.values() if all(v))
    return {"value": _r(good_days / counted) if counted else None, "days_counted": counted, "days_good": good_days,
            "licence_bad_days": len(licence_bad), "locked_drift_days": len(drift),
            "not_measured": ["quarantine (not public)"]}


def score_record(*, reg: Dict[str, Any], now: datetime, integrity_counts: Optional[Dict[str, Any]], long_breach: bool,
                 probes: List[Dict[str, Any]], kids: Dict[str, str]) -> Dict[str, Any]:
    start = now - timedelta(days=WINDOW_DAYS)
    integrity = integrity_component(integrity_counts, long_breach)
    availability = availability_component(probes)
    promises = promises_component(probes, kids, availability["value"], now)
    conduct = conduct_component(probes)
    comps = {"integrity": integrity, "availability": availability, "promises": promises, "conduct": conduct}
    measured = {k: c["value"] for k, c in comps.items() if c.get("value") is not None}
    weight_sum = sum(WEIGHTS[k] for k in measured)
    score = _r(100.0 * sum(WEIGHTS[k] * v for k, v in measured.items()) / weight_sum, 1) if weight_sum else None
    observed_days = len({(p.get("ts") or "")[:10] for p in probes if p.get("ts")})
    return {
        "registry": reg["name"], "registry_kind": reg["kind"], "base": reg["base"], "ledger": reg.get("frame"),
        "computed_at": now.isoformat(), "window": {"start": start.isoformat(), "end": now.isoformat(), "days": WINDOW_DAYS},
        "formula_version": FORMULA_VERSION, "weights": dict(WEIGHTS), "components": comps,
        "score": score, "renormalised": weight_sum not in (0, sum(WEIGHTS.values())),
        "observed_days": observed_days, "provisional": observed_days < PROVISIONAL_DAYS,
    }


# ── reads for the score ─────────────────────────────────────────────────────

async def _integrity_counts(frame: Optional[str], since: str) -> Optional[Dict[str, Any]]:
    if not frame:
        return None
    q = (f"SELECT SUM(CASE WHEN {db.OK_SQL} THEN 1 ELSE 0 END), SUM(CASE WHEN {db.BREACH_SQL} THEN 1 ELSE 0 END), COUNT(*) "
         "FROM audit_history WHERE frame = ? AND timestamp >= ? AND COALESCE(source, 'audit') = ?")
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        audit = await (await c.execute(q, (frame, since, "audit"))).fetchone()
        if audit and audit[2]:
            return {"ok": audit[0] or 0, "breach": audit[1] or 0, "total": audit[2], "public_only": False}
        public = await (await c.execute(q, (frame, since, "public"))).fetchone()
        if public and public[2]:
            return {"ok": public[0] or 0, "breach": public[1] or 0, "total": public[2], "public_only": True}
    return None


async def _long_breach(frame: Optional[str], since: str, now: datetime) -> bool:
    if not frame:
        return False
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        rows = await (await c.execute(
            "SELECT detected_at, resolved_at FROM breaches WHERE frame = ? AND COALESCE(kind, 'supply') IN ('supply', 'public') "
            "AND (resolved_at IS NULL OR resolved_at >= ?)", (frame, since))).fetchall()
    for detected, resolved in rows:
        d0, d1 = _parse_ts(detected), _parse_ts(resolved) or now
        if d0 and (d1 - d0) > timedelta(hours=BREACH_OPEN_CAP_HOURS):
            return True
    return False


async def _window_probes(name: str, since: str) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        c.row_factory = aiosqlite.Row
        rows = await (await c.execute(
            "SELECT ts, health_status, card_status, card_ok, signed_at, kid, commitments, licence_ok, locked_ok "
            "FROM tr_probes WHERE registry = ? AND ts >= ? ORDER BY ts", (name, since))).fetchall()
        return [dict(r) for r in rows]


async def _kids(name: str) -> Dict[str, str]:
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        rows = await (await c.execute("SELECT kid, first_seen FROM tr_kids WHERE registry = ?", (name,))).fetchall()
    return {k: f for k, f in rows}


# ── compute, sign, keep ─────────────────────────────────────────────────────

async def compute_and_record(reg: Dict[str, Any], key, lock: asyncio.Lock, version: str,
                             now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    rec = score_record(reg=reg, now=now, integrity_counts=await _integrity_counts(reg.get("frame"), since),
                       long_breach=await _long_breach(reg.get("frame"), since, now),
                       probes=await _window_probes(reg["name"], since), kids=await _kids(reg["name"]))
    att_id = None
    if key is not None:
        body = {"standard": attest.STANDARD, "kind": "track_record", "auditor_version": version, **rec}
        chain = CHAIN_PREFIX + reg["name"]
        async with lock:
            prev = await db.get_attestation_head(chain) or ""
            body["prev_hash"] = prev
            payload = attest.canonical_json(body)
            att_id = await db.record_attestation(frame=chain, ts=rec["computed_at"], kind="track_record",
                                                 payload=payload, digest=attest.AttestKey.digest(payload),
                                                 prev_hash=prev, signature=key.sign(payload), kid=key.kid)
    rec["attestation_id"] = att_id
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        await c.execute(
            "INSERT INTO tr_records (registry, day, computed_at, score, provisional, observed_days, formula_version, record, "
            "attestation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (reg["name"], rec["computed_at"][:10], rec["computed_at"], rec["score"], int(rec["provisional"]),
             rec["observed_days"], FORMULA_VERSION, json.dumps(rec, sort_keys=True), att_id))
        await c.commit()
    return rec


def _compute_due_at(day: datetime, compute_after: str) -> datetime:
    try:
        hh, mm = (int(x) for x in compute_after.split(":", 1))
    except ValueError:
        hh, mm = 0, 30
    return day.replace(hour=hh % 24, minute=mm % 60, second=0, microsecond=0)


async def compute_due(cfg: Dict[str, Any], key, lock: asyncio.Lock, version: str) -> List[str]:
    """One record per registry per UTC day, after `compute_after`; returns the registries computed."""
    now = _now()
    if now < _compute_due_at(now, cfg.get("compute_after", "00:30")):
        return []
    done = []
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        have = {r[0] for r in await (await c.execute("SELECT registry FROM tr_records WHERE day = ?",
                                                     (now.date().isoformat(),))).fetchall()}
    for reg in cfg.get("registries") or []:
        if reg["name"] not in have:
            await compute_and_record(reg, key, lock, version, now)
            done.append(reg["name"])
    return done


async def prune(now: Optional[datetime] = None) -> None:
    cutoff = ((now or _now()) - timedelta(days=PROBE_KEEP_DAYS)).isoformat()
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        await c.execute("DELETE FROM tr_probes WHERE ts < ?", (cutoff,))
        await c.commit()


async def run_forever(key, lock: asyncio.Lock, version: str) -> None:
    """The observe loop. Never raises: a failed cycle is logged and the next one runs."""
    await asyncio.sleep(20)
    last_prune = 0.0
    while True:
        sleep_s = 300
        try:
            cfg = load_carrier()
            if cfg.get("registries"):
                sleep_s = cfg["probe_seconds"]
                await probe_all(cfg)
                done = await compute_due(cfg, key, lock, version)
                if done:
                    logger.info("[TRACK] daily records computed and signed: %s", ", ".join(done))
                if time.time() - last_prune > 86400:
                    await prune()
                    last_prune = time.time()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — the observe loop must never take the audit loop down with it
            logger.error("[TRACK] cycle failed (the next one runs): %s: %s", type(e).__name__, e)
        await asyncio.sleep(sleep_s)


# ── views ───────────────────────────────────────────────────────────────────

def _meta() -> Dict[str, Any]:
    return {"formula_version": FORMULA_VERSION, "weights": dict(WEIGHTS), "window_days": WINDOW_DAYS,
            "provisional_below_days": PROVISIONAL_DAYS,
            "never_an_input": ["units held, locked or paid", "AGORA points", "peer verdicts"],
            "signed_chain": CHAIN_PREFIX + "<registry>"}


async def latest_view() -> Dict[str, Any]:
    cfg = load_carrier()
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        rows = await (await c.execute(
            "SELECT r.record FROM tr_records r JOIN (SELECT registry, MAX(id) AS mid FROM tr_records GROUP BY registry) m "
            "ON r.id = m.mid ORDER BY r.registry")).fetchall()
    return {**_meta(), "enabled": bool(cfg.get("registries")),
            "registries_configured": [r["name"] for r in cfg.get("registries") or []],
            "records": [json.loads(r[0]) for r in rows]}


async def history_view(name: str, days: int) -> Dict[str, Any]:
    since = (_now() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(str(db.DB_PATH)) as c:
        rows = await (await c.execute(
            "SELECT record FROM tr_records WHERE registry = ? AND computed_at >= ? ORDER BY id DESC", (name, since))).fetchall()
    return {**_meta(), "registry": name, "days": days, "records": [json.loads(r[0]) for r in rows]}

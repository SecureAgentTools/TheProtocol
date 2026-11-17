"""V0664 consoles (C2, order gwo_ebaafc5c4af1fa3a6858e55d): a proxy's status, opt-in, and its owner reads it.

A proxy (theprotocol-sdk, tp-proxy) whose spec says `service: {report_every_s: N}` posts a small report about itself as its own agent:

    {name, sdk_version, uptime_s,
     mappings: {<name>: {pending, done, dead, paused, breaker}},      breaker: the NAME of a state ("stopped", "cooling") or null
     sources:  {<name>: {finished, last_read_at}}}                    last_read_at: UTC ISO text, or null

NAMES AND COUNTS ONLY. The registry does not trust the sender to keep to that: `check` refuses (422) any field the contract does not
name, any text where a count belongs, and any "breaker" that is not a short state name, so a proxy cannot put a record, a config value
or an error message into the row, and a refusal names the field and never repeats what was sent. One row per agent, overwritten by the
next report (table agent_proxy_status, migration 0229); the body is capped at 16 KiB; NO event is emitted per report (a heartbeat-sized
write with no ledger meaning). Reads: the agent's owner only (the developer who created it), or the developer's own list.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Dict, List, Optional

MAX_BYTES = 16 * 1024
MAX_ENTRIES = 200
MAX_LIST = 200
TOP = ("name", "sdk_version", "uptime_s", "mappings", "sources")
MAPPING_FIELDS = ("pending", "done", "dead", "paused", "breaker")
SOURCE_FIELDS = ("finished", "last_read_at")
_STATE = re.compile(r"^[a-z_]{1,24}$")
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_BIG = 10 ** 12


class Refusal(Exception):
    """A refusal with its HTTP status, a code and a sentence that names a field and never a value."""

    def __init__(self, status: int, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail
        super().__init__(detail)


def _bad(path: str, rule: str) -> Refusal:
    return Refusal(422, "invalid_report", f"{path}: {rule}")


def _label(key: Any) -> str:
    """A field name for a sentence: the sender's own key, shortened and with anything odd taken out."""
    return re.sub(r"[^A-Za-z0-9_.-]", "?", str(key))[:40]


def _text(v: Any, low: int, high: int) -> bool:
    return isinstance(v, str) and low <= len(v) <= high and not re.search(r"[\x00-\x1f\x7f]", v)


def _count(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= _BIG


def _exact(obj: Any, fields: tuple, path: str) -> None:
    if not isinstance(obj, dict):
        raise _bad(path, "must be an object")
    for f in fields:
        if f not in obj:
            raise _bad(f"{path}.{f}", "is required")
    for f in obj:
        if f not in fields:
            raise _bad(f"{path}.{_label(f)}", "is not a field of a status report (names and counts only)")


def check(report: Any) -> Dict[str, Any]:
    """The report as it is kept, or a Refusal naming the first field that is not what the contract says."""
    _exact(report, TOP, "report")
    if not _text(report["name"], 1, 120):
        raise _bad("report.name", "a name of 1 to 120 characters, no control characters")
    if not _text(report["sdk_version"], 1, 40):
        raise _bad("report.sdk_version", "a version of 1 to 40 characters, no control characters")
    if not _count(report["uptime_s"]):
        raise _bad("report.uptime_s", "a whole number of seconds, zero or more")
    for section, fields in (("mappings", MAPPING_FIELDS), ("sources", SOURCE_FIELDS)):
        table = report[section]
        if not isinstance(table, dict):
            raise _bad(f"report.{section}", "must be an object keyed by name")
        if len(table) > MAX_ENTRIES:
            raise _bad(f"report.{section}", f"at most {MAX_ENTRIES} entries")
        for name, entry in table.items():
            if not _text(name, 1, 120):
                raise _bad(f"report.{section}", "a name is 1 to 120 characters, no control characters")
            at = f"report.{section}.{_label(name)}"
            _exact(entry, fields, at)
            if section == "mappings":
                for f in ("pending", "done", "dead"):
                    if not _count(entry[f]):
                        raise _bad(f"{at}.{f}", "a whole number, zero or more")
                if not isinstance(entry["paused"], bool):
                    raise _bad(f"{at}.paused", "true or false")
                b = entry["breaker"]
                if b is not None and not (isinstance(b, str) and _STATE.match(b)):
                    raise _bad(f"{at}.breaker", "null, or the name of a state (lower-case letters, at most 24)")
            else:
                if not isinstance(entry["finished"], bool):
                    raise _bad(f"{at}.finished", "true or false")
                t = entry["last_read_at"]
                if t is not None and not (isinstance(t, str) and _STAMP.match(t)):
                    raise _bad(f"{at}.last_read_at", "null, or a UTC time as YYYY-MM-DDTHH:MM:SSZ")
    return report


def _as_dt(v: Any) -> dt.datetime:
    if isinstance(v, str):
        v = dt.datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


def _view(row: Dict[str, Any], now: dt.datetime) -> Dict[str, Any]:
    at = _as_dt(row["reported_at"])
    return {"agent_did": row["agent_did"], "reported_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "age_s": max(0, int((now - at).total_seconds())), "report": json.loads(row["report"])}


class DbStore:
    """The table on the registry database (text SQL, as services/workflow_templates). A report is kept as its JSON text."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def _rows(self, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        from sqlalchemy import text
        return [dict(r) for r in (await self.db.execute(text(sql), params)).mappings().all()]

    async def put(self, did: str, report: Dict[str, Any], now: dt.datetime) -> None:
        from sqlalchemy import text
        await self.db.execute(text(
            "INSERT INTO agent_proxy_status (agent_did, reported_at, report) VALUES (:did, :at, :report) "
            "ON CONFLICT (agent_did) DO UPDATE SET reported_at = excluded.reported_at, report = excluded.report"),
            {"did": did, "at": now, "report": json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)})
        await self.db.commit()

    async def owner_of(self, did: str) -> Optional[int]:
        rows = await self._rows("SELECT creator_developer_id AS dev FROM agents WHERE did = :did", {"did": did})
        return rows[0]["dev"] if rows else None

    async def get(self, did: str) -> Optional[Dict[str, Any]]:
        rows = await self._rows("SELECT agent_did, reported_at, report FROM agent_proxy_status WHERE agent_did = :did", {"did": did})
        return rows[0] if rows else None

    async def list_for(self, developer_id: int, limit: int) -> List[Dict[str, Any]]:
        return await self._rows(
            "SELECT s.agent_did AS agent_did, s.reported_at AS reported_at, s.report AS report FROM agent_proxy_status s "
            "JOIN agents a ON a.did = s.agent_did WHERE a.creator_developer_id = :dev "
            "ORDER BY s.reported_at DESC LIMIT :n", {"dev": developer_id, "n": int(limit)})


async def report(store: Any, did: str, body: Any, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Keep an agent's own report (the route has checked the size)."""
    kept = check(body)
    now = now or dt.datetime.now(dt.timezone.utc)
    await store.put(did, kept, now)
    return {"ok": True, "reported_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


async def read_for_owner(store: Any, developer_id: Any, did: str, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """The report of an agent to its owner. Anyone else, and an agent that does not exist, get the same 404."""
    now = now or dt.datetime.now(dt.timezone.utc)
    owner = await store.owner_of(did)
    if owner is None or developer_id is None or owner != developer_id:
        raise Refusal(404, "not_found", "No such agent")
    row = await store.get(did)
    if row is None:
        raise Refusal(404, "no_report", "This agent has not reported a status")
    return _view(row, now)


async def list_for_owner(store: Any, developer_id: Any, now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
    now = now or dt.datetime.now(dt.timezone.utc)
    return [_view(r, now) for r in await store.list_for(developer_id, MAX_LIST)]

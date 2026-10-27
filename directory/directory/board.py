"""§MEMBERSHIP phase C (2026-10-02): what the registry board reads from each registry. Counts only.

Two public reads per registry, each with its own state. A board that cannot tell "this registry has no members" from
"this registry does not serve the figure" from "the read failed" would print a sentence it never observed:

  membership  GET /api/v1/membership/stats          ok | absent (404: not served there) | unreadable (anything else)
  commons     GET /api/v1/commons/seasons?limit=20  ok | switched_off (the registry's OWN 403 commons_disabled)
                                                       | absent (404) | unreadable (anything else, a gateway's 403 too)

A failed read is silence, not news: the last figures read are KEPT (with the time they were read), and only the state and
the error move. An `absent` or `switched_off` answer is the registry itself saying so, and clears them.

No member is named anywhere: the stats route publishes counts only, and a season row carries its budget and its counts,
never a ballot. Kept free of any registry import, so the Directory's CI job (a plain Python container) can test it.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

MEMBERSHIP_STATS = "/api/v1/membership/stats"
# Twenty read, the newest three that were not cancelled kept: a cancelled season never paid anything (a cancel is refused
# once any award was sent), and a test runner that opens and cancels one per run must not push real seasons off the board;
# how many of the twenty were cancelled is kept as a count (agentvault2-33 with agentvault2-09, 2026-10-02).
COMMONS_SEASONS = "/api/v1/commons/seasons?limit=20"
SEASONS_KEPT = 3

_MEMBERSHIP_INTS = ("members", "joined_30d", "left_30d", "min_bond_age_days", "tenure_full_days")
_MEMBERSHIP_STRS = ("mode", "presence_mode", "as_of")
_SEASON_STRS = ("title", "status", "currency", "budget", "paid_total", "opens_at", "ends_at", "closed_at", "paid_at",
                "cancelled_at")
_SEASON_INTS = ("submissions", "ballots")


async def _get(client: Any, url: str) -> Tuple[Optional[int], Any, Optional[str]]:
    """(status, the JSON body or None, a transport error or None)."""
    try:
        r = await client.get(url)
    except Exception as e:  # noqa: BLE001 — a transport failure is a state of this read, reported verbatim
        return None, None, f"{type(e).__name__}: {str(e)[:120]}"
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 — an HTML page (an SPA fallback) or an empty body is "not a document"
        body = None
    return r.status_code, body, None


def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def membership_figures(doc: Any) -> Optional[Dict[str, Any]]:
    """The counts-and-rules subset of a stats document, typed; None when the document is not one."""
    if not isinstance(doc, dict) or _int(doc.get("members")) is None:
        return None
    out: Dict[str, Any] = {k: _int(doc.get(k)) for k in _MEMBERSHIP_INTS}
    out.update({k: _str(doc.get(k)) for k in _MEMBERSHIP_STRS})
    return out


def season_figures(s: Any) -> Optional[Dict[str, Any]]:
    """One season's public summary, typed; None for a row without an id."""
    if not isinstance(s, dict) or _int(s.get("id")) is None:
        return None
    out: Dict[str, Any] = {"id": _int(s["id"])}
    out.update({k: _str(s.get(k)) for k in _SEASON_STRS})
    out.update({k: _int(s.get(k)) for k in _SEASON_INTS})
    return out


async def read_membership(client: Any, base: str) -> Dict[str, Any]:
    status, body, err = await _get(client, f"{base}{MEMBERSHIP_STATS}")
    if status == 200:
        figures = membership_figures(body)
        if figures is not None:
            return {"state": "ok", "figures": figures, "error": None}
        return {"state": "unreadable", "figures": None, "error": "http 200 without a stats document"}
    if status == 404:
        return {"state": "absent", "figures": None, "error": None}
    return {"state": "unreadable", "figures": None, "error": err or f"http {status}"}


async def read_commons(client: Any, base: str) -> Dict[str, Any]:
    status, body, err = await _get(client, f"{base}{COMMONS_SEASONS}")
    if status == 200 and isinstance(body, dict) and isinstance(body.get("seasons"), list):
        rows = body["seasons"]
        live = [s for s in rows if not (isinstance(s, dict) and s.get("status") == "cancelled")]
        seasons = [f for f in (season_figures(s) for s in live[:SEASONS_KEPT]) if f is not None]
        cancelled = sum(1 for s in rows if isinstance(s, dict) and s.get("status") == "cancelled")
        return {"state": "ok", "figures": {"currency": _str(body.get("currency")), "seasons": seasons,
                                           "cancelled_recent": cancelled}, "error": None}
    if status == 403 and isinstance(body, dict) and body.get("error") == "commons_disabled":
        return {"state": "switched_off", "figures": None, "error": None}
    if status == 404:
        return {"state": "absent", "figures": None, "error": None}
    if status == 200:
        return {"state": "unreadable", "figures": None, "error": "http 200 without a seasons document"}
    return {"state": "unreadable", "figures": None, "error": err or f"http {status}"}


def _record(store: Any, name: str, prefix: str, read: Dict[str, Any], at: float) -> None:
    fields: Dict[str, Any] = {f"{prefix}_state": read["state"], f"{prefix}_error": read["error"],
                              f"{prefix}_checked_at": at}
    if read["state"] == "ok":
        fields[f"{prefix}_json"] = json.dumps(read["figures"])
        fields[f"{prefix}_at"] = at
    elif read["state"] in ("absent", "switched_off"):
        fields[f"{prefix}_json"] = None      # the registry itself said so: nothing to keep
    # unreadable: the last figures and the time they were read stay, so a stale board can say how stale it is
    store.set_registry_field(name, **fields)


async def pull_board(client: Any, store: Any, reg: Dict[str, Any]) -> Dict[str, Any]:
    """Read both figures of one registry and record them on its row; the states go into the cycle's summary."""
    base, name = reg["base"], reg["name"]
    at = time.time()
    membership = await read_membership(client, base)
    commons = await read_commons(client, base)
    _record(store, name, "membership", membership, at)
    _record(store, name, "commons", commons, at)
    return {"membership": membership["state"], "commons": commons["state"],
            "errors": [f"{k} {r['error']}" for k, r in (("membership", membership), ("commons", commons)) if r["error"]]}


def row_figures(row: Dict[str, Any], prefix: str) -> Optional[Dict[str, Any]]:
    """A registry row's stored figures for the schema: None when this Directory never checked that registry."""
    state = row.get(f"{prefix}_state")
    if not state:
        return None
    try:
        figures = json.loads(row[f"{prefix}_json"]) if row.get(f"{prefix}_json") else None
    except (TypeError, ValueError):
        figures = None
    return {"state": state, "figures": figures, "read_at": row.get(f"{prefix}_at"),
            "checked_at": row.get(f"{prefix}_checked_at"), "error": row.get(f"{prefix}_error")}

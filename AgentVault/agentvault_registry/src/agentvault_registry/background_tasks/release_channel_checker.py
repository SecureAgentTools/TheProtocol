"""§RELEASECHANNEL: the registry reads the signed release channel and tells its admins when a stable release or a
hotfix is out, once per version, so they can schedule the rollout themselves (his words 2026-09-21).

What it does, every RELEASE_CHANNEL_CHECK_INTERVAL_SECONDS (default 6 h) on the leader:
  1. GET RELEASE_CHANNEL_URL (15 s, no redirects, at most 1 MB). A 404 is the channel not published yet: recorded as
     `unreachable`, nobody notified, no error stamped (before launch this is the normal state of every frame).
  2. Verify the document's signature against the baked public key. An unsigned or altered document is recorded as
     `invalid_signature`, counted, and NOT acted on.
  3. Compare the newest releases with what this registry runs (core/release_channel.running_versions).
  4. If a newer release exists and this version was not notified before: notify the admin audience under
     `release.update_available` (priority high for a hotfix or a security release), pointing at the admin page where
     the rollout can be scheduled. The notification is the whole action: the checker never pulls, never recreates.
  5. If an admin scheduled a rollout window and it is due within the next interval: one reminder under
     `release.rollout_due` with the command to run.

State: core/release_channel.load_state/save_state (a JSON file on the data volume; memory when unwritable). The
admin rail (routers/admin_release_channel.py) reads the same state and can run `check_once` on demand.

Sends nothing about this registry to the channel: a plain GET, no version, no identifier.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..core import release_channel as rc
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

UPDATE_KEY = "release.update_available"
ROLLOUT_DUE_KEY = "release.rollout_due"
ADMIN_PAGE = "/admin/release-channel"

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    CHECKS_TOTAL = _Counter("registry_release_channel_checks_total",
                            "Release channel checks by outcome (ok, unreachable, invalid_signature, invalid_document).",
                            ["outcome"])
    UPDATE_AVAILABLE = _Gauge("registry_release_channel_update_available",
                              "1 while the channel lists a release newer than the running one, else 0.",
                              multiprocess_mode="livemostrecent")
    LAST_CHECK = _Gauge("registry_release_channel_last_check_unixtime",
                        "Unix time of the last completed check (any outcome).", multiprocess_mode="livemostrecent")
except Exception:  # noqa: BLE001
    CHECKS_TOTAL = UPDATE_AVAILABLE = LAST_CHECK = None  # type: ignore[assignment]


def _interval() -> int:
    try:
        return max(300, int(os.getenv("RELEASE_CHANNEL_CHECK_INTERVAL_SECONDS", "21600")))
    except (ValueError, TypeError):
        return 21600


def _count(outcome: str) -> None:
    if CHECKS_TOTAL is not None:
        try:
            CHECKS_TOTAL.labels(outcome=outcome).inc()
        except Exception:  # noqa: BLE001
            pass


async def fetch_document() -> Tuple[Optional[int], Optional[bytes], str]:
    """(status, body, error). A 3xx is refused (§VITALS: a redirect that loses its scheme is a quiet empty result)."""
    import httpx
    url = rc.channel_url()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False,
                                     headers={"User-Agent": "theprotocol-release-channel/1"}) as client:
            async with client.stream("GET", url) as r:
                if r.status_code != 200:
                    return r.status_code, None, f"HTTP {r.status_code}"
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > rc.MAX_BYTES:
                        return r.status_code, None, f"document larger than {rc.MAX_BYTES} bytes"
                return 200, bytes(buf), ""
    except Exception as exc:  # noqa: BLE001 — the reason is recorded, never raised
        return None, None, f"{type(exc).__name__}: {str(exc)[:160]}"


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def rollout_command(kind_of_node: str, version: str) -> str:
    if kind_of_node == "operator":
        return f"tp update --apply --to-version {version}"
    return f"./frame-update.py --name <frame> --to-version {version} --apply"


def _node_kind() -> str:
    return "operator" if (os.getenv("REGISTRY_NAME") or "").startswith("cloud-op-") else "frame"


async def check_once(*, notify: bool = True, fetch=fetch_document) -> Dict[str, Any]:
    """One check; returns the new state. Used by the worker's cycle and by the admin rail's "check now"."""
    import json
    state = rc.load_state()
    state["channel_url"] = rc.channel_url()
    state["running"] = rc.running_versions()
    status, body, err = await fetch()
    if status != 200 or body is None:
        state.update({"last_check_at": rc.now_iso(), "last_outcome": "unreachable", "last_error": err})
        _count("unreachable")
        _finish(state)
        return state
    try:
        doc = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        state.update({"last_check_at": rc.now_iso(), "last_outcome": "invalid_document", "last_error": str(exc)[:160]})
        _count("invalid_document")
        _finish(state)
        return state
    ok, reason = rc.verify(doc)
    if not ok:
        logger.warning("[release-channel] document at %s NOT verified: %s", rc.channel_url(), reason)
        state.update({"last_check_at": rc.now_iso(), "last_outcome": "invalid_signature", "last_error": reason})
        _count("invalid_signature")
        _finish(state)
        return state
    verdict = rc.assess(doc, state["running"])
    state.update({"last_check_at": rc.now_iso(), "last_outcome": "ok", "last_error": None,
                  "latest": verdict["latest"], "newer": verdict["newer"], "update_available": verdict["update_available"],
                  "kind": verdict["kind"], "comparable": verdict["comparable"]})
    _count("ok")
    if notify and verdict["update_available"]:
        top = verdict["newer"][0]
        if top["version"] not in (state.get("notified") or {}):
            await _notify_update(top, verdict["kind"], len(verdict["newer"]), state["running"])
            state.setdefault("notified", {})[top["version"]] = rc.now_iso()
    if notify:
        await _remind_if_due(state)
    _finish(state)
    return state


def _finish(state: Dict[str, Any]) -> None:
    rc.save_state(state)
    if UPDATE_AVAILABLE is not None:
        try:
            UPDATE_AVAILABLE.set(1 if state.get("update_available") else 0)
            LAST_CHECK.set_to_current_time()
        except Exception:  # noqa: BLE001
            pass


async def _notify_update(top: Dict[str, Any], kind: str, count: int, running: Dict[str, Any]) -> None:
    from .push_notify import notify_audience
    word = {"security": "Security release", "hotfix": "Hotfix", "stable": "Stable release"}.get(kind, "Release")
    running_label = running.get("kit_version") or running.get("software_version") or "unknown"
    title = f"{word} {top['version']} is available (this registry runs {running_label})"
    more = f" {count - 1} more release(s) sit between them." if count > 1 else ""
    notes = (top.get("notes") or "").strip()
    message = (f"The signed release channel lists {top['version']} ({top.get('kind')}, released {top.get('released_at') or 'n/a'})."
               f"{more} Nothing was changed: schedule the rollout when it suits you on the release page, then run "
               f"`{rollout_command(_node_kind(), top['version'])}` in your window." + (f" Notes: {notes[:400]}" if notes else ""))
    await notify_audience(UPDATE_KEY, title=title, message=message,
                          tags="rotating_light" if kind in ("hotfix", "security") else "package",
                          priority="high" if kind in ("hotfix", "security") else "default", click=ADMIN_PAGE)


async def _remind_if_due(state: Dict[str, Any]) -> None:
    sch = state.get("schedule")
    if not isinstance(sch, dict) or not sch.get("version"):
        return
    # a window for a release this registry already runs (the rollout happened, early or on time) is spent: no reminder
    # about work that is done (agentvault2-56, 2026-10-23)
    if rc.schedule_spent(sch, state.get("running") or rc.running_versions()):
        logger.info("[release-channel] schedule for %s cleared: this registry runs it or a later release", sch.get("version"))
        state["schedule"] = None
        return
    if sch.get("reminded_at"):
        return
    at = _parse_iso(sch.get("at"))
    if at is None:
        return
    seconds_left = (at - datetime.now(timezone.utc)).total_seconds()
    if seconds_left > _interval():
        return
    from .push_notify import notify_audience
    when = "now" if seconds_left <= 0 else f"at {sch['at']}"
    await notify_audience(ROLLOUT_DUE_KEY, title=f"Scheduled rollout to {sch['version']} is due {when}",
                          message=(f"You scheduled the rollout to {sch['version']} for {sch['at']}"
                                   + (f" ({sch.get('note')})" if sch.get("note") else "")
                                   + f". Run `{rollout_command(_node_kind(), sch['version'])}` on the host in your window; "
                                     "the registry does not update itself."),
                          tags="alarm_clock", priority="high", click=ADMIN_PAGE)
    sch["reminded_at"] = rc.now_iso()


class ReleaseChannelChecker(BackgroundWorker):
    worker_id = "release_channel_checker"
    leader_key = "leader:release_channel_checker"
    interval_sec = _interval()
    cold_start_delay_sec = 120
    gate_label = "RELEASE_CHANNEL_CHECK_ENABLED"

    def _should_run(self) -> bool:
        return rc.check_enabled()

    async def _cycle_once(self) -> None:
        state = await check_once(notify=True)
        self._stats = {"outcome": state.get("last_outcome"), "update_available": bool(state.get("update_available")),
                       "kind": state.get("kind"), "latest": (state.get("latest") or {}).get("version"),
                       "running": state.get("running"), "channel_url": state.get("channel_url")}


release_channel_checker = ReleaseChannelChecker()

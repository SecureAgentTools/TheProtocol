"""§ALERTS (2026-10-06, agentvault2-09): the alerts that are firing, read where they live.

His words: "check why alerts are not connected to the header thing where the broadcasts are displayed" and, on the
recommendation to wire it to the real data, "1. yes".

Prometheus here only scrapes (its rule_files moved to vmalert on 2026-04-30), so its /api/v1/alerts is empty by
construction. The header strip's alerts mode (which also asked a path that does not exist) and the Health Monitor's
alert list both read it and said "no alerts" while vmalert held 43. vmalert writes every alert's state into
VictoriaMetrics: the ALERTS series (one per firing or pending alert, labels only) and ALERTS_FOR_STATE (its value is the
moment the alert became active). VictoriaMetrics sits on every frame network (VICTORIA_METRICS_URL), so that is the one
place a frame's registry can read them. vmalert's own API (with the annotations) and Alertmanager sit on Frame A's
network only, so a summary line is not available here; the title is the alert name, made readable.

Four outcomes, never collapsed into "none": not configured (VICTORIA_METRICS_URL unset), unreadable (with the reason),
read with alerts, read and empty. Sandbox alerts (env="sandbox") are withheld unless asked for, and COUNTED: a filter
that removes something says what it removed.

The alert e-mails hold a warning back while its critical fires (alertmanager's second inhibit rule, stack
monitoring/alertmanager/alertmanager.yml, his word 2026-10-06 on "critical disk space warning comes before host diskspace
low or whatever it seems to be multiple"). vmalert keeps BOTH firing, so this reader applies the same rule, read the same
way, or the header strip shows one condition twice: a held-back warning leaves the list and the counts, and is named in
`inhibited` (with the critical that holds it) and counted in `withheld.inhibited`.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..core.observability_urls import prometheus_url
from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

# Only series vmalert wrote in the last 3 minutes. vmalert writes no stale marker when a reload changes a rule, so the
# store keeps answering a dead alert's last sample: measured 2026-10-06, 39 CanaryPathDown rows 327 s after the reload
# that retired them while vmalert itself held 3 alerts. 3 m is three times the longest group interval (60 s).
ALERTS_QUERY = 'last_over_time(ALERTS{alertstate=~"firing|pending"}[3m])'
FOR_STATE_QUERY = "last_over_time(ALERTS_FOR_STATE[3m])"
MAX_ALERTS = 500

# the labels a reader needs to tell two alerts of one rule apart (everything else stays on the series)
KEY_LABELS = ("device", "frame", "job", "instance_name", "path", "backend", "service", "trust_domain", "teg_id",
              "scope", "worker", "datname", "family", "component", "name")
_SEVERITY_ORDER = {"page": 0, "critical": 1, "warning": 2, "info": 3}
# alertmanager's inhibit rule, as configured: source severity critical with a family, target severity warning with a
# family, equal on these labels (a label missing on both sides is equal, as alertmanager reads `equal`)
INHIBIT_EQUAL = ("family", "device", "job", "instance", "frame")
_ACRONYM_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def vm_url() -> str:
    """VICTORIA_METRICS_URL, the same variable the degradation panel reads. Unset (or empty) is its own state."""
    return (os.getenv("VICTORIA_METRICS_URL", "") or "").strip().rstrip("/")


def humanize_alertname(name: str) -> str:
    """DiskSpaceCritical -> "Disk space critical", DBConnectionsHigh -> "DB connections high"."""
    if not name:
        return "Unnamed alert"
    words = _ACRONYM_SPLIT.sub(" ", name).split()
    out = [words[0]] + [w if (len(w) > 1 and w.isupper()) else w.lower() for w in words[1:]]
    return " ".join(out)


def _signature(metric: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    """ALERTS carries alertstate, ALERTS_FOR_STATE does not: the rest of the labels pair them."""
    return tuple(sorted((k, v) for k, v in metric.items() if k not in ("__name__", "alertstate")))


def _inhibit_key(metric: Dict[str, str]) -> Tuple[str, ...]:
    return tuple(metric.get(k) or "" for k in INHIBIT_EQUAL)


def _iso(ts: Any) -> Optional[str]:
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()


def _empty(configured: bool) -> Dict[str, Any]:
    return {
        "configured": configured,
        "readable": False,
        "reason": None,
        "source": "victoriametrics",
        "read_at": datetime.now(timezone.utc).isoformat(),
        "alerts": [],
        "counts": {"firing": 0, "pending": 0, "page": 0, "critical": 0, "warning": 0, "info": 0},
        "withheld": {"sandbox": 0, "inhibited": 0},
        "inhibited": [],
        "truncated": 0,
    }


def _alert_rule_count(resp: httpx.Response) -> Tuple[Optional[int], Optional[str]]:
    """(alerting rules a Prometheus holds, None) on an answered /api/v1/rules; (None, reason) otherwise."""
    if resp.status_code != 200:
        return None, f"http:{resp.status_code}"
    try:
        body = resp.json()
    except ValueError:
        return None, "body:not_json"
    if not isinstance(body, dict) or body.get("status") != "success":
        return None, "rules:failed"
    groups = (body.get("data") or {}).get("groups") or []
    return sum(len(g.get("rules") or []) for g in groups if isinstance(g, dict)), None


def _result(resp: httpx.Response) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """(series, None) on an answered query; (None, reason) otherwise. The reason names what failed."""
    if resp.status_code != 200:
        return None, f"http:{resp.status_code}"
    try:
        body = resp.json()
    except ValueError:
        return None, "body:not_json"
    if not isinstance(body, dict) or body.get("status") != "success":
        return None, f"query:{(body or {}).get('errorType') or 'failed'}" if isinstance(body, dict) else "body:unexpected"
    res = (body.get("data") or {}).get("result")
    if not isinstance(res, list):
        return None, "body:no_result"
    return res, None


def shape_alerts(series: List[Dict[str, Any]], for_state: Optional[List[Dict[str, Any]]],
                 include_sandbox: bool = False) -> Dict[str, Any]:
    """The pure half (tested without a network): series of ALERTS (+ ALERTS_FOR_STATE) -> the answer's lists and counts."""
    since: Dict[Tuple[Tuple[str, str], ...], Optional[str]] = {}
    for s in for_state or []:
        m = s.get("metric") or {}
        val = (s.get("value") or [None, None])[1]
        since[_signature(m)] = _iso(val)
    # one alert, one row: in the window an alert that just went pending -> firing has a sample of BOTH states (the
    # alertstate label is the only difference), so the firing one wins
    by_sig: Dict[Tuple[Tuple[str, str], ...], Dict[str, Any]] = {}
    for s in series:
        m = s.get("metric") or {}
        sig = _signature(m)
        if sig in by_sig and (m.get("alertstate") or "firing") != "firing":
            continue
        by_sig[sig] = m
    # the inhibit sources: firing criticals with a family (alertmanager inhibits only on alerts that fire)
    holders: Dict[Tuple[str, ...], str] = {}
    for m in by_sig.values():
        if ((m.get("alertstate") or "firing") == "firing" and (m.get("severity") or "").lower() == "critical"
                and m.get("family")):
            holders.setdefault(_inhibit_key(m), m.get("alertname") or "")
    alerts: List[Dict[str, Any]] = []
    inhibited: List[Dict[str, Any]] = []
    withheld_sandbox = 0
    for m in by_sig.values():
        state = m.get("alertstate") or "firing"
        if (m.get("env") or "") == "sandbox" and not include_sandbox:
            withheld_sandbox += 1
            continue
        name = m.get("alertname") or ""
        if (m.get("severity") or "").lower() == "warning" and m.get("family") and _inhibit_key(m) in holders:
            inhibited.append({"alertname": name, "title": humanize_alertname(name), "state": state,
                              "labels": {k: m[k] for k in KEY_LABELS if m.get(k)}, "by": holders[_inhibit_key(m)]})
            continue
        alerts.append({
            "alertname": name,
            "title": humanize_alertname(name),
            "severity": (m.get("severity") or "info").lower(),
            "state": state,
            "env": m.get("env") or None,
            "labels": {k: m[k] for k in KEY_LABELS if m.get(k)},
            "active_since": since.get(_signature(m)),
        })
    alerts.sort(key=lambda a: (0 if a["state"] == "firing" else 1, _SEVERITY_ORDER.get(a["severity"], 9),
                               a["alertname"], sorted(a["labels"].items())))
    counts = {"firing": 0, "pending": 0, "page": 0, "critical": 0, "warning": 0, "info": 0}
    for a in alerts:
        counts["firing" if a["state"] == "firing" else "pending"] += 1
        if a["state"] == "firing" and a["severity"] in counts:
            counts[a["severity"]] += 1
    truncated = max(0, len(alerts) - MAX_ALERTS)
    inhibited.sort(key=lambda a: (a["alertname"], sorted(a["labels"].items())))
    return {"alerts": alerts[:MAX_ALERTS], "counts": counts,
            "withheld": {"sandbox": withheld_sandbox, "inhibited": len(inhibited)}, "inhibited": inhibited,
            "truncated": truncated}


async def read_active_alerts(include_sandbox: bool = False, timeout: float = 8.0,
                             transport: Optional[httpx.AsyncBaseTransport] = None) -> Dict[str, Any]:
    """Firing and pending alerts as the frame's rule evaluator holds them. Never raises; `readable` and `reason` say what
    happened, `source` where they were read."""
    url, source = vm_url(), "victoriametrics"
    # §DOCSFIX D6-252 (2026-10-16): no VictoriaMetrics, as on a frame built from the template, whose own Prometheus
    # evaluates the kit's alert rules and keeps the same ALERTS series: read the registry's PROMETHEUS_URL instead,
    # and only when that Prometheus holds alerting rules (one that only scrapes has no ALERTS, and "none" from it
    # would be a guess). Unset PROMETHEUS_URL stays "not configured": no host is guessed.
    if not url and (os.getenv("PROMETHEUS_URL", "") or "").strip():
        url, source = prometheus_url(), "prometheus"
    out = _empty(bool(url))
    out["source"] = source
    if not url:
        out["reason"] = "not_configured"
        return out
    client_kw: Dict[str, Any] = {"timeout": timeout, "transport": transport}
    if source == "prometheus":
        client_kw["verify"] = get_httpx_verify()   # the frame's Prometheus asks for the registry's certificate
    try:
        async with httpx.AsyncClient(**client_kw) as client:
            if source == "prometheus":
                rules, reason = _alert_rule_count(await client.get(f"{url}/api/v1/rules", params={"type": "alert"}))
                if rules is None:
                    out["reason"] = reason
                    logger.warning("[ActiveAlerts] the frame Prometheus's rules were not read (%s)", reason)
                    return out
                if rules == 0:
                    out["configured"] = False
                    out["reason"] = "not_configured"
                    return out
            r_alerts = await client.get(f"{url}/api/v1/query", params={"query": ALERTS_QUERY})
            series, reason = _result(r_alerts)
            if series is None:
                out["reason"] = reason
                logger.warning("[ActiveAlerts] the alert read was not answered (%s)", reason)
                return out
            for_state: Optional[List[Dict[str, Any]]] = None
            try:
                r_since = await client.get(f"{url}/api/v1/query", params={"query": FOR_STATE_QUERY})
                for_state, _ = _result(r_since)       # optional: without it the alerts carry no "since"
            except httpx.HTTPError:
                for_state = None
    except httpx.HTTPError as exc:
        out["reason"] = f"transport:{type(exc).__name__}"
        logger.warning("[ActiveAlerts] metrics store unreachable: %s", type(exc).__name__)
        return out
    out.update(shape_alerts(series, for_state, include_sandbox=include_sandbox))
    out["readable"] = True
    return out

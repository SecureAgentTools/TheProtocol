#!/usr/bin/env python3
"""§FRAMEKIT P3.1 (2026-09-12) — the Grafana dashboard a frame ships with, GENERATED so the two copies
(sidecars/grafana/... for a stranger's host, monitoring/grafana/... for this one) cannot drift and every
panel query is a string this script can be asked for (`--queries` prints them; the proof runs each against
Prometheus for a live frame). Keyed on the labels sidecars.py writes (frame / component / parent), on the
metrics the registry, TEG, EventStore and the auditor export — checked live on eu the day this was written —
and on the datasource uid DS_PROMETHEUS, which both provisioning trees declare.

    python3 scripts/hetzner_demo/frame_dashboard.py --out <file.json> [--out <file2.json>]
    python3 scripts/hetzner_demo/frame_dashboard.py --queries      # one expr per line, $frame substituted for --frame
"""
import argparse
import json
import os

DS = {"type": "prometheus", "uid": "DS_PROMETHEUS"}
UID = "frame-overview"

# (title, expr, kind, unit, extra)  — kind: stat | ts ; extra: thresholds / mappings / description
PANELS = [
    ("row", "Availability — is it up"),
    ("Registry", 'max(up{frame="$frame", component="registry"})', "stat", "none",
     {"map_updown": True, "desc": "The scrape of the registry's /metrics. A registry that cannot be scraped is usually one that cannot be reached."}),
    ("TEG", 'max(up{frame="$frame", component="teg"})', "stat", "none", {"map_updown": True, "desc": "The frame's Token Exchange Gateway: every balance move."}),
    ("Event Store", 'max(up{frame="$frame", component="event-store"})', "stat", "none", {"map_updown": True, "desc": "The ledger every Δ is measured on."}),
    ("Operators up (file_sd frames)", 'count(up{parent="$frame", component="registry"} == 1)', "stat", "none",
     {"desc": "Operators wired with a parent label (frames wired through file_sd). Frames wired before P3.1 carry no parent label here and show no data — not zero."}),
    ("Registry requests / s", 'sum(rate(http_requests_total{frame="$frame", component="registry"}[5m]))', "ts", "reqps", {}),
    ("Registry p95 latency", 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{frame="$frame", component="registry"}[5m])))', "ts", "s", {}),
    ("Registry 5xx ratio", 'sum(rate(http_requests_total{frame="$frame", component="registry", status=~"5.."}[5m])) / sum(rate(http_requests_total{frame="$frame", component="registry"}[5m]))', "ts", "percentunit",
     {"thresholds": [(0, "green"), (0.05, "red")], "desc": "Above 5% for 5 minutes is the fleet's HighErrorRate alert."}),
    ("row", "Money — the prime directive"),
    ("Auditor Δ", 'auditor_delta{frame="$frame"}', "stat", "none",
     {"thresholds": [(0, "green")], "abs_red": True, "desc": "issued − destroyed + transit_net − circulating, read by the independent auditor from the ledger. Anything but 0 is a BREACH."}),
    ("Auditor verdict", 'auditor_status{frame="$frame"}', "stat", "none", {"map_okbreach": True, "desc": "1 = the invariant holds on the auditor's last atomic read."}),
    ("Auditor cycle age", 'auditor_last_cycle_age_seconds{frame="$frame"}', "stat", "s",
     {"thresholds": [(0, "green"), (300, "orange"), (14400, "red")], "desc": "Seconds since the auditor last completed a cycle for this frame. Old = Δ is UNMEASURED, not OK."}),
    # §SECBATCH wave 2 (2026-10-16): registry_treasury_balance is no longer published (D6-254: /metrics answers whoever
    # reaches the registry), so this panel read nothing. What remains is the treasury watch's verdict and its floor:
    # 0 above the floor, 1 below it, 2 when the floor is 0 (the default: the watch is off and measures nothing).
    ("Treasury notify floor",
     'max(registry_treasury_low_active{frame="$frame", scope="platform"}) + 2 * '
     '(max(registry_treasury_low_threshold{frame="$frame", scope="platform"}) == bool 0)', "stat", "none",
     {"value_map": {"0": ("ABOVE FLOOR", "green"), "1": ("BELOW FLOOR", "red"), "2": ("WATCH OFF", "text")},
      "desc": "Whether the treasury sits below its notify floor (TREASURY_LOW_NOTIFY_THRESHOLD), as the registry's "
              "treasury watch last read it. The balance itself is not published. WATCH OFF: the floor is 0, the "
              "default, and nothing is measured. Below the floor for 10 minutes the TreasuryLow page fires. No data: "
              "the watch has not run since the registry started."}),
    ("TEG transfers / h", 'sum(increase(teg_transfer_amount_avt_count{frame="$frame", component="teg"}[1h]))', "ts", "none", {}),
    ("Balance outbox backlog", 'max(teg_balance_outbox_backlog{frame="$frame", component="teg"})', "ts", "none",
     {"thresholds": [(0, "green"), (50, "red")], "desc": "Balance events the TEG has not yet delivered to the ledger. 7-day maximum on a busy frame: 36."}),
    ("Registry supply-audit Δ (own read)", 'max(supply_audit_last_delta{frame="$frame", component="registry"})', "stat", "none",
     {"thresholds": [(0, "green")], "abs_red": True, "desc": "The registry's own supply auditor worker. Should agree with the auditor's Δ; a disagreement is itself the finding."}),
    ("row", "Ledger"),
    ("Events ingested / min", 'sum(rate(eventstore_events_ingested_total{frame="$frame", component="event-store"}[5m])) * 60', "ts", "none", {}),
    ("Ledger freshness", 'max(eventstore_ledger_freshness_seconds{frame="$frame", component="event-store"})', "stat", "s",
     {"desc": "Seconds since the last event. A quiet frame idles for hours legitimately — this is context, not an alert."}),
    ("Unique agents in the ledger", 'max(eventstore_unique_agents{frame="$frame", component="event-store"})', "stat", "none", {}),
    ("row", "Federation"),
    ("Peers known", 'max(federation_peers_total{frame="$frame", component="registry"})', "stat", "none", {}),
    ("Peers reachable", 'max(federation_peers_reachable_ratio{frame="$frame", component="registry"})', "stat", "percentunit",
     {"thresholds": [(0, "red"), (0.9, "green")], "desc": "Derived from the peer rows the fan-out stamps. A refused dial parks a peer for 33 minutes."}),
    ("Agent-card pull age", 'time() - max(agent_card_pullsync_last_cycle_unixtime{frame="$frame", component="registry"})', "stat", "s",
     {"thresholds": [(0, "green"), (28800, "red")], "desc": "Age of the last completed pull cycle (cadence 6h). increase() cannot see a reboot; this can."}),
    ("SVID bundle roots", 'max(registry_svid_bundle_roots{frame="$frame", component="registry"})', "stat", "none",
     {"desc": "Roots in the registry's trust bundle: 1 on a standalone frame, one more per federated peer. A pair that shows 1 is not federated, whatever the rows say."}),
    ("row", "Workers"),
    ("Workers failing persistently", 'count((time() - worker_last_success_unixtime{frame="$frame", component="registry"} > 3 * 3600) and on(worker) (increase(worker_cycles_total{frame="$frame", component="registry", outcome="error"}[1h]) > 0)) or vector(0)', "stat", "none",
     {"thresholds": [(0, "green"), (1, "red")], "desc": "No success in 3h AND still erroring in the last hour — the vitals verdict ERRORING. A bare staleness count would list every daily worker."}),
    ("Worker cycles / h by outcome", 'sum by (outcome) (increase(worker_cycles_total{frame="$frame", component="registry"}[1h]))', "ts", "none",
     {"desc": "ok and error cycles per hour across every worker; a healthy frame shows an ok line and no error line."}),
    # §OPAKIT (2026-10-07, his words "prepare a new frame kit including opa metrics"): the registry counts every OPA shadow
    # decision (opa_decisions_total{policy, decision, source=python|opa|mismatch}, opa_decision_latency_seconds) and the
    # kit scrapes OPA itself (job opa, component opa); nothing showed either. Measured that day on the production cluster
    # and the sandbox: every OPA answer agreed with the registry's (0 mismatch, 0 error in 6 h).
    ("row", "OPA (shadow)"),
    ("OPA", 'max(up{frame="$frame", component="opa"})', "stat", "none",
     {"map_updown": True, "desc": "The scrape of OPA's /metrics (job opa). No data = this Prometheus does not scrape OPA (the frame's own monitoring overlay does). In shadow, OPA down refuses nothing but mirrors nothing either."}),
    ("OPA mismatches (24 h)", 'sum(increase(opa_decisions_total{frame="$frame", component="registry", source="mismatch"}[24h])) or vector(0)', "stat", "none",
     {"thresholds": [(0, "green"), (1, "red")], "desc": "Decisions where OPA's answer differed from the registry's own. Read the divergence record before turning OPA_ENFORCE on."}),
    ("OPA query errors (24 h)", 'sum(increase(opa_decisions_total{frame="$frame", component="registry", source="opa", decision="error"}[24h])) or vector(0)', "stat", "none",
     {"thresholds": [(0, "green"), (1, "orange")], "desc": "Registry queries to OPA that returned no decision: unreachable, TLS refused, or a policy with no boolean result."}),
    ("OPA p95 query latency", 'histogram_quantile(0.95, sum by (le) (rate(opa_decision_latency_seconds_bucket{frame="$frame", component="registry"}[5m])))', "stat", "s",
     {"desc": "How long the registry waits for OPA. In shadow the query runs beside the request; under enforce it is on the request path."}),
    ("OPA decisions / min by source", 'sum by (source) (rate(opa_decisions_total{frame="$frame", component="registry"}[5m])) * 60', "ts", "none",
     {"legend": "{{source}}", "desc": "python = the registry's own decisions; opa = OPA's answers to the same questions; mismatch = where they differed. In a healthy shadow the python and opa lines lie on top of each other."}),
]


def _thresholds(steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": (None if i == 0 else v)} for i, (v, c) in enumerate(steps)]}


def build():
    panels, y, pid = [], 0, 1
    x = 0
    for spec in PANELS:
        if spec[0] == "row":
            if x:
                y += 5; x = 0
            panels.append({"id": pid, "type": "row", "title": spec[1], "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}})
            pid += 1; y += 1
            continue
        title, expr, kind, unit, extra = spec
        w = 6 if kind == "stat" else 12
        if x + w > 24:
            y += 5; x = 0
        p = {"id": pid, "type": "stat" if kind == "stat" else "timeseries", "title": title, "datasource": DS,
             "description": extra.get("desc", ""),
             "gridPos": {"x": x, "y": y, "w": w, "h": 5},
             "targets": [{"refId": "A", "datasource": DS, "expr": expr, "legendFormat": extra.get("legend", title)}],
             "fieldConfig": {"defaults": {"unit": unit, "thresholds": _thresholds(extra.get("thresholds") or [(0, "blue")]),
                                          "mappings": []}, "overrides": []},
             "options": ({"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "value",
                          "graphMode": "none", "textMode": "value", "orientation": "auto"} if kind == "stat"
                         else {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "single"}})}
        if extra.get("map_updown"):
            p["fieldConfig"]["defaults"]["mappings"] = [{"type": "value", "options": {"1": {"text": "UP", "color": "green"}, "0": {"text": "DOWN", "color": "red"}}}]
            p["fieldConfig"]["defaults"]["thresholds"] = _thresholds([(0, "red"), (1, "green")])
        if extra.get("value_map"):
            p["fieldConfig"]["defaults"]["mappings"] = [{"type": "value", "options": {
                k: {"text": text, "color": color} for k, (text, color) in extra["value_map"].items()}}]
        if extra.get("map_okbreach"):
            p["fieldConfig"]["defaults"]["mappings"] = [{"type": "value", "options": {"1": {"text": "OK", "color": "green"}, "0": {"text": "BREACH", "color": "red"}}}]
            p["fieldConfig"]["defaults"]["thresholds"] = _thresholds([(0, "red"), (1, "green")])
        if extra.get("abs_red"):
            # any value but exactly 0 is red: a range mapping either side of zero
            p["fieldConfig"]["defaults"]["mappings"] = [
                {"type": "range", "options": {"from": 1e-9, "to": 1e18, "result": {"color": "red"}}},
                {"type": "range", "options": {"from": -1e18, "to": -1e-9, "result": {"color": "red"}}},
                {"type": "value", "options": {"0": {"text": "0", "color": "green"}}}]
        panels.append(p); pid += 1; x += w
    return {
        "uid": UID, "title": "Frame Overview", "tags": ["theprotocol", "frames"], "timezone": "utc", "editable": True,
        "schemaVersion": 38, "version": 1, "refresh": "30s", "time": {"from": "now-24h", "to": "now"},
        "description": "§FRAMEKIT P3.1 — one frame at a time (pick it above): availability, money (the auditor's Δ), ledger, federation, workers, OPA. Generated by scripts/hetzner_demo/frame_dashboard.py; edit there.",
        "templating": {"list": [{"name": "frame", "label": "frame", "type": "query", "datasource": DS,
                                 "query": {"query": 'label_values(up{component="registry"}, frame)', "refId": "PrometheusVariableQueryEditor-VariableQuery"},
                                 "definition": 'label_values(up{component="registry"}, frame)', "refresh": 2, "sort": 1,
                                 "includeAll": False, "multi": False, "current": {"selected": False, "text": "eu", "value": "eu"}, "options": []}]},
        "annotations": {"list": []}, "links": [], "panels": panels,
    }


def queries(frame):
    return [spec[1].replace("$frame", frame) for spec in PANELS if spec[0] != "row"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", action="append", default=[])
    ap.add_argument("--queries", action="store_true")
    ap.add_argument("--frame", default="eu")
    a = ap.parse_args()
    if a.queries:
        print("\n".join(queries(a.frame)))
    d = build()
    for o in a.out:
        os.makedirs(os.path.dirname(o), exist_ok=True)
        open(o, "w").write(json.dumps(d, indent=2) + "\n"); os.chmod(o, 0o644); os.chmod(os.path.dirname(o), 0o755)
        print(f"wrote {o} ({len(d['panels'])} panels)")

"""§ALERTS (2026-10-06): the header strip and the Health Monitor read vmalert's alert state from VictoriaMetrics, and say
which of four things happened (not configured, unreadable, alerts, none). Prometheus's own alert list is empty by
construction here (it only scrapes), which is how both surfaces said "no alerts" over 43 firing ones."""
import ast
import asyncio
import pathlib

import httpx

from agentvault_registry.services import active_alerts as aa

ROUTER = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "admin_health.py"


def _vm(handler):
    return httpx.MockTransport(handler)


def _ok(result):
    return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": result}})


def _series(labels, value="1"):
    return {"metric": {"__name__": "ALERTS", **labels}, "value": [1791280000, value]}


DISK = {"alertname": "DiskSpaceCritical", "alertstate": "firing", "severity": "critical", "device": "/dev/md2",
        "family": "host_disk"}
DISK_LOW = {"alertname": "HostDiskSpaceLow", "alertstate": "firing", "severity": "warning", "device": "/dev/md2",
            "family": "host_disk"}
STORM = {"alertname": "LogWarningStorm", "alertstate": "pending", "severity": "warning"}
SBX = {"alertname": "FrameComponentDown", "alertstate": "firing", "severity": "warning", "env": "sandbox",
       "frame": "sbx-beta", "job": "sbx-beta-teg"}


def test_unset_is_its_own_state(monkeypatch):
    monkeypatch.delenv("VICTORIA_METRICS_URL", raising=False)
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    out = asyncio.run(aa.read_active_alerts())
    assert out["configured"] is False and out["readable"] is False and out["reason"] == "not_configured"
    assert out["alerts"] == []


def test_a_failed_read_is_not_an_all_clear(monkeypatch):
    monkeypatch.setenv("VICTORIA_METRICS_URL", "http://victoriametrics:8428/")

    def refuse(request):
        raise httpx.ConnectError("no route", request=request)
    out = asyncio.run(aa.read_active_alerts(transport=_vm(refuse)))
    assert out["configured"] is True and out["readable"] is False and out["reason"] == "transport:ConnectError"

    out = asyncio.run(aa.read_active_alerts(transport=_vm(lambda r: httpx.Response(503, text="busy"))))
    assert out["readable"] is False and out["reason"] == "http:503"

    out = asyncio.run(aa.read_active_alerts(
        transport=_vm(lambda r: httpx.Response(200, json={"status": "error", "errorType": "bad_data"}))))
    assert out["readable"] is False and out["reason"] == "query:bad_data"


def test_read_alerts_sorted_counted_and_sandbox_withheld(monkeypatch):
    monkeypatch.setenv("VICTORIA_METRICS_URL", "http://victoriametrics:8428")
    asked = []

    def answer(request):
        q = request.url.params.get("query")
        asked.append(q)
        assert request.url.path == "/api/v1/query"
        if q == aa.ALERTS_QUERY:
            return _ok([_series(STORM), _series(DISK_LOW), _series(SBX), _series(DISK)])
        assert q == aa.FOR_STATE_QUERY
        since = {k: v for k, v in DISK.items() if k != "alertstate"}
        return _ok([{"metric": {"__name__": "ALERTS_FOR_STATE", **since}, "value": [1791280000, "1791279000"]}])
    out = asyncio.run(aa.read_active_alerts(transport=_vm(answer)))
    assert asked == [aa.ALERTS_QUERY, aa.FOR_STATE_QUERY]
    assert out["readable"] is True and out["reason"] is None
    names = [(a["alertname"], a["state"]) for a in out["alerts"]]
    # firing before pending; the sandbox alert withheld and counted; the disk warning held back by its critical (the
    # alert e-mails' inhibit rule), named and counted
    assert names == [("DiskSpaceCritical", "firing"), ("LogWarningStorm", "pending")]
    assert out["withheld"] == {"sandbox": 1, "inhibited": 1}
    assert [(i["alertname"], i["by"]) for i in out["inhibited"]] == [("HostDiskSpaceLow", "DiskSpaceCritical")]
    assert out["counts"] == {"firing": 1, "pending": 1, "page": 0, "critical": 1, "warning": 0, "info": 0}
    disk = out["alerts"][0]
    assert disk["title"] == "Disk space critical"
    assert disk["labels"] == {"device": "/dev/md2", "family": "host_disk"}
    assert disk["active_since"].startswith("2026-")           # paired by labels with ALERTS_FOR_STATE
    assert out["alerts"][1]["active_since"] is None            # no state series for it: unknown, not invented

    out = asyncio.run(aa.read_active_alerts(include_sandbox=True, transport=_vm(answer)))
    assert out["withheld"] == {"sandbox": 0, "inhibited": 1} and len(out["alerts"]) == 3


def test_an_empty_answer_is_an_answered_all_clear(monkeypatch):
    monkeypatch.setenv("VICTORIA_METRICS_URL", "http://victoriametrics:8428")
    out = asyncio.run(aa.read_active_alerts(transport=_vm(lambda r: _ok([]))))
    assert out["readable"] is True and out["alerts"] == [] and out["counts"]["firing"] == 0


def test_the_since_series_is_optional(monkeypatch):
    monkeypatch.setenv("VICTORIA_METRICS_URL", "http://victoriametrics:8428")

    def answer(request):
        if request.url.params.get("query") == aa.ALERTS_QUERY:
            return _ok([_series(DISK)])
        return httpx.Response(500)
    out = asyncio.run(aa.read_active_alerts(transport=_vm(answer)))
    assert out["readable"] is True and out["alerts"][0]["active_since"] is None


def test_names_read_as_words():
    assert aa.humanize_alertname("DiskSpaceCritical") == "Disk space critical"
    assert aa.humanize_alertname("DBConnectionsHigh") == "DB connections high"
    assert aa.humanize_alertname("CPULoadCritical") == "CPU load critical"
    assert aa.humanize_alertname("") == "Unnamed alert"


def test_the_health_router_no_longer_asks_prometheus_for_alerts():
    """The regression gate: an f-string that dials Prometheus's /api/v1/alerts in this router is the bug coming back
    (Prometheus here evaluates no rules). Read on the AST's f-strings, so this docstring and the comments cannot
    trip it."""
    tree = ast.parse(ROUTER.read_text())
    dials = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if text.endswith("/api/v1/alerts"):
                dials.append(node.lineno)
    assert dials == [], dials
    src = ROUTER.read_text()
    assert '@router.get("/alerts/active"' in src and "read_active_alerts" in src


def test_an_alert_in_its_pending_to_firing_minute_is_one_row():
    """Both state series sit in the 3-minute window for a moment; the alert is listed once, as firing."""
    pend = dict(DISK_LOW, alertstate="pending")
    out = aa.shape_alerts([_series(pend), _series(DISK_LOW)], None)
    assert [(a["alertname"], a["state"]) for a in out["alerts"]] == [("HostDiskSpaceLow", "firing")]
    out = aa.shape_alerts([_series(DISK_LOW), _series(pend)], None)          # either order
    assert [(a["alertname"], a["state"]) for a in out["alerts"]] == [("HostDiskSpaceLow", "firing")]
    assert out["counts"]["firing"] == 1 and out["counts"]["pending"] == 0


def test_a_critical_holds_back_its_warning_as_the_alert_emails_do():
    """His word 2026-10-06 ("critical disk space warning comes before host diskspace low ... it seems to be multiple"):
    alertmanager's inhibit rule, read the same way here. Only a FIRING critical with a family holds back, only a warning
    of that family, and only with the same device, job, instance and frame (missing on both sides is equal)."""
    other_disk = dict(DISK_LOW, device="/dev/md3")
    out = aa.shape_alerts([_series(DISK), _series(DISK_LOW), _series(other_disk)], None)
    assert [(a["alertname"], a["labels"].get("device")) for a in out["alerts"]] == [
        ("DiskSpaceCritical", "/dev/md2"), ("HostDiskSpaceLow", "/dev/md3")]
    assert out["withheld"]["inhibited"] == 1 and out["inhibited"][0]["labels"]["device"] == "/dev/md2"
    # a pending critical holds nothing back (alertmanager never sees a pending alert)
    out = aa.shape_alerts([_series(dict(DISK, alertstate="pending")), _series(DISK_LOW)], None)
    assert out["withheld"]["inhibited"] == 0 and len(out["alerts"]) == 2
    # a critical without a family holds nothing back, nor does one of another family
    out = aa.shape_alerts([_series({k: v for k, v in DISK.items() if k != "family"}), _series(DISK_LOW)], None)
    assert out["withheld"]["inhibited"] == 0
    out = aa.shape_alerts([_series(dict(DISK, family="host_load")), _series(DISK_LOW)], None)
    assert out["withheld"]["inhibited"] == 0
    # the instance is compared too (it is not one of the labels the list keeps)
    out = aa.shape_alerts([_series(dict(DISK, instance="a:9100")), _series(dict(DISK_LOW, instance="b:9100"))], None)
    assert out["withheld"]["inhibited"] == 0
    out = aa.shape_alerts([_series(dict(DISK, instance="a:9100")), _series(dict(DISK_LOW, instance="a:9100"))], None)
    assert out["withheld"]["inhibited"] == 1 and out["counts"]["warning"] == 0


# §DOCSFIX D6-252 (2026-10-16): a frame built from the template sets no VICTORIA_METRICS_URL; its own Prometheus
# evaluates the kit's alert rules and keeps the same ALERTS series. The reader used to say "not configured" there and
# show nothing. With no VictoriaMetrics it now reads the registry's PROMETHEUS_URL, and only when that Prometheus holds
# alert rules: one that only scrapes has no ALERTS, so "none" from it would be a guess.

def _prom(rules, series):
    def handler(request):
        if request.url.path == "/api/v1/rules":
            return httpx.Response(200, json={"status": "success", "data": {"groups": rules}})
        if request.url.path == "/api/v1/query":
            return _ok(series if "ALERTS{" in request.url.params.get("query", "") else [])
        return httpx.Response(404)
    return _vm(handler)


def test_without_victoriametrics_the_frames_own_prometheus_is_read(monkeypatch):
    monkeypatch.delenv("VICTORIA_METRICS_URL", raising=False)
    monkeypatch.setenv("PROMETHEUS_URL", "https://frame-prometheus:9090")
    groups = [{"name": "frame", "rules": [{"name": "DiskSpaceCritical", "type": "alerting"}]}]
    out = asyncio.run(aa.read_active_alerts(transport=_prom(groups, [_series(DISK)])))
    assert out["configured"] is True and out["readable"] is True and out["source"] == "prometheus"
    assert [a["alertname"] for a in out["alerts"]] == ["DiskSpaceCritical"]


def test_a_prometheus_that_only_scrapes_is_not_an_all_clear(monkeypatch):
    monkeypatch.delenv("VICTORIA_METRICS_URL", raising=False)
    monkeypatch.setenv("PROMETHEUS_URL", "https://frame-prometheus:9090")
    out = asyncio.run(aa.read_active_alerts(transport=_prom([], [])))
    assert out["configured"] is False and out["readable"] is False and out["reason"] == "not_configured"
    assert out["source"] == "prometheus"


def test_victoriametrics_still_wins_where_it_is_set(monkeypatch):
    monkeypatch.setenv("VICTORIA_METRICS_URL", "http://victoriametrics:8428")
    monkeypatch.setenv("PROMETHEUS_URL", "https://frame-prometheus:9090")
    out = asyncio.run(aa.read_active_alerts(transport=_vm(lambda r: _ok([_series(STORM)]))))
    assert out["source"] == "victoriametrics" and out["readable"] is True

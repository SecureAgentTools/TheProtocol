"""§SECFIX D6-823 (agentvault2-13, 2026-10-30): a proxied /metrics carries no system balance; the direct scrape keeps
them. EU's and ASIA's consoles served agora_escrow_balance and fx_reserve_keeper_reserve to anyone (read 2026-10-24).
Fails on V0647 (no core/metrics_public, no middleware: the control)."""
from __future__ import annotations

import inspect

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agentvault_registry.core import metrics_public as M

EXPO = (b"# HELP agora_escrow_balance escrow\n# TYPE agora_escrow_balance gauge\n"
        b"agora_escrow_balance{listing=\"X\"} 12.5\n"
        b"# HELP fx_reserve_keeper_reserve FX reserve balance\n# TYPE fx_reserve_keeper_reserve gauge\n"
        b"fx_reserve_keeper_reserve{frame=\"eu\"} 900.0\n"
        b"# HELP agora_escrow_balance_drift kept\n# TYPE agora_escrow_balance_drift gauge\nagora_escrow_balance_drift 0.0\n"
        b"# HELP supply_delta kept\n# TYPE supply_delta gauge\nsupply_delta 0.0\n"
        b"http_requests_total{handler=\"/x\"} 3\n")


def _client():
    async def metrics(request):
        return PlainTextResponse(EXPO.decode())

    async def other(request):
        return PlainTextResponse(EXPO.decode())
    app = Starlette(routes=[Route("/metrics", metrics), Route("/other", other)])
    return TestClient(M.PublicMetricsMiddleware(app))


def test_withhold_drops_exactly_the_two_families():
    out = M.withhold(EXPO)
    assert b"agora_escrow_balance{" not in out and b"fx_reserve_keeper_reserve" not in out
    assert b"# TYPE agora_escrow_balance gauge" not in out
    assert b"agora_escrow_balance_drift 0.0" in out, "a family whose name only starts the same stays"
    assert b"supply_delta 0.0" in out and b"http_requests_total" in out


def test_a_proxied_scrape_gets_no_system_balance():
    c = _client()
    for h in ({"X-Forwarded-For": "203.0.113.7"}, {"X-Real-IP": "203.0.113.7"}, {"Forwarded": "for=203.0.113.7"}):
        r = c.get("/metrics", headers=h)
        assert r.status_code == 200 and "agora_escrow_balance{" not in r.text and "fx_reserve_keeper_reserve" not in r.text
        assert "supply_delta 0.0" in r.text and int(r.headers["content-length"]) == len(r.content)


def test_the_direct_scrape_and_other_paths_are_untouched():
    c = _client()
    r = c.get("/metrics")
    assert r.content == EXPO, "the frame's own Prometheus scrapes the container directly and keeps every family"
    assert c.get("/other", headers={"X-Forwarded-For": "203.0.113.7"}).content == EXPO


def test_the_registry_wires_it_with_its_metrics():
    import agentvault_registry.main as main
    src = inspect.getsource(main.create_app)
    i, j = src.index('_instrumentator.expose(app, endpoint="/metrics"'), src.index("app.add_middleware(PublicMetricsMiddleware)")
    assert 0 < j - i < 400, "added where /metrics is exposed, so METRICS_ENABLED=false adds neither"

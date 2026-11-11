"""The proxy as a service: /health and /metrics (Prometheus text format), on the spec's service.listen.

    GET /health    200 {"status": "ok" | "degraded", ...} while it runs; 503 when it cannot get a token
                   ("degraded": a mapping is paused or stopped by its breaker, or the whole proxy is paused)
    GET /metrics   the counters and gauges below, for Prometheus to scrape

Neither answer carries a secret: the status names the agent and the registry, never a credential or a token.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

HELP: Dict[str, Tuple[str, str]] = {
    "tp_proxy_records_total": ("counter", "Records written to the outbox, per source and mapping"),
    "tp_proxy_records_repeated_total": ("counter", "Records read again whose key was already in the outbox (not sent twice)"),
    "tp_proxy_sent_total": ("counter", "Calls and deliveries done (outcome done, or dry_run in a dry run)"),
    "tp_proxy_refused_total": ("counter", "Answers a retry will not change (the record went to the dead letters)"),
    "tp_proxy_retries_total": ("counter", "Transient failures (the record waits for its next attempt)"),
    "tp_proxy_dead_letters_total": ("counter", "Records moved to the dead letters"),
    "tp_proxy_source_errors_total": ("counter", "Times a source failed and was started again"),
}


def _labels(pairs: Iterable[Tuple[str, str]]) -> str:
    items = list(pairs)
    if not items:
        return ""
    esc = lambda v: str(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')  # noqa: E731
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in items) + "}"


def render_metrics(proxy: Any) -> str:
    out: List[str] = []
    by_metric: Dict[str, List[Tuple[Tuple[Tuple[str, str], ...], float]]] = {}
    for (metric, labels), value in sorted(proxy.counters.items()):
        by_metric.setdefault(metric, []).append((labels, value))
    for metric in sorted(set(HELP) | set(by_metric)):
        typ, help_ = HELP.get(metric, ("counter", metric))
        out.append(f"# HELP {metric} {help_}")
        out.append(f"# TYPE {metric} {typ}")
        for labels, value in by_metric.get(metric, []):
            out.append(f"{metric}{_labels(labels)} {value:g}")

    st = proxy.status()

    def gauge(name: str, help_: str, rows: Iterable[Tuple[Iterable[Tuple[str, str]], float]]) -> None:
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} gauge")
        for labels, value in rows:
            out.append(f"{name}{_labels(labels)} {value:g}")

    gauge("tp_proxy_info", "The proxy: its name, its agent and the plugin interface it runs",
          [((("name", st["name"]), ("agent_did", st["agent_did"]), ("interface", "1")), 1)])
    gauge("tp_proxy_outbox_rows", "Rows in the outbox, per status",
          [((("status", s),), n) for s, n in sorted(st["outbox"].items())])
    gauge("tp_proxy_mapping_rows", "Rows in the outbox, per mapping and status",
          [((("mapping", m), ("status", s)), v.get(s, 0)) for m, v in sorted(st["mappings"].items())
           for s in ("pending", "done", "dead")])
    gauge("tp_proxy_breaker_open", "1 while a mapping's breaker stops it (stopped, or cooling down)",
          [((("mapping", m),), 1 if v.get("breaker") else 0) for m, v in sorted(st["mappings"].items())])
    gauge("tp_proxy_mapping_paused", "1 while a mapping is paused by hand",
          [((("mapping", m),), 1 if v.get("paused") else 0) for m, v in sorted(st["mappings"].items())])
    gauge("tp_proxy_paused", "1 while the whole proxy is paused", [((), 1 if st["paused"] else 0)])
    gauge("tp_proxy_last_done_timestamp_seconds", "When each mapping's last row was done",
          [((("mapping", m),), t) for m, t in sorted(proxy.outbox.last_done().items())])
    gauge("tp_proxy_tokens_issued", "Agent tokens the registry issued this process",
          [((), st["identity"]["tokens_issued"])])
    gauge("tp_proxy_identity_ok", "1 while the proxy holds a token (0: the registry refused or could not be reached)",
          [((), 0 if st["identity"]["last_error"] else 1)])
    return "\n".join(out) + "\n"


def health(proxy: Any) -> Tuple[int, Dict[str, Any]]:
    st = proxy.status()
    stopped = sorted(m for m, v in st["mappings"].items() if v.get("breaker") or v.get("paused"))
    body: Dict[str, Any] = {
        "status": "ok", "name": st["name"], "agent_did": st["agent_did"], "registry": st["registry"],
        "dry_run": st["dry_run"], "outbox": st["outbox"], "paused": st["paused"],
        "held_mappings": stopped, "identity": st["identity"],
    }
    if st["identity"]["last_error"]:
        body["status"] = "failing"
        return 503, body
    if st["paused"] or stopped:
        body["status"] = "degraded"
    return 200, body


async def start_service(proxy: Any, listen: str):
    """Serve /health and /metrics on `listen` (host:port); answers the aiohttp runner (await runner.cleanup())."""
    from aiohttp import web

    async def _health(_request):
        code, body = health(proxy)
        return web.json_response(body, status=code)

    async def _metrics(_request):
        return web.Response(text=render_metrics(proxy), content_type="text/plain", charset="utf-8",
                            headers={"X-Content-Type-Options": "nosniff"})

    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_get("/metrics", _metrics)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    host, _, port = listen.rpartition(":")
    site = web.TCPSite(runner, host or "127.0.0.1", int(port))
    await site.start()
    return runner

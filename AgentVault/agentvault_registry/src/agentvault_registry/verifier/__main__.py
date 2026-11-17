"""python -m agentvault_registry.verifier: the verifier as a batch on a cadence, with a /metrics page of its own (GET only).

Environment (names only; no value is printed):
  OPA_VERIFIER_CONFIG        a JSON file: {"nodes": [{"name", "container", "db_env", "es_env", "base_url"}]} (db_env / es_env name the
                             variables that hold the DSNs)
  OPA_VERIFIER_BIN           the opa binary                       OPA_VERIFIER_POLICY_DIR  identity-fabric/policies (read-only)
  OPA_VERIFIER_FINDINGS      the findings file (JSON lines)       OPA_VERIFIER_INTERVAL_SECONDS  (default 300)
  OPA_VERIFIER_METRICS_PORT  the metrics port (default 9877)      OPA_VERIFIER_METRICS_HOST  (default 127.0.0.1)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .evaluator import OpaEvaluator
from .facts import NodeSources
from .runner import Recorder, RunResult, run_once

OWN_POLICIES = str(pathlib.Path(__file__).resolve().parent / "policies")


def build(environ=None):
    env = os.environ if environ is None else environ
    cfg = json.loads(pathlib.Path(env["OPA_VERIFIER_CONFIG"]).read_text())
    sources = NodeSources(cfg["nodes"], environ=dict(env))
    opa = OpaEvaluator(env["OPA_VERIFIER_BIN"], [env["OPA_VERIFIER_POLICY_DIR"], OWN_POLICIES])
    return sources, opa, Recorder(pathlib.Path(env.get("OPA_VERIFIER_FINDINGS", "/var/lib/opa-verifier/findings.jsonl")))


def serve_metrics(state: dict, host: str, port: int) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):            # noqa: N802
            if self.path.split("?")[0] != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            body = (state.get("result") or RunResult.empty()).metrics_text().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):   # no access log
            pass
    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def loop(environ=None) -> None:
    env = os.environ if environ is None else environ
    sources, opa, recorder = build(env)
    state: dict = {}
    serve_metrics(state, env.get("OPA_VERIFIER_METRICS_HOST", "127.0.0.1"), int(env.get("OPA_VERIFIER_METRICS_PORT", "9877")))
    interval = float(env.get("OPA_VERIFIER_INTERVAL_SECONDS", "300"))
    while True:
        state["result"] = await run_once(sources, opa, recorder=recorder)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(loop())

"""§MTLSHOPS (a) (2026-09-15, agentvault2-b5; agentvault2-85's rules): what the auditor's live read sends, slot by slot,
through the real _do_audit against recording stores.

RED on the base (the old code sends this host's key to a URL someone else wrote):
- an extra slot with no key, at a single-label URL that stands for another frame's store (lantern-event-store is one):
  no X-Internal-Key may arrive; the new code does not read it and names why;
- a public_read slot: its read arrives without X-Internal-Key;
- a public_only slot: its read arrives without X-Internal-Key, it holds no DSN, and every check it cannot make is recorded
  as not measured.
CONTROLS that pass on the base: a slot with its own key sends exactly that key; a built-in frame with no per-frame key sends
the mode key.
NEW (absent on the base): the kit auditor's keyless https slot is read with the auditor's own certificate, and the same slot
on an auditor with no certificate (the host) is not read.
AUDITOR_TREE points the suite at another checkout of Agents/TheAuditor (the base run).
"""
import asyncio
import http.server
import importlib
import json
import os
import sys
import threading

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE
SENTINEL = "host-key-sentinel-for-tests"
PATH = "/api/v1/projections/supply-audit"
BODY = {"tokens_issued": 10.0, "total_circulating": 10.0, "delta": 0.0, "status": "OK",
        "tokens_destroyed": 0.0, "net_supply": 10.0, "agent_count": 1}


class Store:
    """A stand-in store: records each request's path and X-Internal-Key and answers a supply audit."""

    def __init__(self):
        self.seen = []
        seen = self.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("X-Internal-Key")))
                raw = json.dumps(BODY).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    stores = {name: Store() for name in ("builtin", "other", "public", "own", "public_only")}
    extra = [
        {"id": "other", "mode": "prod", "name": "Another frame's store", "currency": "OTH",
         "url": f"http://localhost:{stores['other'].port}"},
        {"id": "public", "mode": "prod", "name": "Public read", "currency": "PUB",
         "url": f"http://127.0.0.1:{stores['public'].port}", "public_read": True},
        {"id": "own", "mode": "prod", "name": "Own key", "currency": "OWN",
         "url": f"http://127.0.0.1:{stores['own'].port}", "key": "the-slot-own-key"},
        {"id": "public_only", "mode": "prod", "name": "Public only", "currency": "PO",
         "url": f"http://127.0.0.1:{stores['public_only'].port}", "public_only": True,
         "dsn": "postgresql://auditor_ro:pw@po-es-db:5432/events"},
    ]
    _purge()
    for k in list(os.environ):
        if (k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or k.endswith("_EVENT_STORE_KEY")
                or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
    monkeypatch.setenv("EVENT_STORE_INTERNAL_KEY", SENTINEL)
    monkeypatch.setenv("FRAME_A_EVENT_STORE_URL", f"http://127.0.0.1:{stores['builtin'].port}")
    monkeypatch.setenv("AUDITOR_EXTRA_FRAMES_JSON", json.dumps(extra))
    monkeypatch.syspath_prepend(TREE)
    main = importlib.import_module("src.auditor.main")
    recorded = {}

    async def record_audit(**kw):
        recorded[kw["frame"]] = kw
        return {"id": 1, "timestamp": "2026-09-15T00:00:00+00:00", "status": kw.get("status"), "delta": kw.get("delta"),
                "frame": kw["frame"], "extra_data": kw.get("extra_data"), "public_breach_streak": 0}

    monkeypatch.setattr(main.db, "record_audit", record_audit)

    def audit(fid):
        frame = next(f for f in main.FRAMES if f["id"] == fid)
        asyncio.run(main._do_audit(frame))
        return frame, recorded[fid]

    yield main, stores, audit
    for s in stores.values():
        s.close()
    _purge()


def test_red_an_extra_slot_without_a_key_at_another_frames_store_receives_no_host_key(world):
    _main, stores, audit = world
    _frame, rec = audit("other")
    assert all(key is None for _path, key in stores["other"].seen), stores["other"].seen
    assert stores["other"].seen == [], "an extra slot without a key is not read"
    assert "never inherits" in (rec["extra_data"] or {}).get("live_skipped", "")


def test_red_a_public_read_arrives_without_a_key(world):
    _main, stores, audit = world
    frame, rec = audit("public")
    assert stores["public"].seen == [(PATH, None)]
    assert frame["key"] == "" and (rec["extra_data"] or {}).get("public_source", "").endswith(PATH)


def test_red_a_public_only_slot_reads_the_public_audit_alone_and_names_what_it_cannot_measure(world):
    _main, stores, audit = world
    frame, rec = audit("public_only")
    assert stores["public_only"].seen == [(PATH, None)]
    assert frame["dsn"] == "" and frame["reg_dsn"] == "" and frame["teg_dsn"] == ""
    ed = rec["extra_data"] or {}
    assert ed.get("public_only") is True and rec.get("source") == "public" and rec.get("atomic_status") is None
    assert {"atomic", "true_supply", "solvency", "per_user", "staked_guard", "composition", "shares", "escrow",
            "native_supply"} <= set(ed.get("not_measured") or {})
    assert all("frame's own auditor" in why for why in ed["not_measured"].values())


def test_control_a_slot_with_its_own_key_sends_exactly_that_key(world):
    _main, stores, audit = world
    audit("own")
    assert stores["own"].seen == [(PATH, "the-slot-own-key")]


def test_control_a_builtin_frame_with_no_frame_key_sends_the_mode_key(world):
    _main, stores, audit = world
    audit("frame-a")
    assert stores["builtin"].seen == [(PATH, SENTINEL)]


def test_new_the_kit_slot_reads_with_the_auditors_own_certificate_and_the_host_does_not_read_it(world):
    main, _stores, _audit = world
    kit = {"id": "kit", "url": "https://kitproof-nginx-event-store:8443", "key": "", "builtin": False}
    plan = main.tls_client.live_read_plan(kit, SENTINEL, cert="/certs/svid.0.pem", key="/certs/svid.0.key",
                                          ca="/certs/bundle.0.pem")
    assert plan["read"] and plan["store_key"] is None and plan["cert"] == "/certs/svid.0.pem"
    host = main.tls_client.live_read_plan(kit, SENTINEL)
    assert not host["read"] and host["store_key"] is None and "never inherits" in host["skipped"]

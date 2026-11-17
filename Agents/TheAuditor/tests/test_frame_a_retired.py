"""V0666 FA-2 (gwo_34513573bbd4d9cec6841e91; Frame A's retirement, approved in room seq 4404 "retire frame-a approved"): the
auditor without Frame A.

config.py forced the frame-a slot: with FRAME_A_EVENT_STORE_URL unset it copied EVENT_STORE_URL (Frame A's own store,
agentvault_event_store:8200) into it, so removing the env would have left the slot reading Frame A. One switch,
FRAME_A_ENABLED (default on, today's behaviour), drops the slot: no fallback, no FRAME_A_* env brings it back, and every
reader built from FRAMES follows (the audit loop, /api/auditor/latest, /health, /frames, /modes and its attested tiers,
/metrics). Frame A was the last frame of the legacy tier, so that tier goes with it. Its stored history and its signed
attestation chain stay readable: they are the record of what it held.

RED on the base (master df3777b3): every test_red_*. The controls pass on both.
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
BODY = {"tokens_issued": 10.0, "total_circulating": 10.0, "delta": 0.0, "status": "OK",
        "tokens_destroyed": 0.0, "net_supply": 10.0, "agent_count": 1}


class Store:
    """A stand-in store: records each request's path and answers a supply audit."""

    def __init__(self):
        self.seen = []
        seen = self.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                raw = json.dumps(BODY).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture()
def boot(tmp_path, monkeypatch):
    """boot(switch, **frame_a_env) -> (main, stores, cycle). `switch` is FRAME_A_ENABLED's value (None: unset); the
    frame A store stands at EVENT_STORE_URL, where the old fallback points."""
    stores = {name: Store() for name in ("frame_a", "eu", "sbx")}

    def _boot(switch, **frame_a_env):
        _purge()
        for k in list(os.environ):
            if (k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or k.endswith("_EVENT_STORE_KEY")
                    or k.endswith("_REG_DSN") or k.endswith("_TEG_DSN") or k == "FRAME_A_ENABLED"
                    or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE")):
                monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
        monkeypatch.setenv("EVENT_STORE_URL", stores["frame_a"].url)
        monkeypatch.setenv("EVENT_STORE_INTERNAL_KEY", "frame-a-key-for-tests")
        if switch is not None:
            monkeypatch.setenv("FRAME_A_ENABLED", switch)
        for k, v in frame_a_env.items():
            monkeypatch.setenv(k, v)
        extra = [
            {"id": "eu", "mode": "prod", "name": "EU", "currency": "ECU", "url": stores["eu"].url, "key": "eu-key"},
            {"id": "sbx-alpha", "mode": "sandbox", "name": "Sandbox Alpha", "currency": "SBXA", "url": stores["sbx"].url,
             "key": "sbx-key"},
        ]
        monkeypatch.setenv("AUDITOR_EXTRA_FRAMES_JSON", json.dumps(extra))
        monkeypatch.syspath_prepend(TREE)
        main = importlib.import_module("src.auditor.main")

        async def record_audit(**kw):
            return {"id": 1, "timestamp": "2026-11-15T00:00:00+00:00", "status": kw.get("status"),
                    "delta": kw.get("delta"), "frame": kw["frame"], "extra_data": kw.get("extra_data"),
                    "public_breach_streak": 0}
        monkeypatch.setattr(main.db, "record_audit", record_audit)

        def cycle():
            """One pass of the audit loop's gather, over the frames the loop would audit."""
            async def go():
                return await asyncio.gather(*[main._do_audit(f) for f in main.FRAMES], return_exceptions=True)
            return asyncio.run(go())
        return main, stores, cycle

    yield _boot
    for s in stores.values():
        s.close()
    _purge()


def _metrics(main, monkeypatch):
    def stats(*_a, **_k):
        raise AssertionError("/metrics must not query the database")
    monkeypatch.setattr(main.db, "get_stats", stats)
    main._stats_cache["all"] = {"total_audits": 1, "uptime_pct": 100.0}
    main._stats_cache_at["all"] = main.time.time()
    return asyncio.run(main.metrics()).body.decode()


def test_red_off_there_is_no_frame_a_slot_and_no_fallback_to_frame_as_store(boot):
    main, _stores, _cycle = boot("false")
    assert "frame-a" not in [f["id"] for f in main.FRAMES]
    assert "FRAME_A_EVENT_STORE_URL" not in os.environ, "the old fallback copied EVENT_STORE_URL into the slot's env"
    assert [f["id"] for f in asyncio.run(main.api_frames(mode=None))] == ["eu", "sbx-alpha"]
    modes = asyncio.run(main.api_modes())
    assert modes["modes"] == ["prod", "sandbox"] and modes["attest"] == ["prod"] and modes["default"] == "prod"
    assert asyncio.run(main.api_frames(mode="legacy")) == []


@pytest.mark.parametrize("switch", ["false", "0", "no", "off", "FALSE"])
def test_red_off_wins_over_every_frame_a_setting_left_in_the_env(boot, switch):
    main, stores, _cycle = boot(switch, FRAME_A_EVENT_STORE_URL="http://agentvault_event_store:8200",
                                FRAME_A_ES_DSN="postgresql://ro:pw@agentvault_event_store_db:5432/events",
                                FRAME_A_REG_DSN="postgresql://ro:pw@agentvault_registry_db_a:5432/registry",
                                FRAME_A_TEG_DSN="postgresql://ro:pw@agentvault_teg_db_a:5432/teg")
    cfg = sys.modules["src.auditor.config"]
    assert "frame-a" not in [f["id"] for f in main.FRAMES]
    assert "frame-a" not in cfg.BUILTIN_FRAME_IDS and "frame-a" not in cfg.FRAME_MODE


def test_red_off_a_whole_cycle_sends_nothing_to_frame_as_store_and_no_reader_lists_it(boot, monkeypatch):
    main, stores, cycle = boot("false")
    results = cycle()
    assert not [r for r in results if isinstance(r, Exception)], results
    assert stores["frame_a"].seen == [], "a request reached Frame A's store"
    assert stores["eu"].seen and stores["sbx"].seen, "the other frames are still audited"
    assert set(main.latest_results) == {"eu", "sbx-alpha"}
    assert "frame-a" not in asyncio.run(main.api_latest(mode=None))
    assert asyncio.run(main.api_latest(mode="legacy")) == {}
    assert set(asyncio.run(main.health())["frames"]) == {"eu", "sbx-alpha"}
    text = _metrics(main, monkeypatch)
    assert 'frame="frame-a"' not in text and 'frame="eu"' in text


def test_red_off_an_extra_entry_cannot_bring_frame_a_back_under_its_old_id(boot):
    # the frames file is the carrier a host rewrites; with the switch off, an entry named frame-a is refused and named,
    # so a stale file cannot put a retired frame back on the public page
    main, _stores, _cycle = boot("false")
    cfg = sys.modules["src.auditor.config"]
    changed = cfg.apply_extra_frames([
        {"id": "eu", "mode": "prod", "name": "EU", "currency": "ECU", "url": "http://eu-event-store:8200", "key": "k"},
        {"id": "frame-a", "mode": "legacy", "name": "Frame A", "currency": "AVT", "url": "http://agentvault_event_store:8200"},
    ])
    assert "frame-a" not in [f["id"] for f in main.FRAMES] and "frame-a" not in changed["frames"]
    assert "legacy" not in cfg.MODES


def test_control_on_by_default_frame_a_is_audited_through_the_fallback_as_before(boot):
    main, stores, cycle = boot(None)
    fa = next(f for f in main.FRAMES if f["id"] == "frame-a")
    assert fa["url"] == stores["frame_a"].url and fa["mode"] == "legacy"
    assert asyncio.run(main.api_modes())["modes"] == ["prod", "sandbox", "legacy"]
    cycle()
    assert stores["frame_a"].seen == ["/api/v1/projections/supply-audit"]
    assert "frame-a" in main.latest_results


@pytest.mark.parametrize("switch", ["true", "1", "yes", "on", ""])
def test_control_on_when_named_keeps_frame_a(boot, switch):
    main, _stores, _cycle = boot(switch)
    assert "frame-a" in [f["id"] for f in main.FRAMES]


def test_red_the_published_api_says_a_retired_frame_is_not_listed_and_where_its_record_stays(boot):
    # /docs and /openapi.json are public on auditor.theprotocol.cloud: the change is documented where a reader of the API
    # looks, on each route that lists frames
    main, _stores, _cycle = boot("false")
    paths = main.app.openapi()["paths"]
    for route in ("/api/auditor/latest", "/api/auditor/frames", "/api/auditor/modes", "/health"):
        text = paths[route]["get"].get("description") or ""
        assert "not listed" in text and "FRAME_A_ENABLED" in text, (route, text)
    latest = paths["/api/auditor/latest"]["get"]["description"]
    assert "/api/auditor/history?frame=frame-a" in latest and "/api/auditor/attestations?frame=frame-a" in latest

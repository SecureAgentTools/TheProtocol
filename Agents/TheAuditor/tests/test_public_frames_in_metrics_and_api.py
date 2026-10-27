"""§MTLSHOPS (a) (2026-09-15, agentvault2-b5; agentvault2-85's calls): a public-only frame on the metrics page and the API.

A public reading is never published under the truth names (auditor_status, auditor_delta, auditor_consecutive_ok); it has
its own (auditor_public_status, auditor_public_delta, auditor_public_breach_streak). An uptime that is not measured is left
out rather than printed as None. /api/auditor/modes lists the slot shapes a writer may use; /api/auditor/frames marks a
public-only frame.
RED on the base: all three tests. The control inside the first (a keyed frame keeps auditor_status) passes on both.
AUDITOR_TREE points the suite at another checkout of Agents/TheAuditor (the base run).
"""
import asyncio
import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture()
def main(tmp_path, monkeypatch):
    extra = [
        {"id": "po", "mode": "prod", "name": "Public only", "currency": "PO", "url": "https://po-es.example.test",
         "public_only": True},
        {"id": "own", "mode": "prod", "name": "Own key", "currency": "OWN", "url": "http://own-event-store:8200",
         "key": "the-slot-own-key"},
    ]
    _purge()
    for k in list(os.environ):
        if k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
    monkeypatch.setenv("AUDITOR_EXTRA_FRAMES_JSON", json.dumps(extra))
    monkeypatch.syspath_prepend(TREE)
    module = importlib.import_module("src.auditor.main")
    yield module
    _purge()


def _metrics(main, monkeypatch, uptime):
    async def stats(*_a, **_k):
        return {"total_audits": 1, "uptime_pct": uptime}

    monkeypatch.setattr(main.db, "get_stats", stats)
    return asyncio.run(main.metrics()).body.decode()


def test_red_a_public_only_frame_is_published_under_public_names_and_never_under_truth_names(main, monkeypatch):
    main.latest_results["po"] = {"status": "BREACH", "delta": 3.0, "extra_data": {"public_only": True}}
    main.latest_results["own"] = {"status": "OK", "delta": 0.0, "atomic_status": "OK", "atomic_delta": 0.0}
    main.public_streak["po"] = 2
    text = _metrics(main, monkeypatch, 100.0)
    for truth_name in ('auditor_status{frame="po"}', 'auditor_delta{frame="po"}', 'auditor_consecutive_ok{frame="po"}'):
        assert truth_name not in text
    assert 'auditor_public_status{frame="po"} 0' in text
    assert 'auditor_public_delta{frame="po"} 3.0' in text
    assert 'auditor_public_breach_streak{frame="po"} 2' in text
    assert 'auditor_status{frame="own"} 1' in text


def test_red_an_uptime_that_is_not_measured_is_left_out_of_the_metrics(main, monkeypatch):
    text = _metrics(main, monkeypatch, None)
    assert "auditor_uptime_pct None" not in text
    assert not any(line.startswith("auditor_uptime_pct ") for line in text.splitlines())


def test_red_the_modes_list_the_slot_shapes_and_the_frames_mark_a_public_only_frame(main):
    assert asyncio.run(main.api_modes())["slot_shapes"] == ["public_only", "public_read"]
    frames = {f["id"]: f for f in asyncio.run(main.api_frames(mode=None))}
    assert frames["po"]["public_only"] is True and frames["own"]["public_only"] is False

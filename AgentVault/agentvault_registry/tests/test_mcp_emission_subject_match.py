"""§MCPTEST30 (V0638): a noisy event type is matched to the sweep by its subject too, not by its data alone.

The emission check tells a sweep's own events from canary and background noise by finding a sweep DID in the event
(_EMIT_CANARY_NOISY). It looked in the event's data only. ReputationChanged names its agent in aggregate_id and carries
old_score, new_score and a reason as data, so a sweep's signal could never match: agentvault2-aa's History run of
2026-10-24 (the MCP lifecycle through EU's console) read "applyReputationSignal answers 2xx and no ReputationChanged
lands" while sbx-alpha's log said "Emitted ReputationChanged" for the signal's receiver. Pinned: the subject matches,
the data still matches, and an event about another agent does not (the control).
"""
from __future__ import annotations

import pytest

from agentvault_registry.routers import mcp_tester as mt

SWEEP = "did:theprotocol:sandbox-a.theprotocol.cloud:677c3b1b-dc3d-4948-8d0c-32b95feaf818"
OTHER = "did:theprotocol:sandbox-a.theprotocol.cloud:11111111-2222-4333-8444-555555555555"


def _client(events_by_type):
    class _Resp:
        def __init__(self, events):
            self.status_code, self._events = 200, events

        def json(self):
            return self._events

    class _Cli:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            return _Resp(events_by_type.get((params or {}).get("event_type"), []))

    return _Cli()


async def _seen(monkeypatch, events_by_type):
    import httpx
    monkeypatch.setattr(mt, "_EMIT_SETTLE_S", 0.0)
    monkeypatch.setattr(mt, "_emission_store_for", lambda flow: ("http://sbx-alpha-event-store:8200", "k"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _client(events_by_type))
    return await mt._collect_emissions("2026-10-24T11:30:00+00:00", {SWEEP}, expect_types=["ReputationChanged"])


@pytest.mark.parametrize("event, matched", [
    # the signal's own event: its agent only in aggregate_id
    ({"event_type": "ReputationChanged", "aggregate_id": SWEEP,
      "data": {"old_score": 0, "new_score": 1, "reason": "reputation_signal:1:tx:tx-of-the-sweep"}}, True),
    # an event that names the sweep's agent in its data matches as before
    ({"event_type": "ReputationChanged", "aggregate_id": "epoch-42", "data": {"agent_did": SWEEP}}, True),
    # control: background noise about another agent
    ({"event_type": "ReputationChanged", "aggregate_id": OTHER,
      "data": {"old_score": 3, "new_score": 4, "reason": "eigentrust"}}, False),
])
async def test_a_noisy_event_matches_the_sweep_by_its_subject_or_its_data(monkeypatch, event, matched):
    out = await _seen(monkeypatch, {"ReputationChanged": [event]})
    assert out["ReputationChanged"] == {"present": True, "matched": matched}
    assert mt._emit_satisfied("ReputationChanged", out["ReputationChanged"]) is matched

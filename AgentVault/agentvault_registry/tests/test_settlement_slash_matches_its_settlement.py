"""D6-442: the lost-callback recovery pays only on the slash of THIS settlement.

The reconciler took any DisputeSlash among the store's 50 newest whose dispute_id equalled the settlement's. Dispute
ids are per registry, so another registry's slash of its own dispute with the same number paid this settlement's
complainant from this registry's treasury. It now asks the dispute's aggregate and requires the event to name this
settlement's origin registry and defendant.
"""
import asyncio
import types

from agentvault_registry.tasks import settlement_reconciliation as sr

ORIGIN = "https://eu.example.org:8443"
DEFENDANT = "did:theprotocol:defendant"


class _Resp:
    status_code = 200

    def __init__(self, events):
        self._events = events

    def json(self):
        return self._events


def _client(events, asked):
    class _C:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            asked.append(url)
            return _Resp(events)
    return _C


def _settlement():
    return types.SimpleNamespace(id="s1", dispute_id=5, origin_registry_url=ORIGIN + "/", defendant_did=DEFENDANT)


def _slash(**kw):
    data = {"dispute_id": 5, "defendant_did": DEFENDANT, "amount": 40, "origin_registry_url": ORIGIN,
            "slash_tx_id": "dispute-slash-5-abcd1234"}
    data.update(kw)
    return {"id": "e1", "event_type": "DisputeSlash", "data": data}


def _check(monkeypatch, events):
    asked = []
    monkeypatch.setattr(sr.httpx, "AsyncClient", _client(events, asked))
    monkeypatch.setattr(sr, "settings", types.SimpleNamespace(EVENT_STORE_URL="http://es.example:8200/",
                                                              EVENT_STORE_API_KEY="k"))
    return asyncio.run(sr._check_eventstore_for_slash(_settlement())), asked


def test_it_asks_for_the_disputes_own_events(monkeypatch):
    _, asked = _check(monkeypatch, [])
    assert asked == ["http://es.example:8200/api/v1/events/aggregate/dispute:5"
                     "?event_types=DisputeSlash&limit=50&sort_order=desc"]


def test_another_registrys_dispute_with_the_same_number_pays_nothing(monkeypatch):
    found, _ = _check(monkeypatch, [_slash(origin_registry_url="https://elsewhere.example.org:8443")])
    assert found is None


def test_another_defendant_pays_nothing(monkeypatch):
    found, _ = _check(monkeypatch, [_slash(defendant_did="did:theprotocol:someone-else")])
    assert found is None


def test_the_settlements_own_slash_is_found(monkeypatch):
    found, _ = _check(monkeypatch, [_slash(origin_registry_url="https://elsewhere.example.org:8443"), _slash()])
    assert found == {"event_id": "e1", "amount": 40, "slash_tx_id": "dispute-slash-5-abcd1234",
                     "defendant_did": DEFENDANT}

"""§MCPTEST30 V0640 (agentvault2-aa, 2026-10-24): a settlement no peer takes keeps each peer's answer on its row.

Two sandbox settlements (bcc7ae9e on sbx-beta, 63761626 on sbx-alpha) waited at PENDING_SLASH with their three retries
spent, and their rows said only "retry_count=3": the reason (every home refused a callback outside its active peers'
base URLs with 400) had lived in log lines, and the registry's recreate took those (agentvault2-66's read; their warnings
fired production's SettlementFailureRate before its rule left the sandbox out). The first delivery and every retry now
record each peer's name, status and refusal sentence (the home's 400 names hosts only), an exception by its type alone,
with the retry's count first so the next cycle still reads it (agentvault2-66's fix/settlement-warning-noise appends
its exhausted mark after). The tests fail on 0aeffe4e's code (the control).
"""
from __future__ import annotations

import httpx
import pytest

from agentvault_registry.core import settlement_origin

ORIGIN = "https://sandbox-b.theprotocol.cloud:8443"
REFUSAL = ('{"detail":"Callback URL must belong to a registered peer registry: its host sbx-beta-nginx-federation is '
           'under no active peer\'s base URL (active peer hosts: sandbox-a.theprotocol.cloud, '
           'sbxbetaop.op.theprotocol.cloud)"}')


class _Resp:
    def __init__(self, code: int, text: str):
        self.status_code, self.text = code, text

    def json(self):
        return {}


def _client(answer):
    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            if isinstance(answer, Exception):
                raise answer
            return _Resp(*answer)
    return _Client


class _Peer:
    name, status = "Sandbox Alpha", "ACTIVE"
    base_url = "https://sandbox-a.theprotocol.cloud:8443"
    federation_access_token = None


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows, self.added = rows, []

    async def execute(self, stmt):
        return _Rows(self.rows)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        pass


class _Settlement:
    id, dispute_id, ruling, requested_amount = "s-1", 50, "IN_FAVOR_OF_COMPLAINANT", 3
    complainant_did, defendant_did = "did:c", "did:d"
    origin_registry_url, callback_url = ORIGIN, ORIGIN + "/api/v1/federation/disputes/slash-confirmation"
    defendant_registry_url, error_message = "", None


def _count(msg: str) -> int:
    # the reconciliation's own parse (tasks/settlement_reconciliation._reconcile_single_settlement)
    return int(msg.split("retry_count=")[1].split(",")[0])


async def test_the_first_delivery_keeps_each_peers_refusal(monkeypatch):
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.identity import svid_client
    received = []

    class _Emitter:
        async def emit_dispute_compensation_request(self, **kw):
            received.append(kw["dispute_id"])
    monkeypatch.setattr(cd, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(cd.httpx, "AsyncClient", _client((400, REFUSAL)))
    monkeypatch.setattr(svid_client, "get_client_cert_config", lambda: None)

    class _Dispute:
        id, complainant_did, defendant_did = 50, "did:c", "did:d"
    db = _Db([_Peer()])
    await cd._process_cross_registry_compensation(db, _Dispute(), "IN_FAVOR_OF_COMPLAINANT", 3, {})
    (settlement,) = db.added
    assert received == [50]
    assert settlement.status == "PENDING_SLASH" and settlement.defendant_registry_url == ""
    assert settlement.error_message.startswith("Could not reach defendant's home registry: Sandbox Alpha 400: ")
    assert "its host sbx-beta-nginx-federation is under no active peer's base URL" in settlement.error_message


@pytest.mark.parametrize("answer,note", [
    ((400, REFUSAL), "Sandbox Alpha 400: Callback URL must belong to a registered peer registry"),
    ((404, '{"detail":"Not Found"}'), "Sandbox Alpha 404"),
    (httpx.ConnectError("connect to https://sandbox-a.theprotocol.cloud:8443 refused"), "Sandbox Alpha: ConnectError"),
])
async def test_a_retry_keeps_each_peers_answer_after_its_count(monkeypatch, answer, note):
    from agentvault_registry.tasks import settlement_reconciliation as rec
    monkeypatch.setattr(rec.httpx, "AsyncClient", _client(answer))
    monkeypatch.setattr(rec.svid_client, "get_client_cert_config", lambda: None)
    s = _Settlement()
    s.error_message = "retry_count=1, last_retry=2026-10-24T17:40:00+00:00"
    await rec._retry_slash_request(_Db([_Peer()]), s, 1)
    assert s.error_message.startswith("retry_count=2, last_retry=") and _count(s.error_message) == 2
    assert f", refused: {note}" in s.error_message
    assert "https://" not in s.error_message.split("refused:")[1]      # an exception by its type, never its text


def test_an_answer_is_bounded_and_reads_plain_text():
    assert settlement_origin.peer_answer("P", 502, "bad   gateway\n") == "P 502: bad gateway"
    assert len(settlement_origin.peer_answer("P", 400, '{"detail": "' + "x" * 900 + '"}')) <= len("P 400: ") + 160
    assert len(settlement_origin.answers_note(["y" * 400] * 3)) == 600

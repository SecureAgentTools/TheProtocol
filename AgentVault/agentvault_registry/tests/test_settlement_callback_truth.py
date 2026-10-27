"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): a settlement's home says whether it told the origin.

routers/federation_disputes.reject_settlement answered "Settlement rejected. Origin registry notified." whatever the
callback did, and both it and approve_settlement logged an exception and nothing else, while a refusal (a non-2xx) did
not even count as a failure. The origin of a confirmation it never heard ends the settlement only at its saga timeout,
so the home's answer is the one place an administrator learns it. Now one helper (_tell_origin) counts only a 2xx as
delivered, and both answers carry origin_notified; reject keeps its old words when the origin was told. The refusal
case fails on V0637's route (the control: it said "notified").
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import httpx
import pytest

from agentvault_registry.routers import federation_disputes as fd

CALLBACK = "https://origin.example.test/api/v1/federation/disputes/slash-confirmation"


class _Db:
    def __init__(self, settlement):
        self.settlement, self.commits = settlement, 0

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.settlement)

    async def commit(self):
        self.commits += 1


def _client(monkeypatch, answer):
    """httpx.AsyncClient as the router sees it: `answer` is an HTTP code, or an exception to raise."""
    posted = []

    class _Client:
        def __init__(self, **kw):
            self.kw = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted.append((url, json))
            if isinstance(answer, Exception):
                raise answer
            return SimpleNamespace(status_code=answer)
    monkeypatch.setattr(fd.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fd.svid_client, "get_client_cert_config", lambda: None)
    return posted


def _reject(settlement):
    db = _Db(settlement)
    out = asyncio.run(fd.reject_settlement("s1", None, current_admin=SimpleNamespace(email="admin@example.test"), db=db))
    return out, db


def _pending(callback=CALLBACK):
    return SimpleNamespace(id="s1", status="PENDING_ADMIN_APPROVAL", callback_url=callback, error_message=None)


def test_told_keeps_the_old_words(monkeypatch):
    posted = _client(monkeypatch, 200)
    out, db = _reject(_pending())
    assert out["status"] == "REJECTED" and out["origin_notified"] is True
    assert out["message"] == "Settlement rejected. Origin registry notified."
    assert posted == [(CALLBACK, posted[0][1])] and posted[0][1]["status"] == "failed" and posted[0][1]["amount"] == 0
    assert db.settlement.status == "REJECTED" and db.commits == 1


@pytest.mark.parametrize("answer, words", [
    (401, "it answered HTTP 401"),
    (503, "it answered HTTP 503"),
    (httpx.ConnectError("no route"), "it could not be reached: ConnectError"),
])
def test_a_refused_or_unreachable_origin_is_said(monkeypatch, answer, words):
    _client(monkeypatch, answer)
    out, db = _reject(_pending())
    assert out["status"] == "REJECTED" and db.settlement.status == "REJECTED"     # the rejection itself stands
    assert out["origin_notified"] is False
    assert out["message"].startswith("origin_not_notified: ")      # the code word first (agentvault2-d6)
    assert words in out["message"] and "Origin registry notified." not in out["message"]
    assert "ends the settlement at its own timeout" in out["message"]


def test_no_callback_address_is_said(monkeypatch):
    posted = _client(monkeypatch, 200)
    out, _ = _reject(_pending(callback=None))
    assert posted == [] and out["origin_notified"] is False and "names no callback address" in out["message"]
    assert out["message"].startswith("origin_not_notified: ")


def test_a_settlement_not_pending_is_answered_as_before(monkeypatch):
    posted = _client(monkeypatch, 200)
    s = _pending()
    s.status = "SETTLED"
    out, db = _reject(s)
    assert posted == [] and out["status"] == "SETTLED" and db.commits == 0


def test_approve_says_it_too():
    src = inspect.getsource(fd.approve_settlement)
    assert '"origin_notified": told' in src and "_tell_origin(settlement, confirmation" in src
    assert '"origin_not_notified: "' in src
    assert "client.post(" not in src          # one way to call the origin back, the helper's

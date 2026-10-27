"""§MCPTEST30 (V0557) — the Senate floor's reads of federal ballots, to agentvault2-33's spec (2026-10-03):

* GET /api/v1/governance/federation/proposals/{id}/ballots returns every ballot WHOLE (its signed envelope, so anyone
  can check it against the casting registry's card key), `verified_at_receipt` on each, never cached; a proposal this
  registry's store does not hold is 404 not_hosted_here, naming a host only when a frame peer's open list shows it.
* GET /api/v1/governance/federation-ballots carries this registry's members' vote on each open proposal, read at
  answer time from its own database (the peers' answers stay cached); the cache itself is never annotated.

No database and no network: the store and the database are recorders. Every refusal has a control.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from agentvault_registry.routers import federation_ballots as R

PID = "5f1c0b9e-0000-4000-8000-0000000000aa"
UTC = dt.timezone.utc


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DB:
    """Answers every select with `rows`; keeps the statements it was asked so a test can read the WHERE."""

    def __init__(self, rows=()):
        self.rows, self.asked = list(rows), []

    async def execute(self, stmt):
        self.asked.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return _Result(self.rows)


@pytest.fixture(autouse=True)
def _me(monkeypatch):
    monkeypatch.setattr(R.fb, "own_identity", lambda: {"trust_domain": "sandbox-b.test", "name": "Sandbox Beta",
                                                        "id": "registry:sandbox-b.test/sandbox-beta", "card_spiffe": ""})
    R._OPEN_CACHE.update(at=0.0, doc=None)
    yield
    R._OPEN_CACHE.update(at=0.0, doc=None)


def _store(monkeypatch, proposal=(200, None), ballots=(200, None)):
    calls = []

    async def fake_es(method, path, json_body=None):
        calls.append((method, path))
        if path.endswith("/ballots"):
            return ballots
        return proposal

    monkeypatch.setattr(R.fb, "_es", fake_es)
    return calls


def _envelope(choice="for"):
    return {"ballot": {"kind": "tp.federation.ballot.v1", "proposal_id": PID, "choice": choice,
                       "voter": {"id": "registry:sandbox-a.test/sandbox-alpha"},
                       "basis": {"mode": "members", "voters": 2, "points_for": 108.0, "points_against": 100.0,
                                 "local_proposal_id": 271}},
            "alg": "EdDSA", "kid": "spiffe://sandbox-a.test/registry/sandbox-alpha#1", "signature": "c2ln"}


def _row(choice="for", raw=None):
    env = _envelope(choice)
    return {"registry_id": "registry:sandbox-a.test/sandbox-alpha", "choice": choice, "basis": env["ballot"]["basis"],
            "eligibility": {"licence_ok": True, "track_ok": False, "reasons": ["a provisional track record"]},
            "ballot_jws": raw if raw is not None else json.dumps(env, sort_keys=True), "cast_at": "2026-10-03T10:40:00+00:00"}


PROPOSAL = {"id": PID, "status": "VOTING", "ballot_mode": True, "ballot_summary": None}


async def test_a_hosted_proposal_returns_every_ballot_whole_and_verified_at_receipt(monkeypatch):
    _store(monkeypatch, proposal=(200, PROPOSAL), ballots=(200, {"ballots": [_row()]}))
    out = (await R.federation_proposal_ballots(PID, actor={}, db=_DB()))
    assert out["host"] == {"trust_domain": "sandbox-b.test", "name": "Sandbox Beta", "id": "registry:sandbox-b.test/sandbox-beta"}
    assert out["ballot_mode"] is True and out["status"] == "VOTING"
    (b,) = out["ballots"]
    # the envelope arrives as a document, not as the store's JSON text, signature and kid included
    assert b["envelope"]["kid"] == "spiffe://sandbox-a.test/registry/sandbox-alpha#1" and b["envelope"]["signature"]
    assert b["envelope"]["ballot"]["basis"]["points_for"] == 108.0
    assert b["verified_at_receipt"] is True and b["choice"] == "for" and b["cast_at"]


async def test_the_read_is_never_cached(monkeypatch):
    _store(monkeypatch, proposal=(200, PROPOSAL), ballots=(200, {"ballots": []}))
    assert (await R.federation_proposal_ballots(PID, actor={}, db=_DB()))["ballots"] == []
    calls = _store(monkeypatch, proposal=(200, PROPOSAL), ballots=(200, {"ballots": [_row()]}))
    assert len((await R.federation_proposal_ballots(PID, actor={}, db=_DB()))["ballots"]) == 1   # a ballot that landed shows
    assert ("GET", f"/proposals/{PID}/ballots") in calls


async def test_an_unreadable_envelope_is_none_never_a_guess(monkeypatch):
    _store(monkeypatch, proposal=(200, PROPOSAL), ballots=(200, {"ballots": [_row(raw="not json")]}))
    (b,) = (await R.federation_proposal_ballots(PID, actor={}, db=_DB()))["ballots"]
    assert b["envelope"] is None and b["choice"] == "for"


async def test_a_proposal_hosted_elsewhere_names_the_host_only_when_a_peer_lists_it(monkeypatch):
    _store(monkeypatch, proposal=(404, {"detail": "not found"}))

    async def seen(actor, db):
        return {"hosts": [{"host": "self", "proposals": []},
                          {"host": "Sandbox Alpha", "name": "Sandbox Alpha", "trust_domain": "sandbox-a.test",
                           "proposals": [{"id": PID}]}]}

    monkeypatch.setattr(R, "federation_ballots_open", seen)
    r = (await R.federation_proposal_ballots(PID, actor={}, db=_DB()))
    body = json.loads(r.body)
    assert r.status_code == 404 and body["error"] == "not_hosted_here"
    assert body["host"] == {"name": "Sandbox Alpha", "trust_domain": "sandbox-a.test"}

    async def unseen(actor, db):          # the control: a closed proposal is in no open list, so no host is named
        return {"hosts": [{"host": "self", "proposals": []},
                          {"host": "Sandbox Alpha", "name": "Sandbox Alpha", "trust_domain": "sandbox-a.test",
                           "proposals": [{"id": "5f1c0b9e-0000-4000-8000-0000000000bb"}]}]}

    monkeypatch.setattr(R, "federation_ballots_open", unseen)
    body = json.loads((await R.federation_proposal_ballots(PID, actor={}, db=_DB())).body)
    assert body["error"] == "not_hosted_here" and "host" not in body


async def test_a_bad_id_and_an_unreadable_store_say_so(monkeypatch):
    r = (await R.federation_proposal_ballots("not-a-uuid", actor={}, db=_DB()))
    assert r.status_code == 422 and json.loads(r.body)["error"] == "bad_proposal_id"
    _store(monkeypatch, proposal=(503, {"raw": "down"}))
    r = (await R.federation_proposal_ballots(PID, actor={}, db=_DB()))
    assert r.status_code == 502 and json.loads(r.body)["error"] == "store_unreadable"
    _store(monkeypatch, proposal=(200, PROPOSAL), ballots=(500, {"raw": "x"}))
    r = (await R.federation_proposal_ballots(PID, actor={}, db=_DB()))
    assert r.status_code == 502 and json.loads(r.body)["error"] == "store_unreadable"


async def test_the_open_list_carries_this_registrys_members_vote_and_never_annotates_the_cache():
    peer_pid, self_pid = PID, "5f1c0b9e-0000-4000-8000-0000000000cc"
    doc = {"ballot_mode": True, "hosts": [
        {"host": "self", "name": "Sandbox Beta", "trust_domain": "sandbox-b.test", "proposals": [{"id": self_pid}]},
        {"host": "Sandbox Alpha", "name": "Sandbox Alpha", "trust_domain": "sandbox-a.test",
         "proposals": [{"id": peer_pid}]}]}
    later = dt.datetime.now(UTC) + dt.timedelta(minutes=40)
    db = _DB(rows=[(271, later.replace(tzinfo=None), f"sandbox-a.test/{peer_pid}")])   # a naive end reads as UTC
    out = (await R._with_local_votes(db, doc))
    peer = out["hosts"][1]["proposals"][0]
    assert peer["local_vote"]["local_proposal_id"] == 271 and peer["local_vote"]["open"] is True
    assert out["hosts"][0]["proposals"][0]["local_vote"] is None          # the control: no members' vote on that one
    # the WHERE asks exactly the refs the local-vote and cast routes derive: <host trust domain>/<proposal id>
    assert f"sandbox-a.test/{peer_pid}" in db.asked[0] and f"sandbox-b.test/{self_pid}" in db.asked[0]
    assert "local_vote" not in doc["hosts"][1]["proposals"][0]              # the cached document stays as the peers said


async def test_a_closed_members_vote_reads_closed():
    earlier = dt.datetime.now(UTC) - dt.timedelta(minutes=5)
    doc = {"hosts": [{"host": "Sandbox Alpha", "trust_domain": "sandbox-a.test", "proposals": [{"id": PID}]}]}
    out = await R._with_local_votes(_DB(rows=[(271, earlier, f"sandbox-a.test/{PID}")]), doc)
    assert out["hosts"][0]["proposals"][0]["local_vote"]["open"] is False


async def test_no_open_proposal_asks_the_database_nothing():
    db = _DB()
    out = (await R._with_local_votes(db, {"hosts": [{"host": "self", "trust_domain": "x.test", "proposals": []}]}))
    assert out["hosts"][0]["proposals"] == [] and db.asked == []

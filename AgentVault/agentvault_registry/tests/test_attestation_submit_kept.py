"""V0659 (a), on the way: POST /api/v1/teg/attestations/submit keeps its answer under the caller's Idempotency-Key, and
the attestor role carries reputation.signal and nothing else.

TheProtocol Proxy sends every record's call with the record's exactly-once key as its Idempotency-Key, and sends it
again when an answer was lost. This route took no key: a repeat reached the TEG a second time, which refuses a second
copy of the same data (409, "already submitted"), so the proxy could tell "done before" from "done now" only by that
word, and never got the first answer (the attestation's id) back. Now a repeat under the key answers the first answer,
marked Idempotent-Replayed, without reaching the TEG; an error answer gives the key back (an attestation moves nothing,
and the TEG refuses a second copy of the same data, so running it again is safe); a key with another body is refused.

And the role: a proxy that turns a legacy system's records into attestations needs reputation.signal, which only the
service-provider role carried (with a2a.collect, contracts.engage, disputes.file and identity.mtls, none of which a
sensor's proxy should hold). The attestor role carries reputation.signal alone. Red on 13d2011ac: the route takes no
key and there is no attestor role.
"""
import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi import HTTPException, Response

from agentvault_registry import agent_authz
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services.idempotency import cache
from tests.test_idempotency_per_caller import FakeRedis

DID = "did:theprotocol:proxy-attestor-0001"


class _Agent:
    id = 42
    did = DID


class FakeTEG:
    """The TEG's /attestation/submit: a submission per (agent, type, hash), a second copy refused 409."""

    def __init__(self):
        self.posts = []
        self.kept = {}
        self.mode = "ok"            # "ok" | "down" (503) | "lose" (keeps it, the answer never arrives)

    def answer(self, url, json_body):
        self.posts.append(json_body)
        if self.mode == "down":
            return httpx.Response(503, json={"detail": "busy"})
        k = (json_body["agent_did"], json_body["attestation_type"], json_body["attestation_hash"])
        if k in self.kept:
            # what the TEG answers (endpoints_attestation: TEGException(409, message=...) through its HTTPException
            # handler: the message is the body's detail)
            return httpx.Response(409, json={"detail": "Attestation already submitted", "type": "conflict"})
        self.kept[k] = f"sub-{len(self.kept) + 1}"
        if self.mode == "lose":
            raise httpx.ReadTimeout("the answer was lost")
        return httpx.Response(200, json={"submission_id": self.kept[k], "agent_did": json_body["agent_did"],
                                         "attestation_type": json_body["attestation_type"], "status": "pending"})


@pytest.fixture
def world(monkeypatch):
    r = FakeRedis()
    teg = FakeTEG()
    emitted = []

    async def _get():
        return r

    async def _token(agent_id, did):
        return "teg-token"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            return teg.answer(url, json)

    async def _emit(**kw):
        emitted.append(kw)

    from agentvault_registry.background_tasks import leader
    from agentvault_registry import crud_agent_enhanced
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setenv("IDEMPOTENCY_DURABLE", "off")
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.005)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _token)
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(crud_agent_enhanced, "emit_attestation_event", _emit)
    return {"redis": r, "teg": teg, "emitted": emitted}


def _req(**over):
    body = {"target_agent_did": DID, "attestation_type": "tos.gate_out",
            "attestation_data": {"claim": {"container": "MSKU1234567"}, "record": "tpx-abc"},
            "metadata": {"proxy": "gate-scanner", "record": "tpx-abc"}}
    body.update(over)
    return ti.TEGAttestationRequest(**body)


def _submit(req, key=None):
    resp = Response()

    async def _go():
        out = await ti.submit_attestation(req, current_agent=_Agent(), idempotency_key=key, http_response=resp)
        return out, resp
    return asyncio.run(_go())


def _id(out):
    return out["attestation_id"] if isinstance(out, dict) else out.attestation_id


def test_a_repeat_under_the_key_answers_the_first_answer_without_reaching_the_teg(world):
    first, r1 = _submit(_req(), key="tpx-abc")
    again, r2 = _submit(_req(), key="tpx-abc")
    assert _id(first) == _id(again) == "sub-1"
    assert len(world["teg"].posts) == 1 and len(world["emitted"]) == 1, "the TEG and the ledger heard it once"
    assert r2.headers.get(cache.REPLAYED_HEADER) == "true" and cache.REPLAYED_HEADER not in r1.headers


def test_an_error_gives_the_key_back_and_the_retry_runs(world):
    world["teg"].mode = "down"
    with pytest.raises(HTTPException) as e:
        _submit(_req(), key="tpx-abc")
    assert e.value.status_code == 503
    world["teg"].mode = "ok"
    out, _ = _submit(_req(), key="tpx-abc")
    assert _id(out) == "sub-1" and len(world["teg"].posts) == 2 and len(world["emitted"]) == 1


def test_a_lost_answer_run_again_meets_the_teg_s_refusal_of_a_second_copy(world):
    world["teg"].mode = "lose"
    with pytest.raises(HTTPException) as e:
        _submit(_req(), key="tpx-abc")
    assert e.value.status_code == 503, "the TEG kept it; the registry could not know"
    world["teg"].mode = "ok"
    with pytest.raises(HTTPException) as dup:
        _submit(_req(), key="tpx-abc")
    # what TheProtocol Proxy's attestation action reads as done: the same data is on the ledger
    assert dup.value.status_code == 409 and "already submitted" in str(dup.value.detail).lower()
    assert len(world["teg"].kept) == 1


def test_without_a_key_it_runs_as_before(world):
    _submit(_req())
    with pytest.raises(HTTPException) as dup:
        _submit(_req())
    assert dup.value.status_code == 409 and len(world["teg"].posts) == 2


def test_the_key_with_another_body_is_refused(world):
    _submit(_req(), key="tpx-abc")
    with pytest.raises(HTTPException) as e:
        _submit(_req(attestation_type="tos.gate_in"), key="tpx-abc")
    assert e.value.status_code == 422 and len(world["teg"].posts) == 1


def test_another_callers_key_is_its_own(world):
    _submit(_req(), key="tpx-abc")

    class _Other:
        id = 43
        did = "did:theprotocol:someone-else-0002"

    async def _go():
        return await ti.submit_attestation(_req(), current_agent=_Other(), idempotency_key="tpx-abc",
                                           http_response=Response())
    out = asyncio.run(_go())
    assert _id(out) == "sub-2" and len(world["teg"].posts) == 2


def test_the_hash_the_teg_keeps_is_of_the_data_the_caller_sent(world):
    req = _req()
    _submit(req, key="tpx-abc")
    want = hashlib.sha256(json.dumps(req.attestation_data, sort_keys=True).encode()).hexdigest()
    assert world["teg"].posts[0]["attestation_hash"] == want


# ── the attestor role ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_attestor_role_carries_reputation_signal_and_nothing_else():
    assert agent_authz.ROLE_PERMISSIONS["attestor"] == agent_authz.BASE_PERMISSIONS | {"reputation.signal"}


def test_an_owner_can_grant_the_attestor_role_and_it_widens_no_developer_s_delegation():
    from agentvault_registry.routers import agent_authz_api
    assert "attestor" in agent_authz_api.ASSIGNABLE_ROLES
    without = set().union(*(p for r, p in agent_authz.ROLE_PERMISSIONS.items() if r not in ("legacy-full", "attestor")))
    assert agent_authz.DEV_DELEGATABLE_PERMISSIONS == frozenset(without | {"authz.delegate"})

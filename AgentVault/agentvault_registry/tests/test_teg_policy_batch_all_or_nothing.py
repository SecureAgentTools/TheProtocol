"""D6-828 (agentvault2-d6, 2026-10-25): POST /api/v1/teg/policies/batch is all or nothing, as its docstring always said.

The route's old "dry run" loop CREATED each policy at the TEG and undid nothing: a batch whose every policy was refused
answered 200 (success_count 0 and the errors), and a later refusal left the earlier policies live in an "atomic" batch
(agentvault2-66 found it reading code for the V0641 tester). The TEG's delete is a deactivation and its create conflicts
only with a LIVE policy, so the registry rolls back by deactivating what it created and answers the refusal. These tests
drive the route against a scripted TEG: every POST and DELETE it sends is recorded, so "nothing from this batch is live"
is read from the calls, never from the answer alone.
"""
import json
import types

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.routers import teg_integration as ti


def _answer(code, pid):
    return {"policy_id": pid, "policy_code": code, "policy_name": f"name {code}", "policy_type": "compliance",
            "policy_version": "1.0.0", "description": None, "parameters": json.dumps({"k": 1}),
            "circuit_identifier": None, "enforcement_level": "optional", "reward_amount": "0",
            "rules_document_url": None, "is_active": True,
            "created_at": "2026-10-25T07:00:00Z", "updated_at": "2026-10-25T07:00:00Z"}


class _Resp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body) if body is not None else ""
        self.headers = {"content-type": "application/json"}

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


class _TEG:
    """The TEG's policy routes as a script: POST answers the next entry (an exception is raised), DELETE answers
    `delete_status` (or raises it), and every call is recorded in order."""

    def __init__(self, posts, delete_status=200):
        self.posts = list(posts)
        self.delete_status = delete_status
        self.calls = []

    def client(self, *args, **kwargs):
        return _Client(self)


class _Client:
    def __init__(self, teg):
        self.teg = teg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        self.teg.calls.append(("POST", json["policy_code"]))
        nxt = self.teg.posts.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def delete(self, url, headers=None, timeout=None):
        pid = url.rsplit("/", 1)[1]
        self.teg.calls.append(("DELETE", pid))
        if isinstance(self.teg.delete_status, Exception):
            raise self.teg.delete_status
        return _Resp(self.teg.delete_status, {"message": f"Policy {pid} deactivated"})


@pytest.fixture
def rig(monkeypatch):
    audit = []
    monkeypatch.setattr(ti, "log_audit_event", lambda **kw: audit.append(kw))
    monkeypatch.setattr(ti, "get_httpx_verify", lambda: False)

    def make(posts, delete_status=200):
        teg = _TEG(posts, delete_status)
        monkeypatch.setattr(ti.httpx, "AsyncClient", teg.client)
        return teg

    make.audit = audit
    return make


def _batch(*codes):
    return ti.TEGPolicyBatchRequest(policies=[
        ti.TEGPolicyRequest(policy_code=c, policy_name=f"name {c}", policy_type="compliance") for c in codes])


ADMIN = types.SimpleNamespace(email="admin@example.test")


async def _run(batch):
    return await ti.create_teg_policies_batch(request=batch, current_developer=ADMIN)


async def test_a_whole_batch_is_created_and_answered_200(rig):
    teg = rig([_Resp(200, _answer("P1", "id-1")), _Resp(200, _answer("P2", "id-2")), _Resp(200, _answer("P3", "id-3"))])
    out = await _run(_batch("P1", "P2", "P3"))
    assert (out.success_count, out.failure_count, out.errors) == (3, 0, [])
    assert [p.policy_id for p in out.created_policies] == ["id-1", "id-2", "id-3"]
    assert out.created_policies[0].parameters == {"k": 1}
    assert teg.calls == [("POST", "P1"), ("POST", "P2"), ("POST", "P3")]   # nothing deactivated


async def test_a_refusal_midway_deactivates_what_was_created_and_answers_the_refusal(rig):
    teg = rig([_Resp(200, _answer("P1", "id-1")), _Resp(200, _answer("P2", "id-2")),
               _Resp(409, {"detail": "Policy with code P3 already exists"}), _Resp(200, _answer("P4", "id-4"))])
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2", "P3", "P4"))
    assert e.value.status_code == 409
    assert "policy 2 (P3) was refused" in e.value.detail and "already exists" in e.value.detail
    assert "the 2 created before it were deactivated again; nothing from this batch is live" in e.value.detail
    # newest first, and P4 was never sent
    assert teg.calls == [("POST", "P1"), ("POST", "P2"), ("POST", "P3"), ("DELETE", "id-2"), ("DELETE", "id-1")]
    rolled = [a for a in rig.audit if a["action"] == "POLICY_BATCH_ROLLED_BACK"]
    assert len(rolled) == 1 and rolled[0]["details"]["deactivated"] == ["id-1", "id-2"]
    assert rolled[0]["details"]["still_live"] == []


async def test_a_batch_whose_first_policy_is_refused_is_a_refusal_not_a_200(rig):
    teg = rig([_Resp(422, {"detail": "policy_type must be one of attestation, governance, compliance, economic"})])
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2"))
    assert e.value.status_code == 422
    assert "policy 0 (P1) was refused" in e.value.detail and "nothing from this batch is live" in e.value.detail
    assert teg.calls == [("POST", "P1")]


async def test_a_code_named_twice_is_refused_before_anything_is_written(rig):
    teg = rig([])
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2", "P1"))
    assert e.value.status_code == 422 and "P1" in e.value.detail and "nothing was created" in e.value.detail
    assert teg.calls == []


async def test_an_unreachable_teg_midway_rolls_back_and_answers_503(rig):
    teg = rig([_Resp(200, _answer("P1", "id-1")), httpx.ConnectError("connection refused")])
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2"))
    assert e.value.status_code == 503 and "nothing from this batch is live" in e.value.detail
    assert teg.calls == [("POST", "P1"), ("POST", "P2"), ("DELETE", "id-1")]


async def test_a_policy_that_cannot_be_deactivated_is_named_live_in_a_500(rig):
    teg = rig([_Resp(200, _answer("P1", "id-1")), _Resp(409, {"detail": "Policy with code P2 already exists"})],
              delete_status=500)
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2"))
    assert e.value.status_code == 500 and "still live: id-1" in e.value.detail
    assert teg.calls == [("POST", "P1"), ("POST", "P2"), ("DELETE", "id-1")]


async def test_a_200_without_a_policy_id_rolls_back_the_rest_and_says_it_may_be_live(rig):
    teg = rig([_Resp(200, _answer("P1", "id-1")), _Resp(200, {"message": "created"})])
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2"))
    assert e.value.status_code == 502 and "may be live" in e.value.detail
    assert teg.calls == [("POST", "P1"), ("POST", "P2"), ("DELETE", "id-1")]


async def test_an_answer_the_route_cannot_read_is_rolled_back_with_its_own_policy(rig):
    broken = _answer("P2", "id-2")
    del broken["created_at"]
    teg = rig([_Resp(200, _answer("P1", "id-1")), _Resp(200, broken)])
    with pytest.raises(HTTPException) as e:
        await _run(_batch("P1", "P2"))
    assert e.value.status_code == 502 and "could not be read (KeyError)" in e.value.detail
    assert teg.calls == [("POST", "P1"), ("POST", "P2"), ("DELETE", "id-2"), ("DELETE", "id-1")]


def test_the_docstring_says_all_or_nothing_and_no_dry_run_creates():
    doc = ti.create_teg_policies_batch.__doc__ or ""
    assert "all or nothing" in doc and "deactivated again" in doc
    assert "single atomic transaction" not in doc

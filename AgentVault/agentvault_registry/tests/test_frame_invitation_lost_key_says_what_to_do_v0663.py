"""D6-343 (V0663, gwo_49ccc7efec6ae43112f5bd72): the two refusals about a lost licence key no longer contradict each other.

The joining frame's licence-key read answered 404 "Ask the approver's admin for a finalize-retry, which rotates the licence and
delivers a new key", and the finalize-retry on a COMPLETED invitation answered 409 "only applies to status='approved' with
completed_at=null": the admin followed one answer into the other. What is true (oracle/18, "The admission key is collected
once"): once the callback has landed a retry cannot replace the key; the joining frame sends a new invitation, whose approval
issues a new key. Both answers say that now. Words only: no status, no code path and no key handling changed.
RED control: against b27f2ebaf the 404 sends the admin to finalize-retry and the 409 names no way forward.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import frame_invitations as fi


class _Db:
    def __init__(self, inv):
        self._inv = inv

    async def execute(self, *a, **k):
        inv = self._inv
        return SimpleNamespace(scalar_one_or_none=lambda: inv)


def _inv(status, completed):
    return SimpleNamespace(id="inv-1", status=status, completed_at=completed, initiator_trust_domain="joiner.example.org")


def test_the_licence_key_read_does_not_send_the_admin_to_a_retry_that_refuses(monkeypatch):
    import agentvault_registry.background_tasks.leader as leader

    class R:
        async def get(self, k): return None
        async def delete(self, k): return 0

    async def get_redis(): return R()

    monkeypatch.setattr(leader, "get_redis", get_redis)
    with pytest.raises(HTTPException) as e:
        asyncio.run(fi.take_parked_licence_key("inv-1", _Db(_inv("completed", datetime.now(timezone.utc)))))
    assert e.value.status_code == 404
    d = e.value.detail
    assert "send a new invitation" in d and "issues a new key" in d
    assert "Ask the approver's admin for a finalize-retry, which rotates" not in d


def test_finalize_retry_on_a_completed_invitation_says_a_new_invitation_is_the_way():
    with pytest.raises(HTTPException) as e:
        asyncio.run(fi.finalize_retry_frame_invitation("inv-1", _Db(_inv("completed", datetime.now(timezone.utc)))))
    assert e.value.status_code == 409
    assert "only applies to status='approved'" in e.value.detail          # the existing sentence stays
    assert "the joining frame sends a new invitation" in e.value.detail


def test_finalize_retry_on_a_pending_invitation_keeps_its_plain_refusal():
    with pytest.raises(HTTPException) as e:
        asyncio.run(fi.finalize_retry_frame_invitation("inv-1", _Db(_inv("pending", None))))
    assert e.value.status_code == 409
    assert "new invitation" not in e.value.detail                          # nothing landed, so nothing to say about a lost key

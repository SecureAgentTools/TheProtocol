"""§MCPTEST30 (V0550): the admin slash route says why it refused.

POST /admin/enforcement/agents/{did}/slash-stake answered 400 "An internal error occurred" for every ForceUnstakeError:
a DID with no agent, an agent with nothing staked, a TEG that did not unlock. An admin read a server fault where the
answer was "no such agent" (agentvault2-45 found it pinning the sweep's refusals, 2026-10-02). Each reason has its
class now and the route maps it: 404, 409, 502 (the TEG's own text logged, never returned), else 400 with the sentence.
"""
from __future__ import annotations

from agentvault_registry.routers.enforcement_admin import _slash_refusal
from agentvault_registry.services import force_unstake as fu


def test_each_reason_answers_its_own_status_and_sentence():
    e = _slash_refusal(fu.AgentNotFoundError("Agent not found: did:theprotocol:phase6-no-such-agent"))
    assert (e.status_code, e.detail) == (404, "Agent not found: did:theprotocol:phase6-no-such-agent")
    e = _slash_refusal(fu.NoActiveStakeError("Agent did:x has no active lock positions to unlock"))
    assert e.status_code == 409 and "no active lock positions" in e.detail
    assert _slash_refusal(fu.InsufficientStakeError("not enough locked")).status_code == 409
    e = _slash_refusal(fu.ForceUnstakeError("required_amount must be positive"))
    assert (e.status_code, e.detail) == (400, "required_amount must be positive")


def test_the_teg_failure_is_said_without_the_tegs_own_words():
    e = _slash_refusal(fu.TegUnlockError("TEG unlock failed: http://teg-internal:8080/api/v1 refused. Transaction rolled back."))
    assert e.status_code == 502
    assert "teg-internal" not in e.detail and "rolled back" in e.detail


def test_every_reason_is_still_a_force_unstake_error():
    """The enforcement engine catches ForceUnstakeError; the new classes must stay inside it."""
    for cls in (fu.AgentNotFoundError, fu.NoActiveStakeError, fu.TegUnlockError, fu.InsufficientStakeError):
        assert issubclass(cls, fu.ForceUnstakeError)


def test_the_old_reasonless_answer_is_gone():
    import inspect
    from agentvault_registry.routers import enforcement_admin
    assert "An internal error occurred" not in inspect.getsource(enforcement_admin.slash_stake_execute)

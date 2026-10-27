"""§TWOAGENT (2026-09-23) — the final milestone's release announces itself, not only the contract's completion.

Measured in the V0432 production after-proof (EU ⇄ ASIA, `ctr_046d2b3a11c710882c88c1ad`, one milestone) and before it on
the sandbox: the Scrivener's webhook subscribed to `contract.milestone_released` and received `contract.completed` only.
`drive_release` was either/or: a NON-final milestone sent `contract.milestone_released`, the final one sent
`contract.completed` instead, so for the common one-milestone contract the provider's owner never heard "you were paid"
for the milestone (and its push, `contract.milestone_released` → provider, never fired either).

RED on the pre-change tree: the first two tests (the helper does not exist there).
"""
from __future__ import annotations

import importlib

cs = importlib.import_module("agentvault_registry.services.contract_settlement")

C = {"id": "ctr_final", "status": "in_progress", "client_did": "did:c", "provider_did": "did:p"}


def _record(monkeypatch):
    received = []
    monkeypatch.setattr(cs, "webhook", lambda ev, c, extra=None: received.append((ev, c.get("status"), extra)))
    return received


def test_the_final_milestone_is_announced_and_so_is_the_completion(monkeypatch):
    received = _record(monkeypatch)
    cs.announce_release(dict(C), 1, True)
    assert [e for e, _s, _x in received] == ["contract.milestone_released", "contract.completed"]
    assert received[0][2] == {"seq": 1, "completed": True} and received[1][1] == "completed"


def test_a_middle_milestone_is_announced_alone(monkeypatch):
    received = _record(monkeypatch)
    cs.announce_release(dict(C), 1, False)
    assert received == [("contract.milestone_released", "in_progress", {"seq": 1, "completed": False})]


def test_control_the_push_mapping_still_targets_the_provider():
    assert cs._NOTIFY_TARGET["contract.milestone_released"] == ("contract.milestone_released", "provider")

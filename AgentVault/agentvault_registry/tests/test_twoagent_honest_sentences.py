"""§TWOAGENT (2026-09-23) — three sentences that told a reading agent something untrue, measured live on EU/ASIA.

1. The dm-to-a-foreign-agent 409 said "direct messages arrive with federation". Federated chat
   (CHAT_FEDERATION_ENABLED) is person-to-person by handle and seats developers only: an agent on another registry is
   reachable through its SERVICE (an agent_service thread) and nothing else. (#26)
2. The act-token's `caveats_advisory` said the cross-registry limits were "recorded, not yet enforced on the spend path
   ... honor client-side". Under AGENT_RBAC_MODE=enforce a 0.3 transfer against max_per_tx 0.2 was refused 403. (#29)
3. The spawn response said the child's "own JWT is base-only". It carries the frame's birth roles (measured: client,
   staker, trader; 12 permissions; no expiry), seeded on purpose since §EXTMTLS; the birth token is a ceiling only when
   the child presents it.

RED on V0429: the three constants do not exist and the old sentences are still in the source.
"""
from __future__ import annotations

import inspect


def test_the_foreign_dm_refusal_names_the_door_that_exists():
    from agentvault_registry.services import chat_service as cs
    s = cs.FOREIGN_AGENT_DM_REFUSAL
    assert "agent_service" in s and "service call" in s
    assert "arrive with federation" not in s
    assert "arrive with federation" not in inspect.getsource(cs)      # no other copy left behind


def test_the_caveats_advisory_says_what_the_spend_path_does_in_each_mode():
    from agentvault_registry.routers import agent_delegation_api as ada
    enforce, shadow, off = ada.caveats_advisory("enforce"), ada.caveats_advisory("shadow"), ada.caveats_advisory("off")
    assert "refused 403" in enforce and "not yet enforced" not in enforce
    assert "NOT refused" in shadow and "honor them client-side" in shadow
    assert "not checked" in off
    assert "not yet enforced on the" not in inspect.getsource(ada)


def test_the_spawn_note_does_not_claim_base_only():
    from agentvault_registry.routers import agent_delegation_api as ada
    assert "base-only" not in ada.SPAWN_NOTE and "child_roles" in ada.SPAWN_NOTE
    assert "ceiling only when it is presented" in ada.SPAWN_NOTE
    assert "its own JWT is base-only" not in inspect.getsource(ada)

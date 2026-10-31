"""§DOCSFIX D6-556 (2026-10-16): a client that types a rail-only card is told which rail writes it.

The card validator refused every rail-only card a client typed with one sentence: "written only by the service-call
rail, a client cannot author a service record". Only `service.call` and `service.result` are written by that rail; a
holding certificate comes from the registry's certificate rail, an organization's work receipt from its money rails,
and the four engagement cards from the contract rail. The refusal now names the rail of the type it refused (still a
refusal for every one of them; a rail author still passes).
"""
from __future__ import annotations

import pytest

from agentvault_registry.services import chat_service as cs

RAIL = {
    "service.call": "service-call rail",
    "service.result": "service-call rail",
    "share.certificate": "certificate rail",
    "org.work.receipt": "money rails",
    "engagement.offer": "contract rail",
    "engagement.accepted": "contract rail",
    "engagement.milestone": "contract rail",
    "engagement.settled": "contract rail",
    "approval.request": "chat approval rail",      # V0650 (l)
    "approval.decided": "chat approval rail",
}


def test_the_table_covers_every_rail_only_type():
    assert set(RAIL) == set(cs.RAIL_ONLY_CARDS), "a new rail-only card needs its rail named here and in the service"


@pytest.mark.parametrize("ctype", sorted(RAIL))
def test_the_refusal_names_the_rail_that_writes_the_type(ctype):
    reason = cs.validate_card({"v": 1, "type": ctype, "data": {}}, rail_author=False)
    assert reason and reason.startswith(f"card type {ctype!r} is written only by"), reason
    assert RAIL[ctype] in reason, reason
    if RAIL[ctype] != "service-call rail":
        assert "service-call" not in reason and "service record" not in reason, reason


def test_a_rail_author_is_not_refused_for_being_a_client():
    reason = cs.validate_card({"v": 1, "type": "share.certificate", "data": {}}, rail_author=True)
    assert not (reason or "").startswith("card type 'share.certificate' is written only by"), reason

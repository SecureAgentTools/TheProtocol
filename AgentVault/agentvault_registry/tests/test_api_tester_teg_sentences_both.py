"""W1/W4 (agentvault2-aa, 2026-10-25): the API tester reads the TEG's two refusals it matches in their old and new words.

agentvault2-69 rewords the TEG's sentences for the opening (fix/teg-compliant-sentences from a9cad595, his words that day:
"i want the illegal wording completly gone before opening"): "Cannot transfer tokens to yourself" becomes "Cannot transfer
units to yourself", "Active stake not found" becomes "Active lock not found". The tester's expected-failure rules matched
the old words at seven sites; until every TEG runs the new image either TEG may answer, so each rule takes both
(agentvault2-d6's order: "your contracts accept BOTH the old and the new sentence, so the TEG roll order no longer
matters"). Pinned here: both helpers, and that no site reads the old words alone.
"""
from __future__ import annotations

import inspect

from agentvault_registry.routers import admin_api_test as A


def test_a_transfer_to_oneself_is_read_in_either_words():
    for body in ({"detail": "Cannot transfer tokens to yourself"}, {"detail": "Cannot transfer units to yourself"},
                 '{"detail":"Cannot transfer units to yourself","type":"about:blank","status":400}'):
        assert A._self_transfer_refusal(body), body
    for body in ({"detail": "Insufficient balance"}, {"detail": "Cannot transfer units"}, None, ""):
        assert not A._self_transfer_refusal(body), body


def test_a_missing_lock_is_read_in_either_words():
    assert A._no_active_lock({"detail": "Active stake not found"}) and A._no_active_lock({"detail": "Active lock not found"})
    assert not A._no_active_lock({"detail": "Local proposal not found"}) and not A._no_active_lock(None)


def test_no_rule_reads_the_old_words_alone():
    src = inspect.getsource(A)
    assert '"cannot transfer tokens to yourself" in' not in src and '"active stake not found" in str' not in src
    assert src.count("_self_transfer_refusal(response_data)") == 4, "the four expected-failure rules"
    assert src.count("_no_active_lock(response_data)") + src.count("_no_active_lock(_rd)") == 3

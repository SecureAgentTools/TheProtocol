"""V0658 (l), code-scanning #41 (py/polynomial-redos, 2026-11-07, session-watch): the e-mail redaction's quantifiers
are bounded.

withhold_personal_ids runs _EMAIL_ADDRESS_RE over caller-shaped values on the way to a PUBLIC answer. The pattern had
an unbounded run of labels (`[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+`), which backtracks across the group boundary on a long
non-matching tail. The bounds are the RFC's own (local part 64, label 63, ten labels), so the language it accepts is
unchanged for every address that can exist.

⚠ The invariant is pinned STRUCTURALLY, not by a stopwatch. A polynomial regex is still quick on a modest input, so a
timing assertion would either pass on the old pattern or need an input big enough to be slow and flaky. The behaviour
cases below pass on both patterns on purpose: they are the controls that the bound did not change what is redacted.
RED on e70fb58b2: test_every_quantifier_in_the_pattern_is_bounded.
"""
from __future__ import annotations

import re
import time

import pytest

from agentvault_registry.identifiers import EMAIL_WITHHELD, _EMAIL_ADDRESS_RE, withhold_personal_ids


# --- the invariant the fix is about ---------------------------------------------------------------------------------
def test_every_quantifier_in_the_pattern_is_bounded():
    """No bare + or * on a character class: each run carries a {m,n}, so the backtracking budget is fixed."""
    pat = _EMAIL_ADDRESS_RE.pattern
    unbounded = re.findall(r"\][+*]", pat)
    assert unbounded == [], f"an unbounded quantifier follows a character class in {pat!r}"


def test_the_bounds_are_the_rfc_ones():
    pat = _EMAIL_ADDRESS_RE.pattern
    assert "{1,64}" in pat and "{1,63}" in pat, pat


# --- controls: the bound did not change what is redacted (these pass on both patterns) ------------------------------
@pytest.mark.parametrize("addr", [
    "ruffa@example.com",
    "first.last@sub.example.co.uk",
    "odd!#$%&*+=?^_`{|}~'-name@example.org",
    "a@b.co",
])
def test_a_real_address_is_still_withheld(addr):
    assert withhold_personal_ids(f"from {addr} ok") == f"from {EMAIL_WITHHELD} ok"


@pytest.mark.parametrize("text", [
    "no address here",
    "a@b",                      # no dot in the domain: not an address
    "plain text with an @ sign alone",
])
def test_what_is_not_an_address_is_untouched(text):
    assert withhold_personal_ids(text) == text


def test_it_still_reaches_into_keys_and_nesting():
    got = withhold_personal_ids({"to@example.com": ["cc@example.com", {"x": "d@e.fg"}]})
    assert got == {EMAIL_WITHHELD: [EMAIL_WITHHELD, {"x": EMAIL_WITHHELD}]}


# --- an upper bound, not a benchmark --------------------------------------------------------------------------------
def test_a_long_non_matching_tail_finishes_quickly():
    """A generous ceiling: this is here to catch a pathological rewrite later, not to time the old pattern."""
    hostile = "x@" + ("a-" * 2000) + "!"
    start = time.monotonic()
    withhold_personal_ids(hostile)
    assert time.monotonic() - start < 2.0

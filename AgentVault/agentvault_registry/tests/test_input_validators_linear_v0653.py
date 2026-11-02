"""V0653 (am), item 3 (the hardening list in the sessions' room): the text filters run in linear time and strip what they
stripped before.

input_validators.sanitize_text and contains_dangerous_content (governance proposals, contracts, templates, funding
requests): "<[^>]*>" retried every '<' to the end of a text holding no '>', and "on\\w+\\s*=" every "on" inside a long word
(both quadratic). The tag strip is a scan with the regex's own matches; the linear regex "<[^<>]*>" was not used because it
would turn "<a <b>onclick=x>" into a live "<a onclick=x>". The event-handler pattern now reads a name that starts with
"on" (an attribute named xonload is no handler), so words like "bonus=" are no longer refused. BASE (a5ef48ddd, V0652): the
long inputs take seconds; the strip and the tag check match the old regex everywhere.
"""
from __future__ import annotations

import random
import re
import time

import pytest

from agentvault_registry import input_validators as iv

OLD_TAG = re.compile(r"<[^>]*>")


def _fuzz(n=4000, seed=653):
    rng = random.Random(seed)
    alphabet = "<>ab /=\"x\n"
    return [""] + ["".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 30))) for _ in range(n)]


def test_the_strip_matches_the_old_regex_on_every_input():
    for s in _fuzz():
        assert iv.sanitize_text(s) == OLD_TAG.sub("", iv._CONTROL_CHAR_RE.sub("", s)), repr(s)


def test_the_tag_check_matches_the_old_regex_on_every_input():
    for s in _fuzz():
        assert iv._has_tag(s) == bool(OLD_TAG.search(s)), repr(s)


def test_a_nested_open_bracket_is_stripped_whole_never_left_as_a_live_tag():
    assert iv.sanitize_text("<a <b>onclick=x>") == "onclick=x>"
    assert iv.sanitize_text("ok <script>alert(1)</script> done") == "ok alert(1) done"


@pytest.mark.parametrize("text", ["<script>", "x onerror=1", '"onload =1', "/onmouseover=", "ONCLICK=", "javascript:",
                                  "data: text/html", "<img src=x>"])
def test_the_dangerous_shapes_are_still_refused(text):
    assert iv.contains_dangerous_content(text)
    with pytest.raises(ValueError):
        iv.validate_safe_text(text)


@pytest.mark.parametrize("text", ["bonus=3", "content=final", "a > b, so b < a", "plain text"])
def test_words_that_only_contain_on_and_plain_text_pass(text):
    assert not iv.contains_dangerous_content(text)


@pytest.mark.parametrize("make", [lambda: "<" * 100_000, lambda: "on" * 25_000, lambda: "<a" * 50_000],
                         ids=["open-brackets", "on-run", "open-tags"])
def test_a_long_hostile_text_is_checked_and_stripped_in_bounded_time(make):
    s = make()
    t = time.perf_counter()
    iv.contains_dangerous_content(s)
    iv.sanitize_text(s)
    assert time.perf_counter() - t < 0.5

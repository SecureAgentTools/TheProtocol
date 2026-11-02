"""V0653 (am), item 3 (the hardening list in the sessions' room): the email studio's address check is bounded and keeps
its rule.

routers/admin_email_preview (a real send from the admin email studio): "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$" retried every split of
a long dotted domain (quadratic). The parts are bounded now (64 before the @, 253 after, RFC 5321) and the dot rule is a
test on the domain. The rule is unchanged within those bounds: one @, no space, a dot inside the domain with something on
both sides of it; a trailing newline, which "$" let through, is refused. BASE (a5ef48ddd, V0652): no _is_email, and the
long domain takes seconds.
"""
from __future__ import annotations

import random
import re
import time

import pytest

from agentvault_registry.routers import admin_email_preview as aep

OLD = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@pytest.mark.parametrize("addr", ["a@b.c", "first.last+tag@sub.example.org", "x@localhost.localdomain",
                                  "a" * 64 + "@" + "b" * 200 + ".de"])
def test_an_address_is_accepted(addr):
    assert aep._is_email(addr)


@pytest.mark.parametrize("addr", ["", None, "a@b", "a@.b", "a@b.", "a b@c.d", "a@b@c.d", "@b.c", "a@", "a@b.c\n",
                                  "a" * 65 + "@b.c", "a@" + "b" * 254 + ".c"])
def test_an_address_is_refused(addr):
    assert not aep._is_email(addr)


def test_the_rule_matches_the_old_pattern_within_the_bounds():
    rng = random.Random(653)
    for _ in range(5000):
        s = "".join(rng.choice("ab.@ ") for _ in range(rng.randrange(0, 18)))
        assert aep._is_email(s) == bool(OLD.match(s)), repr(s)


def test_a_long_dotted_domain_is_checked_in_bounded_time():
    s = "a@" + "." * 40_000 + "@"
    t = time.perf_counter()
    assert not aep._is_email(s)
    assert time.perf_counter() - t < 0.5

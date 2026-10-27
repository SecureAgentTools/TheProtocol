"""The heavy-run lock must be taken over ONLY when its holder is provably dead.

§EVTYPES 2026-09-05. `acquire_heavy_run_slot` releases its Redis lock in a
`finally`, which does not run when the process is killed. A container recreate
mid-suite therefore left `api_test:heavy_run` held by nobody for its full
ex=3600, and every subsequent api-test run was refused 409 naming a dead holder.
Measured: three launches refused by a holder whose process had died minutes
earlier; the key had 3245s still to live.

The fix stamps the holder with the container's PID-1 boot epoch and takes the
lock over only when that tag differs from ours. This pins BOTH directions,
because a takeover rule that is too eager reintroduces the concurrent-sweep bug
the lock exists to prevent -- and "cannot know" must stay conservative.
"""
import re

# The predicate as implemented in routers/admin_api_test.py::acquire_heavy_run_slot.
# Kept as a literal twin rather than imported: the router pulls in the whole app
# (DB, settings, Redis) at import, and this is a pure string/int decision.
def _would_take_over(holder: str, mine):
    their = None
    if "boot=" in holder:
        tail = holder.rsplit("boot=", 1)[1].strip()
        if tail.isdigit():
            their = int(tail)
    return mine is not None and their is not None and their != int(mine)


MINE = 1788639706


def test_dead_holder_from_another_boot_is_taken_over():
    assert _would_take_over(f"POST /x @ t boot={MINE - 5000}", MINE) is True


def test_live_holder_from_this_boot_still_refuses():
    # The lock's actual job. A takeover here would let two sweeps contend, which
    # the guard's own comment records as inflating per-tool latency 2-2.5x until
    # both exceed the ReadTimeout ceiling and fail.
    assert _would_take_over(f"POST /x @ t boot={MINE}", MINE) is False


def test_pre_fix_holder_without_a_tag_refuses():
    # Written by the old code: no tag means we cannot know, so we must not guess.
    assert _would_take_over("POST /x @ 2026-09-05T20:18:38", MINE) is False


def test_unparseable_tag_refuses():
    assert _would_take_over("POST /x @ t boot=notanumber", MINE) is False


def test_unreadable_own_boot_never_takes_over():
    # container_boot_epoch() returns None on any surprise; None must be
    # conservative, never "the holder is dead".
    assert _would_take_over(f"POST /x @ t boot={MINE - 5000}", None) is False


def test_router_still_carries_the_predicate():
    """Control: the twin above must not drift from the router silently."""
    src = open("src/agentvault_registry/routers/admin_api_test.py", encoding="utf-8").read()
    assert "boot_tag()" in src, "holder no longer stamped with a boot tag"
    assert re.search(r"_their\s*!=\s*int\(_mine\)", src), \
        "router no longer compares the holder's boot against ours"
    assert "_HEAVY_RUN_LOCK_KEY, holder, ex=3600" in src, "takeover no longer re-sets the lock"

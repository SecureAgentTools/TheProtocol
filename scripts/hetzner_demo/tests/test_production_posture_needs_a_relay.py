"""§FRAMELIC findings row 181 — a production frame must not come up mail-dead, and a mail-less
frame must not CLAIM a relay.

Two halves of one gap, both measured on EU/ASIA before the fix (row 173): they ran for a day
with `MAIL_SERVER=mailpit`, a host that does not resolve from the frame's own network, while
wearing production's limiter and production's flags. Nothing errored because nothing tried —
twelve routers send mail and none had been exercised. The registrant who finally gets no mail is
the alarm, which is far too late.

  1. `--posture production` with no FRAME_MAIL_* relay must REFUSE, naming the three env vars.
     (The sandbox branch is untouched: a deliberately mail-less sandbox is a real thing.)
  2. With no relay the driver must write an EMPTY MAIL_SERVER, never a plausible-looking host.
     "Configured" and "reachable" must not be the same word (§FXSTRAND's blank promise).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DRIVER = REPO / "scripts" / "hetzner_demo" / "standup_driver.py"
SRC = DRIVER.read_text()


def test_production_without_a_relay_refuses_and_names_the_env_vars():
    i = SRC.index('if getattr(args, "posture", "") == "production":')
    block = SRC[i:i + 1200]
    for var in ("FRAME_MAIL_SERVER", "FRAME_MAIL_ADDRESS", "FRAME_MAIL_TOKEN"):
        assert var in block, f"the refusal must name {var} — a refusal that does not say what to supply is a wall"
    assert "SystemExit" in block, "build_ctx returns a CONTEXT; `return <int>` would hand the caller an int as its ctx"


def test_the_sandbox_branch_still_allows_a_mail_less_frame():
    """The control. A gate that refuses BOTH postures is not a posture gate, it is an outage."""
    i = SRC.index("no FRAME_MAIL_* relay supplied")
    assert "require_email_verification = False" in SRC[i - 400:i + 200], \
        "a sandbox with no relay must still stand up, invite-gated with verification off"


def test_no_relay_means_an_EMPTY_mail_server_not_a_plausible_one():
    i = SRC.index('("MAIL_SERVER"')
    line = SRC[i:SRC.index("\n", i)]
    assert '"mailpit"' not in line and "example.com" not in line, \
        f"the default names an unreachable host: {line.strip()}"
    assert 'os.getenv("FRAME_MAIL_SERVER", "")' in line, "the real relay must be the first source"
    assert line.rstrip().endswith('""))') or '"")' in line, "the fallback must be EMPTY, not a hostname"


def test_the_envelope_sender_follows_the_supplied_credential():
    """protonmail (and every other relay) accepts only the address its credential owns, so
    MAIL_FROM must follow FRAME_MAIL_ADDRESS. The frame's own identity rides MAIL_FROM_NAME."""
    i = SRC.index('("MAIL_FROM"')
    line = SRC[i:SRC.index("\n", i)]
    assert 'FRAME_MAIL_ADDRESS' in line, f"MAIL_FROM must follow the supplied sender: {line.strip()}"
    # §ONESHOT F3: `.invalid` is unroutable AND refused by email-validator 2.3.0 (the registry never booted);
    # RFC 2606's `.example` is unroutable by construction and the validator accepts it.
    assert ".example" in line and ".invalid" not in line, "a mail-less frame's fallback sender must be unroutable by construction AND valid to the app's validator"


def test_mail_from_name_is_written_exactly_once():
    """findings row 176: a duplicate key in an env carrier is decided by precedence, not by the
    line you edited. I nearly added a second writer of this very key while fixing this file."""
    n = sum(1 for l in SRC.splitlines() if l.strip().startswith('("MAIL_FROM_NAME"'))
    assert n == 1, f"MAIL_FROM_NAME has {n} writers; the last one silently wins"

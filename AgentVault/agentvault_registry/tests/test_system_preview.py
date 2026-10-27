"""System-row previews (§CHATCOHERE follow-up, 2026-09-01).

`conversations.last_preview` is written at post time. Until now every system row
was stored as `[<first 24 chars of body>]`, so a thread list showed `[room.mode]`
beside a thread that renders "Ada set the room to announce-only" — and the
consent-review rows, which are already full sentences, were TRUNCATED mid-word
into `[Desk Owner d2a419 allo]`.

The population was measured live on frame-c before any of this was written:
room.* x474 · ping x84 · support.* x79 · retention.* x18 · free prose.
"""
import os
import re

import pytest

from agentvault_registry.services.chat_service import (
    PREVIEW_LEN, _ROOM_TEMPLATE, _system_sentence, preview_for,
)


# --- the five measured families -------------------------------------------

def test_ping_names_the_sender():
    assert _system_sentence("ping", None, "Ada") == "Ada pinged"


def test_ping_without_a_name_says_someone_not_blank():
    # An empty who would render " pinged". Absent is a state, not a name.
    assert _system_sentence("ping", None, None) == "Someone pinged"


@pytest.mark.parametrize("status,word", [
    ("open", "open"), ("in_progress", "being worked on"),
    ("resolved", "resolved"), ("closed", "closed"),
])
def test_support_status_reads_as_a_sentence(status, word):
    assert _system_sentence(f"support.{status}", None, "Support") == \
        f"Support marked this ticket {word}."


def test_support_unknown_status_passes_the_token_through_not_a_guess():
    assert _system_sentence("support.escalated", None, "Support") == \
        "Support marked this ticket escalated."


def test_retention_off_and_hours_and_days():
    assert _system_sentence("retention.off", None, "Ada") == \
        "Ada turned disappearing messages off — everything is kept."
    assert _system_sentence("retention.6h", None, "Ada") == \
        "Ada set messages here to disappear after 6h."
    assert _system_sentence("retention.24h", None, "Ada") == \
        "Ada set messages here to disappear after 1d."


def test_retention_garbage_does_not_invent_a_duration():
    # A malformed tail must not render "after 0h" — say the raw thing instead.
    assert _system_sentence("retention.banana", None, "Ada") == "retention.banana"


@pytest.mark.parametrize("action,card,expect", [
    ("room.kick", {"by_name": "Ada", "target_name": "Bob"},
     "Ada removed Bob from the room"),
    ("room.mute", {"by_name": "Ada", "target_name": "Bob"}, "Ada muted Bob"),
    ("room.unmute", {"by_name": "Ada", "target_name": "Bob"}, "Ada unmuted Bob"),
    ("room.mode", {"by_name": "Ada", "value": "announce"},
     "Ada set the room to announce-only"),
    ("room.mode", {"by_name": "Ada", "value": "open"}, "Ada opened the room"),
    ("room.topic", {"by_name": "Ada", "value": "Q3"}, "Ada set the topic: Q3"),
    ("room.topic", {"by_name": "Ada"}, "Ada cleared the topic"),
    ("room.motd", {"by_name": "Ada"}, "Ada updated the room genesis"),
])
def test_room_vocabulary_matches_the_thread_wording(action, card, expect):
    assert _system_sentence(action, card, "ignored") == expect


def test_room_falls_back_to_the_card_by_when_no_name_resolved():
    assert _system_sentence("room.motd", {}, None) == \
        "An operator updated the room genesis"


def test_free_prose_is_passed_through_not_bracketed():
    # The consent-review rows. This was the WORST case: bracketed AND cut to 24.
    prose = ("Desk Owner d2a419 allowed the support desk to review this "
             "conversation for ticket #186 — read-only, until the ticket closes.")
    out = _system_sentence(prose, None, "Desk Owner")
    assert not out.startswith("[")
    assert out.startswith("Desk Owner d2a419 allowed the support desk")


def test_preview_for_no_longer_brackets_system_rows():
    out = preview_for("system", "room.mode", {"by_name": "Ada", "value": "open"},
                      "Ada")
    assert out == "Ada opened the room"
    assert "[" not in out


def test_preview_is_clipped_to_the_column_budget():
    assert len(preview_for("system", "x" * 900, None, "Ada")) <= PREVIEW_LEN


# --- the drift gate -------------------------------------------------------

_FE_CANDIDATES = (
    "/w/fe/orgRoomActions.ts",  # mounted by the CI step
    os.path.join(os.path.dirname(__file__), "..", "src", "agentvault_registry",
                 "static", "new_registry_frontend", "src", "services", "chat",
                 "orgRoomActions.ts"),
)


def _fe_source():
    for c in _FE_CANDIDATES:
        if os.path.exists(c):
            return open(c, encoding="utf-8").read()
    return None


def test_server_room_vocabulary_covers_every_action_the_fe_renders():
    """The anti-drift gate, and the reason a second table is tolerable here.

    Two renderings of one fact are fine; two renderings that DISAGREE are not.
    This parses the FE brain's own `case '<action>'` labels and fails if the FE
    knows an action the server table cannot render — which is exactly how the
    server would silently start previewing "performed a room action" while the
    thread said something specific.

    ⚠ Skips LOUDLY rather than passing when the .ts is absent: the registry image
    ships the built dist, not the FE source, so an unmounted run must not read as
    a green gate.
    """
    src = _fe_source()
    if src is None:
        pytest.skip("FE source not present (image ships dist, not src) — "
                    "gate NOT run; mount orgRoomActions.ts to exercise it")

    body = src[src.index("export function systemRowText"):]
    body = body[:body.index("\n}")]
    actions = set(re.findall(r"case '([a-z_]+)'", body))
    assert actions, "parsed zero actions — the gate would pass vacuously"

    # `mode` and `topic` are the two that branch on `value`; the server keys
    # them with a suffix, so map them before comparing.
    variants = {"mode": {"mode:announce", "mode:open"},
                "topic": {"topic", "topic:clear"}}
    missing = set()
    for a in actions:
        need = variants.get(a, {a})
        if not need <= set(_ROOM_TEMPLATE):
            missing.add(a)
    assert not missing, (
        f"FE renders room actions the server preview cannot: {sorted(missing)}. "
        "Add them to _ROOM_TEMPLATE or the list will preview a vague sentence.")

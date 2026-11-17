"""V0663 (order gwo_c6b60425a411aff1293d2377, defect 1 of the browser pass, seq 3591): a quoted message left a raw `> ` in the thread
list's preview (`> Sandbox Beta Admin: first mess...`). The preview is a hint, never a render: quote markers never show in it, and a
message that quotes and then says something previews what it SAID."""
from __future__ import annotations

from agentvault_registry.services import chat_service as cs


def test_a_message_that_is_only_a_quote_previews_the_quoted_words_without_the_marker():
    assert cs.preview_for("text", "> Sandbox Beta Admin: first message\n\n", None) == "Sandbox Beta Admin: first message"


def test_a_message_that_quotes_and_replies_previews_the_reply():
    assert cs.preview_for("text", "> Sandbox Beta Admin: first message\n\nmy reply to it", None) == "my reply to it"


def test_nested_and_unspaced_markers_go_too():
    assert cs.preview_for("text", ">> deep quote\n>no space", None) == "deep quote\nno space"


def test_a_greater_than_inside_a_line_stays():
    assert cs.preview_for("text", "5 > 3 is true", None) == "5 > 3 is true"
    assert cs.preview_for("text", "a\n> b\nc", None) == "a\nc"            # the quoted line is dropped when something else was said


def test_other_kinds_and_plain_text_are_unchanged():
    assert cs.preview_for("text", "plain words", None) == "plain words"
    assert cs.preview_for("text", None, None) == ""
    assert len(cs.preview_for("text", "x" * 500, None)) == cs.PREVIEW_LEN


def test_a_long_quote_is_still_cut_to_the_preview_length():
    out = cs.preview_for("text", "> " + "y" * 500, None)
    assert out == "y" * cs.PREVIEW_LEN

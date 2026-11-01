"""V0652 (ae) (order gwo_5b9de9adb052d681ca95853d, agentvault2-14, 2026-10-31): a text file shows its first lines on its card.

The maintainer (the sessions' room, seq 265): "can you print like a preview from the context of the file on the card?
... otherwise i would always have to download it to see whats in it if its an md or txt file or json". The registry
writes the preview (services/chat_media.text_preview): at most 600 characters and 16 lines, cut at a line end, never
inside a character; JSON pretty-printed, Markdown, CSV and logs named so a client knows how to show them; a binary or a
file shaped like a credential gets none and says which. The upload's card carries it, and the post path writes it again
from the stored file (chat_media.ground_card), so a card never shows text its file does not hold; a relayed card from
another registry carries none. JSON, CSV and .log files are accepted as text (they were refused). Each case fails on
05441be31 (the V0651 recut), which has none of it.
"""
from __future__ import annotations

import json
import unicodedata
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import chat
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_media as cm
from agentvault_registry.services import chat_service as cs


def pv(text, mime="text/plain", name="notes.txt", complete=True):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return cm.text_preview(data, mime=mime, filename=name, complete=complete)


# ── the cut ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_short_file_is_shown_whole():
    assert pv("# Plan\n\nship it\n", "text/markdown", "plan.md") == {
        "preview": "# Plan\n\nship it", "preview_kind": "markdown", "preview_truncated": False}


def test_the_cut_falls_at_a_line_end_under_the_cap():
    lines = [f"line {i:02d} " + "x" * 40 for i in range(40)]           # 48 characters a line
    out = pv("\n".join(lines))
    shown = out["preview"].split("\n")
    assert out["preview_truncated"] is True and len(out["preview"]) <= cm.PREVIEW_CHARS
    assert shown == lines[:len(shown)]                                   # whole lines only, in order
    assert len(shown) == 12                                              # 12 lines and their breaks = 587 characters


def test_at_most_sixteen_lines():
    out = pv("\n".join(f"{i}" for i in range(100)))
    assert out["preview"].split("\n") == [str(i) for i in range(cm.PREVIEW_LINES)] and out["preview_truncated"]


def test_a_read_window_that_ends_inside_a_character_loses_only_that_character():
    text = "größe " * 2000                                               # ö and ß are two bytes each
    head = text.encode("utf-8")[:4099]                    # 4099 = 512 words and g, r, half an ö
    assert head[-1:] != b" " and head.decode("utf-8", "replace").endswith("�")   # it does end mid-character
    out = pv(head, complete=False)
    assert "�" not in out["preview"] and out["preview"].startswith("größe größe")
    assert out["preview_truncated"] is True


def test_one_long_line_is_cut_at_a_word_else_at_a_character_never_off_its_mark():
    words = pv(" ".join(["word"] * 400))["preview"]
    assert len(words) <= cm.PREVIEW_CHARS and words.endswith("word") and not words.endswith(" ")
    solid = pv("y" * 2000)["preview"]
    assert solid == "y" * cm.PREVIEW_CHARS
    marked = "x" + "é" * 600                                      # an e and its combining accent, 600 times
    out = pv(marked)["preview"]
    nxt = marked[len(out)]
    assert marked.startswith(out) and not unicodedata.combining(nxt)    # the cut never parts a letter from its mark


def test_leading_blank_lines_are_not_shown_and_a_blank_file_shows_nothing():
    assert pv("\n\n\nhello")["preview"] == "hello"
    assert pv("   \n\n  \n") is None


# ── each type ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_json_is_pretty_printed_when_the_whole_file_was_read():
    out = pv('{"order":"(ae)","steps":[1,2,3],"done":false}', "application/json", "state.json")
    assert out["preview_kind"] == "json"
    assert out["preview"] == json.dumps({"order": "(ae)", "steps": [1, 2, 3], "done": False}, indent=2)


def test_json_that_does_not_parse_or_was_not_read_whole_is_shown_as_it_is():
    assert pv('{"cut": tru', "application/json", "x.json")["preview"] == '{"cut": tru'
    head = ('{"a": "' + "v" * 20 + '", ') * 10
    assert pv(head, "application/json", "big.json", complete=False)["preview"].startswith('{"a": "vvvv')


@pytest.mark.parametrize("mime,name,kind", [
    ("text/markdown", "report.md", "markdown"),
    ("application/json", "state.json", "json"),
    ("text/csv", "fills.csv", "csv"),
    ("text/plain", "server.log", "log"),
    ("text/plain", "notes.txt", "text"),
    ("text/plain", "report.md.txt", "markdown"),        # chat_link's name for a .md sent to a registry before V0650
    ("text/plain", "state.json.txt", "json"),
])
def test_the_kind_says_how_to_show_it(mime, name, kind):
    assert pv("a,b\n1,2\n", mime, name)["preview_kind"] == kind


def test_an_image_or_a_pdf_has_no_preview():
    assert cm.text_preview(b"\x89PNG\r\n\x1a\n" + b"\x00" * 9, mime="image/png", filename="a.png", complete=True) is None
    assert cm.text_preview(b"%PDF-1.7", mime="application/pdf", filename="a.pdf", complete=True) is None


def test_a_logs_colour_codes_are_not_shown():
    out = pv("\x1b[32mINFO\x1b[0m started\r\n\x1b[31mERROR\x1b[0m stopped\r\n", name="run.log")
    assert out["preview"] == "INFO started\nERROR stopped" and out["preview_kind"] == "log"


# ── what gets no preview ─────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data", [
    b"text\x00with a nul",
    b"valid start \xff\xfe then bytes that are not UTF-8 " + b"x" * 40,
    bytes(range(1, 32)) * 40,
])
def test_a_binary_says_so(data):
    assert cm.text_preview(data, mime="text/plain", filename="x.txt", complete=True) == {"preview_withheld": "binary"}


# The shapes are assembled from pieces, so no credential shape sits in this file (the pre-commit hook refuses one).
_PEM = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END " + "PRIVATE KEY-----\n"
_JWT = "token " + "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiJ4eXoxMjMifQ" + ".c2lnbmF0dXJlMTIz\n"
_KEY = "key " + "avreg" + "_0123456789abcdefABCDEF\n"


@pytest.mark.parametrize("text", [
    _PEM,
    _JWT,
    _KEY,
    "DATABASE_URL=postgres://db\nAPI_KEY=abcdef1234567890\n",
    'deploy:\n  password: "hunter2-and-more"\n',
    '{"name": "svc", "client_secret": "s3cr3t-value"}',
])
def test_a_file_shaped_like_a_credential_shows_none(text):
    assert pv(text) == {"preview_withheld": "credential"}


def test_prose_that_names_a_password_is_still_prose():
    out = pv("Password: rotated on Friday, see the handover.\nToken lifetime is 3600 s.\n")
    assert out["preview"].startswith("Password: rotated on Friday")


# ── the upload ───────────────────────────────────────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, first=None, scalar_first=None):
        self._first, self._scalar_first = first, scalar_first

    def first(self):
        return self._first

    def scalars(self):
        return SimpleNamespace(first=lambda: self._scalar_first)


class _Session:
    def __init__(self):
        self.rows = {}

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        if "FROM conversation_participants" in sql:
            return _Result(scalar_first=None)
        if "count(*)" in sql and "chat_attachments" in sql:
            return _Result(first=(0, 0))
        if sql.startswith("SELECT id, filename, mime, bytes, sha256 FROM chat_attachments"):
            hit = next((r for r in self.rows.values() if r["s"] == p.get("s") and r["c"] == p.get("c")), None)
            return _Result(first=(hit["i"], hit["f"], hit["m"], hit["b"], hit["s"]) if hit else None)
        if sql.startswith("INSERT INTO chat_attachments"):
            self.rows[p["i"]] = p
            return _Result()
        raise AssertionError(f"unexpected statement: {sql[:90]}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "DATA_ROOT", tmp_path)

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind="dm", host_registry=None)

    async def _mine(db, cid, actor):
        return SimpleNamespace(state="active")

    async def _request(db, cid):
        return False
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "_my_row", _mine)
    monkeypatch.setattr(cs, "thread_is_request", _request)
    session = _Session()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chat.router)
    app.dependency_overrides[get_db] = lambda: session
    caller = lambda: {"kind": "developer", "developer": SimpleNamespace(id=5, name="Sender", email="s@example.test")}
    from agentvault_registry import security
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep is not None:
            app.dependency_overrides[dep] = caller
    return TestClient(app, raise_server_exceptions=False), session


def _up(c, name, data, mime):
    return c.post("/api/v1/chat/conversations/conv-1/attachments", files={"file": (name, data, mime)})


@pytest.mark.parametrize("name,mime,stored,kind", [
    ("state.json", "application/json", "application/json", "json"),
    ("fills.csv", "text/csv", "text/csv", "csv"),
    ("run.log", "text/x-log", "text/plain", "log"),
    ("report.md", "text/markdown", "text/markdown", "markdown"),
])
def test_text_files_upload_and_their_card_carries_the_preview(client, name, mime, stored, kind):
    c, session = client
    r = _up(c, name, b'{"a": 1}\n', mime)
    assert r.status_code == 201, r.text
    card = r.json()["card"]["data"]
    assert card["mime"] == stored and card["preview_kind"] == kind and card["preview"] and "preview_truncated" in card
    [row] = session.rows.values()
    assert row["m"] == stored


def test_the_same_file_twice_is_one_blob_and_both_cards_carry_the_preview(client):
    c, session = client
    first = _up(c, "a.md", b"# Same\n", "text/markdown").json()
    again = _up(c, "a.md", b"# Same\n", "text/markdown").json()
    assert again["deduplicated"] is True and len(session.rows) == 1
    assert first["card"]["data"]["preview"] == again["card"]["data"]["preview"] == "# Same"


def test_a_picture_card_carries_no_preview_fields(client):
    c, _ = client
    r = _up(c, "a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")
    assert r.status_code == 201 and not set(r.json()["card"]["data"]) & set(cm.PREVIEW_KEYS)


def test_the_upload_refusals_hold_for_the_new_types(client):
    c, _ = client
    r = _up(c, "x.json", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "application/json")
    assert r.status_code == 415 and "this file says application/json but its contents are image/png" in r.text
    assert _up(c, "x.bin", b"\x00\x01", "application/octet-stream").status_code == 415      # still not a text type


# ── the post path writes the preview from the stored file ───────────────────────────────────────────────────────

def _forged(att_id="att-1"):
    return {"v": 1, "type": "media", "data": {
        "attachment_id": att_id, "name": "plan.md", "mime": "text/markdown", "bytes": 9,
        "preview": "APPROVED: pay 5000", "preview_kind": "markdown", "preview_truncated": False}}


@pytest.fixture()
def stored(monkeypatch, tmp_path):
    rows = {}

    def put(att_id, content, conv="conv-1", mime="text/markdown", name="plan.md", deleted=None):
        path = tmp_path / f"{att_id}.bin"
        path.write_bytes(content)
        rows[att_id] = {"id": att_id, "conversation_id": conv, "filename": name, "mime": mime,
                        "bytes": len(content), "path": str(path), "deleted_at": deleted}

    async def _fetch(db, att_id):
        return rows.get(att_id)
    monkeypatch.setattr(cm, "fetch", _fetch)
    return put


def ground(card, conv="conv-1"):
    import asyncio
    return asyncio.run(cm.ground_card(None, conv, card))


def test_a_forged_preview_is_replaced_by_the_files_own_lines(stored):
    stored("att-1", b"# Plan\nship (ae)\n")
    out = ground(_forged())["data"]
    assert out["preview"] == "# Plan\nship (ae)" and out["preview_kind"] == "markdown"
    assert out["attachment_id"] == "att-1" and out["name"] == "plan.md"


@pytest.mark.parametrize("setup,att_id", [
    (lambda put: put("att-2", b"# other thread\n", conv="conv-9"), "att-2"),       # a file from another thread
    (lambda put: put("att-3", b"# gone\n", deleted="2026-10-31T22:00:00Z"), "att-3"),
    (lambda put: None, "att-404"),                                                  # no such file
    (lambda put: put("att-5", b"\x89PNG\r\n\x1a\n", mime="image/png", name="a.png"), "att-5"),
])
def test_a_card_whose_file_it_cannot_read_here_shows_none(stored, setup, att_id):
    setup(stored)
    out = ground(_forged(att_id))["data"]
    assert not set(out) & set(cm.PREVIEW_KEYS) and out["attachment_id"] == att_id


def test_a_stored_file_that_cannot_be_read_shows_none(stored, tmp_path):
    stored("att-6", b"# here\n")
    (tmp_path / "att-6.bin").unlink()
    assert "preview" not in ground(_forged("att-6"))["data"]


def test_grounding_leaves_the_senders_card_unchanged(stored):
    stored("att-1", b"# Plan\n")
    card = _forged()
    ground(card)
    assert card["data"]["preview"] == "APPROVED: pay 5000"


def test_the_router_grounds_a_media_card_before_any_send(monkeypatch):
    import asyncio
    seen = {}

    async def _gate(*a, **k):
        return True

    async def _ground(db, conv_id, card):
        seen["grounded"] = (conv_id, card["data"].get("preview"))
        return cm.without_preview(card)

    async def _sender(db, actor):
        return SimpleNamespace(display_name="Sender")

    async def _insert(db, conv, my_row, sender, kind, body, card, *a, **k):
        seen["inserted"] = card
        raise RuntimeError("stop")

    async def _relay(db, conv, my_row, actor, kind, body, card, client_ref):
        seen["relayed"] = card
        return {"relayed": True}
    monkeypatch.setattr(cs, "_rate_gate", _gate)
    monkeypatch.setattr(cm, "ground_card", _ground)
    monkeypatch.setattr(chat, "_named_sender", _sender)
    monkeypatch.setattr(cs, "insert_message", _insert)
    monkeypatch.setattr(chat, "_relay_resident_send", _relay)
    from agentvault_registry.services import chat_federation as fed
    monkeypatch.setattr(fed, "federation_enabled", lambda: False)
    actor = SimpleNamespace(key="dev:5")
    local = SimpleNamespace(id="conv-1", kind="dm", host_registry=None)
    with pytest.raises(RuntimeError):
        asyncio.run(chat._send_and_fan_out(None, local, None, actor, "card", None, _forged(), "ref-0001-preview"))
    assert seen["grounded"] == ("conv-1", "APPROVED: pay 5000") and "preview" not in seen["inserted"]["data"]
    mirror = SimpleNamespace(id="conv-2", kind="dm", host_registry="https://asia.example")
    asyncio.run(chat._send_and_fan_out(None, mirror, None, actor, "card", None, _forged(), "ref-0002-preview"))
    assert seen["grounded"][0] == "conv-2" and "preview" not in seen["relayed"]["data"]


def test_a_card_another_registry_relays_carries_no_preview(monkeypatch):
    import asyncio
    seen = {}

    def _validate(card, **k):
        seen["card"] = card
        raise RuntimeError("stop")
    monkeypatch.setattr(cs, "validate_card", _validate)
    with pytest.raises(RuntimeError):
        asyncio.run(cs.insert_remote_message(None, SimpleNamespace(id="c"), SimpleNamespace(state="active"),
                                             "remote:x", "Peer", "card", None, _forged(), "ref-0001-preview"))
    assert seen["card"]["type"] == "media" and not set(seen["card"]["data"]) & set(cm.PREVIEW_KEYS)


# ── the card's shape ─────────────────────────────────────────────────────────────────────────────────────────────

def _card(**extra):
    return {"v": 1, "type": "media", "data": {"attachment_id": "att-1", "name": "a.md", "mime": "text/markdown",
                                              "bytes": 9, **extra}}


def test_a_well_formed_preview_passes():
    # control: passes on both trees (a card was permissive on extras before; it still takes a well-formed one)
    assert cs.validate_card(_card(preview="# A", preview_kind="markdown", preview_truncated=False)) is None
    assert cs.validate_card(_card(preview_withheld="credential")) is None


@pytest.mark.parametrize("extra,words", [
    ({"preview": "x" * 601}, "at most 600 characters"),
    ({"preview": ["not", "text"]}, "at most 600 characters"),
    ({"preview_kind": "html"}, "preview_kind is one of"),
    ({"preview_withheld": "maybe"}, "preview_withheld is one of"),
    ({"preview_truncated": "yes"}, "true or false"),
])
def test_a_preview_out_of_shape_is_refused(extra, words):
    r = cs.validate_card(_card(**extra))
    assert r and words in r, r

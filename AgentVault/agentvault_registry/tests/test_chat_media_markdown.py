"""V0650 (i) (2026-10-31, agentvault2-14): markdown attachments in chat, held to plain text's rules.

Order gwo_1a140754ab54988c8d2f99db. The upload allowlist took PNG, JPEG, WebP, GIF, PDF and plain text; a session's
report as a .md file was refused ("'text/markdown' is not an accepted file type"). Markdown is now accepted with
text/plain's rules (no magic number; refused when its contents sniff as an image or a PDF) and nothing else changes:
the 5 MB limit, the quota, the 409 into a request, the named refusals, and the download, which serves every file as
octet-stream with attachment, nosniff and a sandbox policy, so a markdown file never renders on this origin.

Through FastAPI on the real routes; the database (the participant rows, the quota and dedup reads, the INSERT and the
fetch), the file root and the caller's token are replaced. Cases marked BASE fail on 6c1f036b (V0649).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import chat
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_media
from agentvault_registry.services import chat_service as cs

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MD = b"# Report\n\n- one\n- two\n"


class _Result:
    def __init__(self, first=None, scalar_first=None):
        self._first, self._scalar_first = first, scalar_first

    def first(self):
        return self._first

    def scalars(self):
        return SimpleNamespace(first=lambda: self._scalar_first)


class _Session:
    def __init__(self, other_pending: bool = False):
        self.other_pending, self.rows = other_pending, {}

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        if "FROM conversation_participants" in sql:
            return _Result(scalar_first=SimpleNamespace(state="pending") if self.other_pending else None)
        if "count(*)" in sql and "chat_attachments" in sql:
            return _Result(first=(0, 0))
        if sql.startswith("SELECT id, filename, mime, bytes, sha256 FROM chat_attachments"):
            return _Result(first=None)
        if sql.startswith("INSERT INTO chat_attachments"):
            self.rows[p["i"]] = p
            return _Result()
        if sql.startswith("SELECT id, conversation_id, filename, mime, bytes, storage_path, deleted_at"):
            r = self.rows.get(p["i"])
            return _Result(first=(r["i"], r["c"], r["f"], r["m"], r["b"], r["p"], None) if r else None)
        raise AssertionError(f"unexpected statement: {sql[:90]}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def room(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_media, "DATA_ROOT", tmp_path)

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind="dm", host_registry=None)

    async def _mine(db, cid, actor):
        return SimpleNamespace(state="active")
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "_my_row", _mine)

    def make(other_pending: bool = False):
        session = _Session(other_pending)
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: session
        caller = lambda: {"kind": "developer", "developer": SimpleNamespace(id=5, name="Sender", email="s@example.test")}
        # the chat read dependency, and (where V0650 (m) is merged) its key-aware successor on the GET routes
        from agentvault_registry import security
        for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
            if dep is not None:
                app.dependency_overrides[dep] = caller
        return TestClient(app, raise_server_exceptions=False), session
    make.root = tmp_path
    return make


def _up(client, name, data, mime):
    return client.post("/api/v1/chat/conversations/conv-1/attachments", files={"file": (name, data, mime)})


def test_a_markdown_report_is_accepted_and_stored_as_md(room):
    # BASE: 415 "'text/markdown' is not an accepted file type"
    client, session = room()
    r = _up(client, "notes.md", MD, "text/markdown")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mime"] == "text/markdown" and body["card"]["type"] == "media"
    assert body["card"]["data"]["mime"] == "text/markdown" and body["card"]["data"]["name"] == "notes.md"
    [row] = session.rows.values()
    assert row["m"] == "text/markdown" and row["p"].endswith(".md") and "/conv-1/" in row["p"]


def test_the_rfc_7763_charset_parameter_is_accepted(room):
    # BASE: 415
    client, _ = room()
    r = _up(client, "notes.md", MD, "text/markdown; charset=UTF-8")
    assert r.status_code == 201 and r.json()["mime"] == "text/markdown", r.text


def test_a_markdown_file_downloads_as_an_attachment_never_inline(room):
    # BASE: the upload is refused, so there is nothing to download
    client, _ = room()
    att = _up(client, "notes.md", MD, "text/markdown").json()["attachment_id"]
    r = client.get(f"/api/v1/chat/attachments/{att}")
    assert r.status_code == 200 and r.content == MD
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert r.headers["content-disposition"].startswith("attachment") and "notes.md" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert r.headers["cache-control"] == "private, no-store"


def test_markdown_has_the_same_size_limit(room):
    client, _ = room()
    at_limit = b"x" * chat_media.MAX_BYTES
    assert _up(client, "big.md", at_limit, "text/markdown").status_code == 201        # BASE: 415
    over = _up(client, "bigger.md", at_limit + b"x", "text/markdown")                 # control: the size check runs first
    assert over.status_code == 413 and "files are limited to 5 MB" in over.text


@pytest.mark.parametrize("name,data,mime,status,words", [
    ("a.svg", b"<svg/>", "image/svg+xml", 415, "SVG can carry script"),
    ("a.html", b"<p>x</p>", "text/html", 415, "HTML is a program here"),
    ("a.bin", b"\x00\x01", "application/octet-stream", 415, "is not an accepted file type"),
    ("a.txt", PNG, "text/plain", 415, "this file says text/plain but its contents are image/png"),
    ("empty.md", b"", "text/markdown", 422, "an empty file is not an attachment"),
])
def test_the_refusals_are_unchanged(room, name, data, mime, status, words):
    # controls: the same answers on both trees
    client, _ = room()
    r = _up(client, name, data, mime)
    assert r.status_code == status and words in r.text, (r.status_code, r.text)


def test_no_markdown_into_a_request(room):
    # control: the D6-554 rule holds for the new type too
    client, _ = room(other_pending=True)
    r = _up(client, "notes.md", MD, "text/markdown")
    assert r.status_code == 409 and "still a request" in r.text


def test_a_picture_labelled_markdown_is_refused_by_name(room):
    # BASE: refused, but with the unaccepted-type sentence
    client, _ = room()
    r = _up(client, "x.md", PNG, "text/markdown")
    assert r.status_code == 415 and "this file says text/markdown but its contents are image/png" in r.text, r.text

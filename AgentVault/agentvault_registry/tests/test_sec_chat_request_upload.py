"""D6-554 (2026-10-16): no file goes into a chat thread that is still a request, whoever uploads it.

POST /api/v1/chat/conversations/{id}/attachments refused an upload "into a request" by the UPLOADER's own participant
row. A stranger's first message lands the recipient's row 'pending' and leaves the stranger's own row 'active', so the
stranger, the one party the rule exists to stop, passed it and could store files in a thread the recipient had never
accepted (and post them as media cards). The route now asks the thread (chat_service.thread_is_request: any row still
pending), the rule the ping route already used. Each case marked BASE fails on 7140a4a6.

Through FastAPI on the real route; only the database (the conversation, the participant rows, the quota and dedup
reads, the attachment insert), the file root and the caller's token are replaced.
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


class _Result:
    def __init__(self, first=None, scalar_first=None):
        self._first, self._scalar_first = first, scalar_first

    def first(self):
        return self._first

    def scalars(self):
        return SimpleNamespace(first=lambda: self._scalar_first)


class _Session:
    def __init__(self, other_pending: bool):
        self.other_pending, self.stored = other_pending, 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM conversation_participants" in sql:     # thread_is_request: is any row still pending?
            return _Result(scalar_first=SimpleNamespace(state="pending") if self.other_pending else None)
        if "count(*)" in sql and "chat_attachments" in sql:
            return _Result(first=(0, 0))
        if sql.startswith("SELECT id, filename, mime, bytes, sha256 FROM chat_attachments"):
            return _Result(first=None)
        if sql.startswith("INSERT INTO chat_attachments"):
            self.stored += 1
            return _Result()
        raise AssertionError(f"unexpected statement: {sql[:90]}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def upload(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_media, "DATA_ROOT", tmp_path)

    def call(my_state: str, other_pending: bool):
        async def _conv(db, cid):
            return SimpleNamespace(id=cid, kind="dm", host_registry=None)

        async def _mine(db, cid, actor):
            return SimpleNamespace(state=my_state)
        monkeypatch.setattr(cs, "_get_conversation", _conv)
        monkeypatch.setattr(cs, "_my_row", _mine)
        session = _Session(other_pending)
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_actor_for_read] = lambda: {
            "kind": "developer", "developer": SimpleNamespace(id=5, name="Sender", email="s@example.test")}
        r = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/chat/conversations/conv-1/attachments", files={"file": ("a.png", PNG, "image/png")})
        return r, session
    return call


def test_an_accepted_thread_takes_a_file(upload):
    r, s = upload("active", other_pending=False)          # control
    assert r.status_code == 201 and s.stored == 1, r.text
    assert r.json()["card"]["type"] == "media"


def test_the_stranger_cannot_push_a_file_into_a_request(upload):
    r, s = upload("active", other_pending=True)           # BASE: 201, the file stored
    assert r.status_code == 409 and "still a request" in r.text and s.stored == 0, (r.status_code, r.text)


def test_the_recipient_of_a_request_cannot_either(upload):
    r, s = upload("pending", other_pending=True)          # control: refused on both trees
    assert r.status_code == 409 and s.stored == 0, r.text

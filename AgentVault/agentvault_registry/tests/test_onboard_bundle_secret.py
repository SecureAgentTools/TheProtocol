"""§MCPTEST30 (V0640): the onboarding bundle carries only the agent's own secret.

POST /api/v1/onboard/download-bundle checked the agent's owner and its client_id, then wrote whatever client_secret the
request carried into the bundle's .env.secret, so a mistyped secret built a bundle whose agent could never sign in,
with no error anywhere until it ran (agentvault2-66, 2026-10-24; agentvault2-d6's yes for V0640). Pinned: a secret
that does not match the agent's stored hash is refused 400 "client_secret does not match the agent record" and no zip
is written; the agent's own secret builds the bundle, its .env.secret carrying exactly that secret.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import agent_bundle as B
from agentvault_registry.security import hash_password

DID = "did:theprotocol:11111111-2222-4333-8444-555555555555"
SECRET = "tp_secret_" + "ab12" * 16
_REAL_ZIP = zipfile.ZipFile


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _Db:
    """The route's two reads, in order: the agent, then its card."""

    def __init__(self, agent, card):
        self._answers = [agent, card]

    async def execute(self, _stmt):
        return _Result(self._answers.pop(0) if self._answers else None)


def _call(monkeypatch, tmp_path, secret, made):
    (tmp_path / ".env").write_text("AGENT_NAME=My Agent\nAGENT_DID=PLACEHOLDER_DID\n")
    (tmp_path / "README.md").write_text("# My Agent\n")
    (tmp_path / "docker-compose.yml").write_text("services:\n  my-agent:\n    image: example\n")
    monkeypatch.setattr(B, "MINIMAL_TEMPLATE_DIR", tmp_path)

    def spy(*a, **k):
        made.append(a)
        return _REAL_ZIP(*a, **k)

    monkeypatch.setattr(B.zipfile, "ZipFile", spy)
    agent = SimpleNamespace(did=DID, creator_developer_id=7, client_id="agent-own-client",
                            hashed_client_secret=hash_password(SECRET))
    card = SimpleNamespace(name="Bundle Agent", card_data={"name": "Bundle Agent", "did": DID})
    req = B.BundleRequest(agent_did=DID, client_id="agent-own-client", client_secret=secret, template_type="minimal")
    return asyncio.run(B.download_bundle(req, current_developer=SimpleNamespace(id=7), db=_Db(agent, card)))


async def _body(resp) -> bytes:
    return b"".join([c if isinstance(c, bytes) else c.encode() async for c in resp.body_iterator])


def test_a_secret_that_is_not_the_agents_is_refused_and_no_zip_is_written(monkeypatch, tmp_path):
    made = []
    with pytest.raises(HTTPException) as e:
        _call(monkeypatch, tmp_path, "tp_secret_" + "wrong" * 8, made)
    assert e.value.status_code == 400 and e.value.detail == "client_secret does not match the agent record"
    assert made == []


def test_the_agents_own_secret_builds_the_bundle_with_exactly_that_secret(monkeypatch, tmp_path):
    made = []
    resp = _call(monkeypatch, tmp_path, SECRET, made)
    assert len(made) == 1 and resp.media_type == "application/zip"
    secret_file = _REAL_ZIP(io.BytesIO(asyncio.run(_body(resp)))).read(".env.secret").decode()
    assert f"CLIENT_SECRET={SECRET}\n" in secret_file and f"AGENT_DID={DID}\n" in secret_file

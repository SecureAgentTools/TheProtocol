"""§FIRSTHOUR (2026-09-03) — GET /auth/verify-email keeps the consumed token.

Mail clients prefetch links and people tap twice. Before this, a successful verification
NULLed `email_verification_token`, so the second visit to the very same link could not find
the developer and answered `status=failed&reason=not_found` ("invalid or already used") —
a failure screen for an account that had just been verified. Now the row keeps the token
(only its expiry is cleared) and the second visit answers `status=success&already=true`.
Pure: the crud lookup and the TEG initialiser are patched, the session is a stub.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import auth_secure


class _Session:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _developer(token: str, *, verified: bool = False, expires_in_hours: float = 24.0):
    return SimpleNamespace(
        id=4242,
        email="ada.probe@example.org",
        is_verified=verified,
        email_verification_token=token,
        verification_token_expires=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
    )


def _patch_lookup(monkeypatch, developer, *, console="https://frame-c.theprotocol.cloud"):
    # pin the console so the asserted targets do not depend on the test box's env
    from agentvault_registry.core import public_url as pu
    monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
    monkeypatch.setattr(pu, "public_base_url_static", lambda: console)
    async def _lookup(db, token):
        return developer if developer is not None and developer.email_verification_token == token else None

    monkeypatch.setattr(auth_secure.developer_crud, "get_developer_by_verification_token", _lookup)

    async def _teg(email, dev_id):
        return True

    monkeypatch.setattr(auth_secure, "initialize_teg_account", _teg)


@pytest.mark.asyncio
async def test_first_click_verifies_and_keeps_the_token(monkeypatch):
    dev = _developer("tok-first-click")
    _patch_lookup(monkeypatch, dev)
    db = _Session()

    resp = await auth_secure.verify_email(token="tok-first-click", db=db)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/#/email-verification?status=success"
    assert dev.is_verified is True
    assert dev.email_verification_token == "tok-first-click", "the consumed token must stay on the row"
    assert dev.verification_token_expires is None
    assert db.commits == 1 and db.rollbacks == 0


@pytest.mark.asyncio
async def test_second_click_on_the_same_link_answers_already_verified(monkeypatch):
    dev = _developer("tok-twice")
    _patch_lookup(monkeypatch, dev)
    db = _Session()

    first = await auth_secure.verify_email(token="tok-twice", db=db)
    second = await auth_secure.verify_email(token="tok-twice", db=db)

    assert first.headers["location"] == "/#/email-verification?status=success"
    assert second.status_code == 303
    assert second.headers["location"] == "/#/email-verification?status=success&already=true"
    assert db.commits == 1, "the second visit must not write"


@pytest.mark.asyncio
async def test_unknown_token_is_still_not_found(monkeypatch):
    _patch_lookup(monkeypatch, None)
    resp = await auth_secure.verify_email(token="tok-nobody", db=_Session())
    assert resp.headers["location"] == "/#/email-verification?status=failed&reason=not_found"


@pytest.mark.asyncio
async def test_expired_token_is_still_refused_and_left_untouched(monkeypatch):
    dev = _developer("tok-old", expires_in_hours=-1)
    _patch_lookup(monkeypatch, dev)
    db = _Session()
    resp = await auth_secure.verify_email(token="tok-old", db=db)
    assert resp.headers["location"] == "/#/email-verification?status=failed&reason=expired"
    assert dev.is_verified is False and db.commits == 0


@pytest.mark.asyncio
async def test_apex_console_receives_the_landing_when_named(monkeypatch):
    """registry-a: PUBLIC_UI_URL=https://theprotocol.cloud — the person lands on the apex, not api./ui."""
    dev = _developer("tok-apex")
    _patch_lookup(monkeypatch, dev, console="https://api.theprotocol.cloud")
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    resp = await auth_secure.verify_email(token="tok-apex", db=_Session())
    assert resp.headers["location"] == "https://theprotocol.cloud/#/email-verification?status=success"


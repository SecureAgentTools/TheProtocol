"""D6-821 (V0640): an inline admin check asks what require_admin_flag asks, sub-flags and widened reads included.

The D6-057 census found inline checks that read the account's admin flags alone, so what an admin is shown widened on a
credential that does not carry admin authority: an admin's scoped API key (a paired phone's, an MCP OAuth key), an
account without the second factor REQUIRE_ADMIN_2FA demands, or one that must change its password. Unlisted cards in the
card list and in discovery, a guild order's deliverable, the admin notification kinds and their preferences, every
dispute, the docker telemetry socket, the socket's admin audiences and the admin cosmetic flares. security.
admin_flag_credential() is the inline twin of require_admin_flag for the sub-flags (is_admin or the flag, on this
credential, with the second factor, never while a password change is forced); admin_credential() gains the password
change it lacked. Each test marked BASE fails on 5ebd9b76 (fix/d6-backlog-v0639); its control holds on both.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry import security
from agentvault_registry.config import settings
from agentvault_registry.services.notification_catalog import CATALOG

disputes = importlib.import_module("agentvault_registry.routers.disputes")
websocket = importlib.import_module("agentvault_registry.routers.websocket")
fiat = importlib.import_module("agentvault_registry.routers.fiat_onramp")
guild = importlib.import_module("agentvault_registry.routers.guild")
notifications = importlib.import_module("agentvault_registry.routers.notifications")

SCOPED = ["mcp:tools"]          # a paired phone's or an MCP OAuth key's scopes: no mcp:admin
FULL = ["*"]
ADMIN_KINDS = {t.key for t in CATALOG if t.audience == "admin"}


def _dev(**kw):
    base = dict(id=7, email="a@example.test", name="A", is_admin=False, admin_treasury=False, admin_support=False,
                admin_enforcement=False, admin_federation=False, admin_platform=False, must_change_password=False,
                two_fa_enabled=True, is_federation_operator=False, notification_prefs={}, organization_memberships=[])
    base.update(kw)
    return SimpleNamespace(**base)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def cred(monkeypatch):
    """The credential of one call: the presented key's scopes (None = a JWT) and REQUIRE_ADMIN_2FA."""
    tokens = []

    def _set(scopes=None, two_fa_required=False):
        tokens.append(security._PRESENTED_KEY_SCOPES.set(scopes))
        monkeypatch.setattr(settings, "REQUIRE_ADMIN_2FA", two_fa_required)
    yield _set
    for t in reversed(tokens):
        security._PRESENTED_KEY_SCOPES.reset(t)


# ── the twin ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_twin_holds_is_admin_as_every_flag_and_a_flag_as_itself(cred):
    cred(None)
    sup = _dev(admin_support=True)
    assert security.admin_flag_credential(sup, "admin_support") and security.admin_flag_credential(sup)
    assert not security.admin_flag_credential(sup, "admin_treasury")
    adm = _dev(is_admin=True)
    assert all(security.admin_flag_credential(adm, f) for f in security.ADMIN_FLAGS)
    assert not security.admin_flag_credential(_dev()) and not security.admin_flag_credential(None)


def test_the_twin_asks_the_credential_the_second_factor_and_the_password_change(cred):
    adm = _dev(admin_platform=True)
    cred(SCOPED)
    assert not security.admin_flag_credential(adm, "admin_platform")
    cred(FULL)
    assert security.admin_flag_credential(adm, "admin_platform")
    cred(None, two_fa_required=True)
    assert not security.admin_flag_credential(_dev(admin_platform=True, two_fa_enabled=False), "admin_platform")
    assert security.admin_flag_credential(adm, "admin_platform")
    cred(None)
    assert not security.admin_flag_credential(_dev(admin_platform=True, must_change_password=True), "admin_platform")


def test_an_unknown_flag_is_a_programming_error():
    with pytest.raises(ValueError):
        security.admin_flag_credential(_dev(is_admin=True), "admin_everything")


def test_admin_credential_refuses_while_a_password_change_is_forced(cred):   # BASE
    cred(None)
    assert security.admin_credential(_dev(is_admin=True))
    assert not security.admin_credential(_dev(is_admin=True, must_change_password=True))


# ── the sites ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_dispute_needs_the_second_factor(cred):   # BASE
    cred(None, two_fa_required=True)
    assert not disputes.reads_every_dispute(_dev(admin_enforcement=True, two_fa_enabled=False))
    assert disputes.reads_every_dispute(_dev(admin_enforcement=True))
    cred(SCOPED)
    assert not disputes.reads_every_dispute(_dev(is_admin=True))


def test_the_docker_telemetry_socket_asks_what_its_http_twin_asks(cred):   # BASE
    cred(None, two_fa_required=True)
    assert not websocket.may_watch_docker_stats(_dev(admin_platform=True, two_fa_enabled=False))
    assert websocket.may_watch_docker_stats(_dev(admin_platform=True))
    cred(SCOPED)
    assert not websocket.may_watch_docker_stats(_dev(is_admin=True))
    cred(None)
    assert not websocket.may_watch_docker_stats(_dev(is_admin=True, must_change_password=True))


def test_the_socket_writes_no_admin_flags_while_a_password_change_is_forced(cred):   # BASE
    cred(None)
    forced = websocket._build_user_data(_dev(is_admin=True, admin_support=True, must_change_password=True))
    assert forced["role"] == "developer" and not forced["is_admin"] and not forced["admin_support"]
    live = websocket._build_user_data(_dev(is_admin=True, admin_support=True))
    assert live["role"] == "admin" and live["is_admin"] and live["admin_support"]


def test_admin_flares_need_an_admin_on_this_credential(cred):   # BASE
    cred(None)
    assert fiat._is_admin_developer(_dev(admin_treasury=True))
    assert not fiat._is_admin_developer(_dev(admin_treasury=True, must_change_password=True))


class _NoRows:
    async def execute(self, *a, **k):
        return SimpleNamespace(first=lambda: None)


def test_a_deliverable_is_an_admins_only_on_an_admin_credential(cred):   # BASE
    order = {"poster_did": "did:theprotocol:someone-else", "worker_did": None, "poster_org_id": None}
    cred(SCOPED)
    assert _run(guild._may_see_deliverable(_NoRows(), order, _dev(is_admin=True))) is False
    cred(None)
    assert _run(guild._may_see_deliverable(_NoRows(), order, _dev(is_admin=True))) is True


def test_the_admin_notification_kinds_follow_the_credential(cred):   # BASE
    assert ADMIN_KINDS, "the catalog names no admin-audience kind: this test would measure nothing"
    cred(SCOPED)
    seen = {t["key"] for t in _run(notifications.get_catalog(current_dev=_dev(is_admin=True)))["types"]}
    assert not (seen & ADMIN_KINDS)
    cred(None)
    seen = {t["key"] for t in _run(notifications.get_catalog(current_dev=_dev(is_admin=True)))["types"]}
    assert ADMIN_KINDS <= seen


class _PastTheCheck(Exception):
    pass


class _StopAtWrite:
    async def execute(self, *a, **k):
        raise _PastTheCheck()


def test_an_admin_kinds_preference_is_written_only_on_an_admin_credential(cred):   # BASE
    kind = sorted(k for k in ADMIN_KINDS
                  if not next(t for t in CATALOG if t.key == k).mandatory
                  and not next(t for t in CATALOG if t.key == k).legacy_managed)[0]
    body = notifications.PrefsPutIn(rows=[{"type_key": kind, "channel": "inapp", "enabled": False}])
    cred(SCOPED)
    with pytest.raises(HTTPException) as ei:
        _run(notifications.put_prefs(payload=body, current_dev=_dev(is_admin=True), db=_StopAtWrite()))
    assert ei.value.status_code == 403
    cred(None)
    with pytest.raises(_PastTheCheck):
        _run(notifications.put_prefs(payload=body, current_dev=_dev(is_admin=True), db=_StopAtWrite()))


def test_the_card_list_and_discovery_widen_only_on_an_admin_credential():
    """The two card reads are large; what they ask is read from their source: each calls admin_credential and reads
    no bare is_admin (the D6-057 census guards the second half for every router)."""
    src = pathlib.Path(importlib.import_module("agentvault_registry.routers.agent_cards").__file__).read_text()
    tree = ast.parse(src)
    for name in ("list_agent_cards", "discover_agent_cards"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        calls = {getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)}
        assert "admin_credential" in calls, f"{name} does not ask admin_credential"

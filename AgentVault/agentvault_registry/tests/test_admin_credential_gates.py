"""D6-057 (V0639): an admin route asks admin_credential(), never the account's bare is_admin.

§POCKETPAIR made every inline admin check ask security.admin_credential(): is_admin on the account AND a credential that
reaches admin on THIS request (a paired phone's key or an MCP OAuth key carries scopes without mcp:admin) AND, under
REQUIRE_ADMIN_2FA, the account's second factor. Five routes kept a bare `if not getattr(dev, "is_admin", False)`, so an
admin's scoped key passed them: the contract dispute split (moves the escrowed remainder), the staking rewards' manual
distribution and the TEG lock reconcile, the admin attestation revoke, and the emission-policy write (that one sits behind
require_admin_flag already; its inline check now asks the same question).

The credential is set the way the API-key path sets it (security._PRESENTED_KEY_SCOPES), so the real admin_credential
runs; each route is stopped just past its gate (a stand-in that raises 418, or the route's own next refusal).
RED on V0638's routers: the census, the five scoped-key refusals and the three the census found (the guild's
dispute resolve, the batch transfers from any agent, the bridge). The controls hold on both.
"""
from __future__ import annotations

import ast
import asyncio
import decimal
import importlib
import pathlib
import types

import pytest
from fastapi import HTTPException

security = importlib.import_module("agentvault_registry.security")
ctr = importlib.import_module("agentvault_registry.routers.contracts_v2")
srew = importlib.import_module("agentvault_registry.routers.staking_rewards")
att = importlib.import_module("agentvault_registry.routers.attestations")
health = importlib.import_module("agentvault_registry.routers.admin_health")

ROUTERS = pathlib.Path(ctr.__file__).parent
SCOPED = ["mcp:tools"]           # a paired phone's or an MCP OAuth key's scopes: no mcp:admin
FULL = ["*"]                     # a key with the account's whole authority (every key minted before §POCKETPAIR)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _admin():
    return types.SimpleNamespace(id=1, is_admin=True, email="admin@test.invalid")


def _stop(*a, **k):
    raise HTTPException(418, detail="past the admin gate")


@pytest.fixture
def scopes(monkeypatch):
    """Set the presented key's scopes for one call, as the API-key path does (None = a JWT)."""
    tokens = []

    def _set(value):
        tokens.append(security._PRESENTED_KEY_SCOPES.set(value))
    monkeypatch.setattr(ctr, "_require_enabled", lambda: None)
    monkeypatch.setattr(ctr, "_must_load", _stop)
    monkeypatch.setattr(srew, "get_staking_rewards_service", _stop)
    monkeypatch.setattr(att, "ZKP_PHASE_2_ENABLED", False)
    yield _set
    for t in reversed(tokens):
        security._PRESENTED_KEY_SCOPES.reset(t)


ROUTES = {
    "the contract dispute split": lambda: ctr.admin_resolve_contract("ctr_x", ctr.ResolveIn(provider_pct=50), dev=_admin(),
                                                                     db=None),
    "the staking rewards' manual distribution": lambda: srew.trigger_distribution(db=None, current_developer=_admin()),
    "the TEG lock reconcile": lambda: srew.reconcile_teg_locks(db=None, current_developer=_admin(),
                                                             payload={"tolerance": "not-a-number"}),
    "the admin attestation revoke": lambda: att.admin_revoke_attestation_endpoint(
        "att-1", types.SimpleNamespace(reason="test"), db=None, current_developer=_admin()),
    "the emission-policy write": lambda: health.update_event_emission_policy(
        "TokensTransferred", {"skip_in_projection": True}, current_developer=_admin(), db=None),
}


def _outcome(make):
    """403 at the gate, or what the route did past it (418/503/422, or the reconcile's unreadable tolerance)."""
    try:
        _run(make())
    except HTTPException as e:
        return e.status_code
    except decimal.InvalidOperation:
        return "past the gate"
    return "past the gate"


@pytest.mark.parametrize("name", sorted(ROUTES))
def test_an_admins_scoped_key_is_refused_at_the_gate(scopes, name):
    scopes(SCOPED)
    assert _outcome(ROUTES[name]) == 403, f"{name}: a scoped key passed the admin gate"


@pytest.mark.parametrize("name", sorted(ROUTES))
def test_control_an_admins_full_credential_passes_the_gate(scopes, name):
    scopes(FULL)
    assert _outcome(ROUTES[name]) != 403
    scopes(None)                                   # a JWT
    assert _outcome(ROUTES[name]) != 403


def test_control_a_developer_who_is_no_admin_is_refused(scopes):
    scopes(None)
    with pytest.raises(HTTPException) as e:
        _run(ctr.admin_resolve_contract("ctr_x", ctr.ResolveIn(provider_pct=50),
                                        dev=types.SimpleNamespace(id=2, is_admin=False), db=None))
    assert e.value.status_code == 403


# Every read of the account's is_admin in routers/, reviewed (D6-057, 2026-10-24): a read that is not in this list fails the
# census below until someone decides whether it grants admin power (then it asks admin_credential, or require_admin_flag)
# or only reports, filters or widens a view (then it joins the list with its reason). Removing a read also updates it.
# D6-821 (V0640) moved the reads that widened a view on the account's flag alone to admin_credential and
# admin_flag_credential (tests/test_admin_subflag_credential.py), so they left the list.
REVIEWED = {
    ("admin_api_test.py", "_listed"): "filters the tester's developer list (a dict), grants nothing",
    ("admin_developers.py", "_to_admin_read"): "serializes the account's flag for an admin view",
    ("admin_developers.py", "delete_developer"): "protects the TARGET (an admin account is not deleted here)",
    ("admin_developers.py", "list_developers"): "a SQL filter on the column",
    ("admin_invite_codes.py", "generate_codes"): "inside a credential-gated admin route: may the caller grant any flag",
    ("agent_locations.py", "get_operator_location"): "a SQL filter on the column",
    ("assistant.py", "assistant_status"): "says whether the bridge is available to the caller, grants nothing",
    ("auth.py", "get_profile"): "reports the account's role",
    ("auth_2fa.py", "recover_with_backup_code"): "reports the account's flag in the login answer",
    ("auth_2fa.py", "validate_two_factor"): "reports the account's flag in the login answer",
    ("auth_secure.py", "get_profile"): "reports the account's role",
    ("auth_secure.py", "login_for_access_token"): "reports the account's role at login",
    ("developers.py", "export_my_account"): "the account's own export",
    ("federation_sync.py", "_get_display_name"): "a SQL filter on the column",
    ("federation_sync.py", "_get_operator_location"): "a SQL filter on the column",
    ("fiat_onramp.py", "_handle_routed_settle"): "a SQL filter on the column",
    ("frame_invitations.py", "_may_name_internal_bundle"): "asks api_key_grants_admin and the second factor",
    ("teg_transactions.py", "reads_every_ledger"): "asks api_key_grants_admin and the second factor",
    ("websocket.py", "<module>"): "the socket's audience predicates over the user dict _build_user_data writes",
    ("websocket.py", "_build_user_data"): "writes the flags only while the credential conveys admin (D6-821)",
    ("websocket.py", "topic_allowed"): "over the user dict _build_user_data writes",
}


def _is_admin_reads():
    """{(file, function): [lines]} of every read of is_admin in routers/: an attribute load, getattr(x, "is_admin", ...)
    or x.get("is_admin")."""
    sites = {}
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def walk(node, func):
            for ch in ast.iter_child_nodes(node):
                f = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
                hit = isinstance(ch, ast.Attribute) and ch.attr == "is_admin" and isinstance(ch.ctx, ast.Load)
                if isinstance(ch, ast.Call) and ch.args:
                    fn = ch.func
                    if getattr(fn, "id", None) == "getattr" and len(ch.args) >= 2 \
                            and isinstance(ch.args[1], ast.Constant) and ch.args[1].value == "is_admin":
                        hit = True
                    if isinstance(fn, ast.Attribute) and fn.attr == "get" and isinstance(ch.args[0], ast.Constant) \
                            and ch.args[0].value == "is_admin":
                        hit = True
                if hit:
                    sites.setdefault((path.name, f or "<module>"), []).append(ch.lineno)
                walk(ch, f)
        walk(tree, None)
    return sites


def test_every_read_of_is_admin_in_the_routers_is_reviewed():
    """A bare flag hid in shapes a narrow pattern missed (`if not bool(getattr(...))`, `and not getattr(...)`): the
    census reads every is_admin read, whatever the expression around it."""
    found = _is_admin_reads()
    new = {k: v for k, v in found.items() if k not in REVIEWED}
    gone = sorted(k for k in REVIEWED if k not in found)
    assert not new, f"is_admin read where nobody decided whether it grants admin power (ask admin_credential): {new}"
    assert not gone, f"reviewed reads that no longer exist (drop them from REVIEWED): {gone}"


def test_the_sites_that_grant_admin_power_read_no_bare_flag():
    found = _is_admin_reads()
    for site in (("contracts_v2.py", "admin_resolve_contract"), ("attestations.py", "admin_revoke_attestation_endpoint"),
                 ("admin_health.py", "update_event_emission_policy"), ("staking_rewards.py", "trigger_distribution"),
                 ("staking_rewards.py", "reconcile_teg_locks"), ("guild.py", "_require_admin"),
                 ("teg_transactions.py", "_run_batch_transfers"), ("assistant.py", "assistant_ask")):
        assert site not in found, f"{site} reads the bare flag"


# ── the three found by the census: the guild's dispute resolve, the batch transfers, the bridge ────────────────────

guild = importlib.import_module("agentvault_registry.routers.guild")
txs = importlib.import_module("agentvault_registry.routers.teg_transactions")
assistant = importlib.import_module("agentvault_registry.routers.assistant")
integ = importlib.import_module("agentvault_registry.routers.teg_integration")


def test_the_guild_admin_gate_refuses_a_scoped_key_and_passes_a_full_one(scopes):
    scopes(SCOPED)
    with pytest.raises(HTTPException) as e:
        guild._require_admin(_admin())
    assert e.value.status_code == 403
    scopes(FULL)
    guild._require_admin(_admin())          # no refusal


class _BatchDB:
    async def execute(self, stmt):
        return types.SimpleNamespace(scalar_one_or_none=lambda: types.SimpleNamespace(
            did="did:theprotocol:someone-else", creator_developer_id=99))


@pytest.fixture
def transfers(monkeypatch):
    moved = []

    async def _transfer(*, transfer_request, request, current_agent, db, idempotency_key=None):
        moved.append(current_agent.did)
        return {"transaction_id": "tx-1", "fee_amount": "0"}
    monkeypatch.setattr(integ, "transfer_teg_tokens", _transfer)
    return moved


def test_a_scoped_key_batch_transfers_from_no_agent_it_does_not_own(scopes, transfers):
    item = [{"from": "did:theprotocol:someone-else", "to": "did:theprotocol:4a3c2b1d-1111-4222-8333-944455556666", "amount": "1"}]
    scopes(SCOPED)
    out = _run(txs._run_batch_transfers(item, _admin(), None, _BatchDB()))
    assert transfers == [] and "not owned" in str(out)
    scopes(FULL)
    _run(txs._run_batch_transfers(item, _admin(), None, _BatchDB()))
    assert transfers == ["did:theprotocol:someone-else"]          # the control: a full admin credential still may


def test_the_bridge_refuses_a_scoped_key(scopes, monkeypatch):
    monkeypatch.setattr(assistant, "_flag_on", lambda: True)
    monkeypatch.setattr(assistant, "_bridge_url", lambda: _stop())
    scopes(SCOPED)
    with pytest.raises(HTTPException) as e:
        _run(assistant.assistant_ask(None, {"prompt": "x"}, current_developer=_admin(), db=None))
    assert e.value.status_code == 403
    scopes(FULL)
    with pytest.raises(HTTPException) as e:
        _run(assistant.assistant_ask(None, {"prompt": "x"}, current_developer=_admin(), db=None))
    assert e.value.status_code == 418                               # past the gate

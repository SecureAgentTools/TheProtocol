"""§MCPTEST30 (V0636): the admin developer tools on the run's own developers, and the flare tools on their agents
(agentvault2-aa; step 2 of sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md).

On V0635 each admin tool here passed on one refusal: 404 "Developer 999999 not found". Here every tool does its job
on a developer this run registered for it, through the admin bridge, with a read that shows the effect:

  verification   forceEmailVerify on an account the registration left unverified (is_verified afterwards); where
                 the target verifies at registration there is nothing to verify, and the row says so
  flags          updateDeveloperAdminFlags with the one flag that grants nothing (agents_unlisted_by_default): on,
                 read, off again, read
  API keys       revokeDeveloperApiKeys: the developer's own key works before and is refused after
  2FA            disableDeveloper2FA on an account that enabled 2FA with a real code: getMy2FAStatus reads it off
  password       forceDeveloperPasswordReset: a reset token issued (the mail goes to the target's catcher)
  provisioning   giftProvisioning (one month), reconcileFiatProvisioning (an account with no purchase reconciles none)
  suspension     suspendDeveloper (the developer's token is refused afterwards), reinstateDeveloper (a fresh login
                 works again)
  deletion       softDeleteDeveloper last: deleted_at set, the login refused
  invite codes   generateInviteCodes makes one code with the run's note (V0637: the measured row, where the phase-6
                 sweep used to make a code of its own and leave it unused, with no note and no expiry),
                 revokeInviteCode revokes it, then refused as gone

The flare lifecycle grants a developer of the run an encirclement-class tier (grantFiatFlare), and that developer
equips it on its first agent (equipFlare), sets its variant and overlay there (setFlareVariant, setFlareOverlay),
moves it to its second agent (moveFlare); revokeFiatFlare takes it back. Cosmetic only: nothing moves.

Not here: refundFiatPurchase, replayFiatPurchase and resendFiatMagicLink (a fiat purchase exists only after a Stripe
checkout and its webhook; the run makes none), tegTreasuryIssue (his decision D9: no automated mint, so the tester
never mints), simulationFundingPreview (it runs the former network's host script, which no current frame carries).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, effect, effect_name, effect_unmeasured, lc, refusal_step, said, step,
)

ADMIN = "admin"
DEV_TOOLS = (
    "theprotocol_forceEmailVerify", "theprotocol_updateDeveloperAdminFlags", "theprotocol_revokeDeveloperApiKeys",
    "theprotocol_disableDeveloper2FA", "theprotocol_forceDeveloperPasswordReset", "theprotocol_giftProvisioning",
    "theprotocol_reconcileFiatProvisioning", "theprotocol_suspendDeveloper", "theprotocol_reinstateDeveloper",
    "theprotocol_softDeleteDeveloper", "theprotocol_revokeInviteCode", "theprotocol_generateInviteCodes",
)
FLARE_ADMIN = ("theprotocol_grantFiatFlare", "theprotocol_revokeFiatFlare")
FLARE_DEV = ("theprotocol_equipFlare", "theprotocol_setFlareVariant", "theprotocol_setFlareOverlay",
             "theprotocol_moveFlare")


async def _admin_read(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return False, {}, ""
    ok, body, code = await rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=20)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


def _bug(outcomes: Dict[str, dict], tool: str, why: str, *, own: bool = False) -> None:
    name = tool if own else effect_name(tool)
    lc()._bugfind(outcomes, name, "3" if own else "admin_effect", f"{tool.replace('theprotocol_', '')}: {why}")


def _passed(outcomes: Dict[str, dict], tool: str) -> bool:
    row = outcomes.get(effect_name(tool))
    return bool(row and row.get("healthy"))


def _reads(key: str, *want: Any):
    def check(answer: Dict[str, Any]) -> Optional[str]:
        return None if answer.get(key) in want else f"the answer reads {key}={answer.get(key)!r}, not {list(want)}"
    return check


async def _dev_detail(bag: Any, parse: Any, dev_id: int) -> Tuple[bool, Dict[str, Any], str]:
    return await _admin_read(bag, parse, "theprotocol_getAdminDeveloperDetail", {"developer_id": dev_id})


async def _detail_shows(bag: Any, parse: Any, outcomes: Dict[str, dict], tool: str, dev_id: int, key: str,
                        want: Any = None, *, present: Optional[bool] = None) -> None:
    if not _passed(outcomes, tool):
        return
    ok, d, code = await _dev_detail(bag, parse, dev_id)
    if not ok:
        _bug(outcomes, tool, f"the developer's detail could not be read afterwards (HTTP {code})")
        return
    v = d.get(key)
    if present is not None:
        if bool(v) != present:
            _bug(outcomes, tool, f"the developer's detail reads {key}={v!r} afterwards")
    elif v != want:
        _bug(outcomes, tool, f"the developer's detail reads {key}={v!r} afterwards, not {want!r}")


async def _works(rpc: Any, parse: Any, token: str) -> bool:
    """Whether `token` (a developer JWT or API key) still opens the developer's own profile."""
    ok, body, _code = await rpc("theprotocol_getMyDeveloperProfile", {}, jwt=token, timeout=20)
    return bool(ok)


async def lifecycle_earn_developer_admin(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The admin developer tools, each on a developer of this run's own (the module docstring)."""
    if getattr(bag, "rpc_admin", None) is None:
        for tool in DEV_TOOLS:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    t = Throwaways(rpc, parse, bag, "developer-admin")
    try:
        await _developer_steps(rpc, parse, bag, outcomes, t)
    except Exception as e:                                             # noqa: BLE001
        for tool in DEV_TOOLS:
            if effect_name(tool) not in outcomes:
                effect_unmeasured(outcomes, tool, f"the lifecycle raised {type(e).__name__}: {str(e)[:160]} before it "
                                                  f"reached this tool")
    finally:
        await t.close()


async def _developer_steps(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], t: Throwaways) -> None:
    await _invite_code(bag, parse, outcomes)
    dev = await t.developer("developer-admin", verify=False)
    if not dev.get("access_token"):
        for tool in DEV_TOOLS:
            if effect_name(tool) not in outcomes:
                effect_unmeasured(outcomes, tool, f"no developer of the run's own could be made: {dev.get('why')}")
        return
    dev_id = int(dev["developer_id"])

    # ── verification ─────────────────────────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_forceEmailVerify"
    ok, ans = await effect(bag, parse, tool, {"developer_id": dev_id}, outcomes, check=_reads("status", "verified"))
    if not ok and "already verified" in said(ans).lower():
        effect_unmeasured(outcomes, tool, "this target verifies an account when it registers, so the run has no "
                                          "unverified account of its own to verify")
    await _detail_shows(bag, parse, outcomes, tool, dev_id, "is_verified", True)

    # ── the one flag that grants nothing ─────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_updateDeveloperAdminFlags"
    await effect(bag, parse, tool, {"developer_id": dev_id, "admin_flags": {"agents_unlisted_by_default": True}},
                 outcomes, check=_reads("agents_unlisted_by_default", True))
    await _detail_shows(bag, parse, outcomes, tool, dev_id, "agents_unlisted_by_default", True)
    ok_off, off, _c = await _admin_read(bag, parse, tool, {"developer_id": dev_id,
                                                           "admin_flags": {"agents_unlisted_by_default": False}})
    if _passed(outcomes, tool) and not (ok_off and off.get("agents_unlisted_by_default") is False):
        _bug(outcomes, tool, f"the flag could not be turned off again (it reads {off.get('agents_unlisted_by_default')!r})")

    # ── the developer's own API key, revoked ─────────────────────────────────────────────────────────────────────
    tool = "theprotocol_revokeDeveloperApiKeys"
    okk, body, codek = await rpc("theprotocol_createApiKey", {"key_name": "mcp-earn-revoke"}, jwt=dev["access_token"],
                                 timeout=20)
    made = parse(body) if isinstance(body, dict) else {}
    key = (made.get("plain_api_key") or made.get("api_key")) if okk and isinstance(made, dict) else None
    if not key:
        effect_unmeasured(outcomes, tool, f"the run's own developer could not make an API key (HTTP {codek})")
    else:
        if not await _works(rpc, parse, key):
            effect_unmeasured(outcomes, tool, "the developer's new API key opened nothing before it was revoked, so "
                                              "its refusal afterwards would prove nothing")
        else:
            await effect(bag, parse, tool, {"developer_id": dev_id}, outcomes)
            if _passed(outcomes, tool) and await _works(rpc, parse, key):
                _bug(outcomes, tool, "the developer's API key still opens its profile after the revoke")

    # ── 2FA, enabled with a real code, disabled by the administrator ─────────────────────────────────────────────
    await _two_factor(rpc, parse, bag, outcomes, dev, dev_id)

    # ── password reset, provisioning ─────────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_forceDeveloperPasswordReset"
    await effect(bag, parse, tool, {"developer_id": dev_id}, outcomes, check=_reads("status", "reset_token_issued"))
    tool = "theprotocol_giftProvisioning"
    ok, ans = await effect(bag, parse, tool, {"developer_id": dev_id, "months": 1,
                                              "reason": "MCP tester: its own developer"}, outcomes,
                           check=lambda a: None if a.get("developer_id") == dev_id
                           else f"the answer names developer {a.get('developer_id')!r}")
    if not ok and "mainframe-only" in said(ans).lower():
        effect_unmeasured(outcomes, tool, "this target is no mainframe: provisioning is gifted only on one")
    tool = "theprotocol_reconcileFiatProvisioning"
    await effect(bag, parse, tool, {"developer_id": dev_id}, outcomes,
                 check=lambda a: None if a.get("developer_id", dev_id) == dev_id
                 else f"the answer names developer {a.get('developer_id')!r}")

    # ── suspension: the token refused; reinstatement: a fresh login works ───────────────────────────────────────
    tool = "theprotocol_suspendDeveloper"
    await effect(bag, parse, tool, {"developer_id": dev_id, "reason": "MCP tester: its own developer"}, outcomes,
                 check=_reads("status", "suspended"))
    await _detail_shows(bag, parse, outcomes, tool, dev_id, "is_suspended", True)
    if _passed(outcomes, tool) and await _works(rpc, parse, dev["access_token"]):
        _bug(outcomes, tool, "the developer's token still opens its profile after the suspension")
    tool = "theprotocol_reinstateDeveloper"
    await effect(bag, parse, tool, {"developer_id": dev_id}, outcomes,
                 check=lambda a: None if a.get("developer_id", dev_id) == dev_id and a.get("status") != "suspended"
                 else f"the answer reads status={a.get('status')!r}")
    await _detail_shows(bag, parse, outcomes, tool, dev_id, "is_suspended", False)
    if _passed(outcomes, tool):
        fresh = await t.relogin(dev)
        if not fresh or not await _works(rpc, parse, fresh):
            _bug(outcomes, tool, "the reinstated developer cannot log in and open its profile")

    # ── deletion, last ───────────────────────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_softDeleteDeveloper"
    await refusal_step(bag.rpc_admin, parse, tool, ADMIN,
                       {"developer_id": dev_id, "reason": "MCP tester: a confirmation for another address",
                        "confirm_email": "mcp-earn-not-the-address@throwaway-pl.example.com"},
                       bag.developer_jwt, outcomes, "with a confirmation naming another address", codes=(400,),
                       text="confirm_email")
    ok, _ = await effect(bag, parse, tool, {"developer_id": dev_id, "reason": "MCP tester: its own developer, removed",
                                            "confirm_email": dev["email"]}, outcomes,
                         check=_reads("status", "deleted"))
    await _detail_shows(bag, parse, outcomes, tool, dev_id, "deleted_at", present=True)
    if ok:
        t.forget_developer(dev["email"])
        if await t.relogin(dev):
            _bug(outcomes, tool, "the deleted developer can still log in")


async def _two_factor(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], dev: Dict[str, Any],
                      dev_id: int) -> None:
    tool = "theprotocol_disableDeveloper2FA"
    jwt = dev["access_token"]
    ok, body, code = await rpc("theprotocol_setup2FA", {"password": dev["password"]}, jwt=jwt, timeout=20)
    r = parse(body) if isinstance(body, dict) else {}
    secret = (r.get("secret_raw") or r.get("secret") or "") if ok and isinstance(r, dict) else ""
    if not secret:
        effect_unmeasured(outcomes, tool, f"the run's own developer could not set up 2FA (HTTP {code})")
        return
    ok, body, code = await rpc("theprotocol_verify2FA", {"code": lc().totp_code(secret)}, jwt=jwt, timeout=20)
    okst, st, _c = await _status(rpc, parse, jwt)
    if not (ok and okst and st.get("enabled") is True):
        effect_unmeasured(outcomes, tool, f"the run's own developer could not enable 2FA (HTTP {code}); there is "
                                          f"nothing to disable")
        return
    await effect(bag, parse, tool, {"developer_id": dev_id, "reason": "MCP tester: its own developer"}, outcomes,
                 check=_reads("status", "2fa_disabled"))
    if _passed(outcomes, tool):
        okst, st, _c = await _status(rpc, parse, jwt)
        if not okst or st.get("enabled") is not False:
            _bug(outcomes, tool, f"getMy2FAStatus reads {st.get('enabled')!r} after the administrator disabled 2FA")


async def _status(rpc: Any, parse: Any, jwt: str) -> Tuple[bool, Dict[str, Any], str]:
    ok, body, code = await rpc("theprotocol_getMy2FAStatus", {}, jwt=jwt, timeout=20)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


async def _invite_code(bag: Any, parse: Any, outcomes: Dict[str, dict]) -> None:
    tool = "theprotocol_revokeInviteCode"
    note = "MCP tester: generated to be revoked"

    def _one_code(a: Dict[str, Any]) -> Optional[str]:
        codes = a.get("codes") if isinstance(a.get("codes"), list) else []
        if len(codes) == 1 and isinstance(codes[0], dict) and codes[0].get("code"):
            return None if codes[0].get("note") in (None, note) else f"the code's note reads {codes[0].get('note')!r}"
        return f"the answer carries {len(codes)} codes, not the one asked for"
    ok, ans = await effect(bag, parse, "theprotocol_generateInviteCodes", {"count": 1, "note": note}, outcomes,
                           check=_one_code)
    codes = ans.get("codes") if isinstance(ans, dict) and isinstance(ans.get("codes"), list) else []
    first = codes[0] if codes else None
    value = (first.get("code") if isinstance(first, dict) else first) if first else None
    if not isinstance(value, str) or not value:
        effect_unmeasured(outcomes, tool, "no invite code of the run's own could be generated")
        return
    ok, _ = await effect(bag, parse, tool, {"code": value}, outcomes)
    if ok:
        await refusal_step(bag.rpc_admin, parse, tool, ADMIN, {"code": value}, bag.developer_jwt, outcomes,
                           "a code already revoked", codes=(404,), text="not found")


async def lifecycle_earn_flare(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """grantFiatFlare -> equipFlare -> setFlareVariant -> setFlareOverlay -> moveFlare -> revokeFiatFlare, on a
    developer of this run's own and its two agents (the module docstring)."""
    if getattr(bag, "rpc_admin", None) is None:
        for tool in FLARE_ADMIN:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    t = Throwaways(rpc, parse, bag, "flare")
    try:
        await _flare_steps(rpc, parse, bag, outcomes, t)
    except Exception as e:                                             # noqa: BLE001
        why = f"the lifecycle raised {type(e).__name__}: {str(e)[:160]} before it reached this tool"
        for tool in FLARE_ADMIN:
            if effect_name(tool) not in outcomes:
                effect_unmeasured(outcomes, tool, why)
        for tool in FLARE_DEV:
            outcomes.setdefault(tool, lc()._not_measured(tool, "3", f"NOT MEASURED: {why}"))
    finally:
        await t.close()


async def _flare_steps(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], t: Throwaways) -> None:
    dev = await t.developer("flare")
    a1 = await t.agent(dev, "a")
    a2 = await t.agent(dev, "b")
    if a1.get("why") or a2.get("why"):
        why = a1.get("why") or a2.get("why")
        for tool in FLARE_ADMIN:
            effect_unmeasured(outcomes, tool, f"no developer and two agents of the run's own: {why}")
        for tool in FLARE_DEV:
            outcomes[tool] = lc()._not_measured(tool, "3", f"NOT MEASURED: no agents of the run's own: {why}")
        return
    dev_id, jwt = int(dev["developer_id"]), dev["access_token"]
    tool = "theprotocol_grantFiatFlare"
    ok, _ = await effect(bag, parse, tool, {"developer_id": dev_id, "flare_tier": "shadow_chancellor"}, outcomes,
                         check=_reads("flare_tier", "shadow_chancellor"))
    if not ok:
        for t2 in FLARE_DEV:
            outcomes[t2] = lc()._not_measured(t2, "3", "NOT MEASURED: the developer of the run's own holds no flare "
                                                       "(grantFiatFlare did not grant one)")
        effect_unmeasured(outcomes, "theprotocol_revokeFiatFlare", "no flare was granted, so none could be revoked")
        return
    await step(rpc, parse, "theprotocol_getDeveloperFlare", "1", {"developer_id": dev_id}, jwt, outcomes,
               record_as_separate=False, verify_against=effect_name(tool),
               verify_against_check=lambda a: None if a.get("flare_tier") == "shadow_chancellor"
               else f"getDeveloperFlare reads flare_tier={a.get('flare_tier')!r}")
    ok, _ = await step(rpc, parse, "theprotocol_equipFlare", "3",
                       {"slot": "encirclement", "agent_did": a1["did"], "variant": "sauron"}, jwt, outcomes)
    await step(rpc, parse, "theprotocol_setFlareVariant", "3", {"agent_did": a1["did"], "variant": "sauron"}, jwt,
               outcomes)
    v = outcomes.get("theprotocol_setFlareVariant") or {}
    if v.get("healthy") and (v.get("result_excerpt") or {}).get("flare_encirclement_variant") not in (None, "sauron"):
        _bug(outcomes, "theprotocol_setFlareVariant", "the answer names another variant", own=True)
    await step(rpc, parse, "theprotocol_setFlareOverlay", "3", {"agent_did": a1["did"], "overlay": "glitch"}, jwt,
               outcomes)
    o = outcomes.get("theprotocol_setFlareOverlay") or {}
    if o.get("healthy") and (o.get("result_excerpt") or {}).get("flare_encirclement_overlay") not in (None, "glitch"):
        _bug(outcomes, "theprotocol_setFlareOverlay", "the answer names another overlay", own=True)
    ok, ans = await step(rpc, parse, "theprotocol_moveFlare", "3", {"agent_did": a2["did"]}, jwt, outcomes)
    if ok and ans.get("moved_to_did") != a2["did"]:
        _bug(outcomes, "theprotocol_moveFlare", f"the answer moves it to {ans.get('moved_to_did')!r}", own=True)
    if ok:
        await step(rpc, parse, "theprotocol_getAgentFlare", "1", {"did": a2["did"]}, jwt, outcomes,
                   record_as_separate=False, verify_against="theprotocol_moveFlare",
                   verify_against_check=lambda a: None if a.get("flare_tier") == "shadow_chancellor"
                   else f"getAgentFlare reads the second agent's tier as {a.get('flare_tier')!r} after the move")
    tool = "theprotocol_revokeFiatFlare"
    ok, _ = await effect(bag, parse, tool, {"developer_id": dev_id}, outcomes,
                         check=lambda a: None if a.get("status") != "no_flare_to_revoke" else "it found no flare")
    if ok:
        await step(rpc, parse, "theprotocol_getDeveloperFlare", "1", {"developer_id": dev_id}, jwt, outcomes,
                   record_as_separate=False, verify_against=effect_name(tool),
                   verify_against_check=lambda a: None if not a.get("flare_tier")
                   else f"getDeveloperFlare still reads flare_tier={a.get('flare_tier')!r}")


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_developer_admin", "runner": lifecycle_earn_developer_admin},
    {"name": "earn_flare", "runner": lifecycle_earn_flare},
]
